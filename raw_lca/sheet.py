"""
Google Sheet -> snapshot -> tables, with validation.

The sheet is the single source of the model's inputs. `fetch_snapshot` saves every tab verbatim as a CSV
(data/sheet_snapshot/<date>/); all results are computed from such a snapshot, so they can be reproduced
without network access even if the sheet changes later.
"""
import datetime
import io
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd

from .formulas import evaluate_formula, formula_variables
from .params import DISTRIBUTIONS, GROUPS

# Id of the Google Sheet (the part of its URL after /d/). The sheet must be viewable by "anyone with the link" for the
# download to work without login. docs/RAW_LCA_inputs_v2.xlsx is the layout it was created from.
SHEET_ID = "1aiMhvFkKEoIe5zj3Iw_sEgMJv2QC-z1JwMJHB3PcIwc"
STATUSES = ("placeholder", "partner estimate", "measured", "literature")
REQUIRED_TABS = ("baselines", "products", "study_setup", "scenarios", "impact_categories", "constants",
                 "eol_routes", "baseline_eol_setup", "gwpbio_table", "dcf_bern", "EoL_constants",
                 "benefits_constants_dataSources", "unit_burdens_dataSources", "processes_typicalValues")
PARAM_COLUMNS = ("case", "group", "stage", "item", "qualifier", "parameter", "description", "unit", "typical",
                 "min", "max", "distribution", "choices", "source", "status", "comments")
CHAIN_PARAMETERS = ("machine weight", "power", "output rate", "machine lifetime", "process yield",
                    "machine source", "electricity location")


def fetch_snapshot(out_dir, sheet_id: str = SHEET_ID) -> Path:
    """Download the whole sheet and write one verbatim CSV per tab into out_dir/<today>/."""
    if not sheet_id:
        raise ValueError("SHEET_ID is not set in raw_lca/sheet.py: open docs/RAW_LCA_inputs_v2.xlsx in Google Sheets, "
                         "share it (anyone with the link can view), and put its id there.")
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    xlsx = urllib.request.urlopen(url).read()
    folder = Path(out_dir) / datetime.date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    book = pd.ExcelFile(io.BytesIO(xlsx))
    for name in book.sheet_names:
        book.parse(name, header=None).to_csv(folder / f"{name}.csv", header=False, index=False)
    (folder / "README.txt").write_text(
        f"Verbatim export of every tab of the RAW LCA Google Sheet ({sheet_id}).\n"
        f"Exported: {datetime.datetime.now():%Y-%m-%d %H:%M}. One CSV per tab; the first row of a tab is its header.\n")
    return folder


def load_tables(snapshot_dir) -> Dict[str, pd.DataFrame]:
    """Read every tab CSV of a snapshot (first row = header; fully empty rows and unnamed empty columns dropped)."""
    tables = {}
    for path in sorted(Path(snapshot_dir).glob("*.csv")):
        df = pd.read_csv(path).dropna(how="all")
        df = df.drop(columns=[c for c in df.columns if str(c).startswith("Unnamed") and df[c].isna().all()])
        tables[path.stem] = df.reset_index(drop=True)
    return tables


@dataclass
class Issue:
    level: str      # "error" or "warning"
    tab: str
    message: str

    def __str__(self):
        return f"[{self.level.upper():7s}] {self.tab}: {self.message}"


def validate(tables: Dict[str, pd.DataFrame]) -> List[Issue]:
    issues: List[Issue] = []
    err = lambda tab, msg: issues.append(Issue("error", tab, msg))
    warn = lambda tab, msg: issues.append(Issue("warning", tab, msg))

    case_tabs = [t for t in tables if t.startswith("case_")]
    if not case_tabs:
        err("case_*", "no partner case tabs (case_<name>) found")
    for t in REQUIRED_TABS:
        if t not in tables:
            err(t, "tab is missing")
    if any(i.level == "error" for i in issues):
        return issues

    # parameter tabs ------------------------------------------------------------------------
    param_frames = []
    for t in case_tabs + ["baselines"]:
        df = tables[t]
        missing = [c for c in PARAM_COLUMNS if c not in df.columns]
        if missing:
            err(t, f"missing columns {missing}")
            continue
        df = df.copy()
        df["qualifier"] = df["qualifier"].fillna("")
        param_frames.append((t, df))
        for col, allowed in (("group", GROUPS), ("distribution", DISTRIBUTIONS), ("status", STATUSES)):
            bad = sorted(set(df[col].dropna()) - set(allowed))
            if bad or df[col].isna().any():
                err(t, f"column '{col}': values must be one of {list(allowed)}, found {bad or 'empty cells'}")
        for r in df.itertuples():
            label = f"{r.case} / {r.stage} / {r.item} / {r.parameter}"
            if r.distribution == "choice":
                continue
            try:
                typ = float(r.typical)
            except (TypeError, ValueError):
                err(t, f"{label}: typical value '{r.typical}' is not a number")
                continue
            lo, hi = pd.to_numeric(r.min, errors="coerce"), pd.to_numeric(r.max, errors="coerce")
            if r.distribution in ("triangular", "uniform") and (pd.isna(lo) or pd.isna(hi)):
                err(t, f"{label}: distribution '{r.distribution}' needs min and max")
            elif pd.notna(lo) and pd.notna(hi) and not (lo <= typ <= hi):
                err(t, f"{label}: expected min <= typical <= max, got {lo} <= {typ} <= {hi}")
        n_placeholder = int((df["status"] == "placeholder").sum())
        if n_placeholder:
            warn(t, f"{n_placeholder} of {len(df)} parameters still have status 'placeholder'")

        # shares add up to 100 (at typical values)
        def check_sum(mask, what):
            for keys, g in df[mask].groupby(["case", "stage"] if what == "BOM" else ["case", "item"]):
                total = pd.to_numeric(g["typical"]).sum()
                if abs(total - 100) > 0.5:
                    err(t, f"{what} shares of {keys} add up to {total:g}, not 100")
        check_sum(df["parameter"] == "share of input mass", "BOM")
        check_sum(df["parameter"] == "share of waste", "end-of-life")

    params = pd.concat([d for _, d in param_frames], ignore_index=True) if param_frames else pd.DataFrame()
    if params.empty:
        return issues

    # RAW cases need a complete chain ----------------------------------------------------------
    for t in case_tabs:
        df = tables[t]
        case = df["case"].iloc[0]
        for stage in ("production", "repair"):
            steps = list(dict.fromkeys(df.loc[(df.stage == stage) & (df.parameter == "machine weight"), "item"]))
            if stage == "production" and not steps:
                err(t, "no production process steps (rows with parameter 'machine weight')")
            for s in steps:
                have = set(df.loc[(df.stage == stage) & (df.item == s), "parameter"])
                if set(CHAIN_PARAMETERS) - have:
                    err(t, f"step '{s}' ({stage}) misses parameters {sorted(set(CHAIN_PARAMETERS) - have)}")
        if not ((df.stage == "production") & (df.parameter == "share of input mass")).any():
            err(t, "no production bill of materials (rows with parameter 'share of input mass')")

    # products tab -------------------------------------------------------------------------------
    products = tables["products"]
    known_cases = set(params["case"])
    for r in products.itertuples():
        if r.case_name not in known_cases:
            err("products", f"case '{r.case_name}' has no parameter rows (tabs case_* / baselines)")
            continue
        names = set(params.loc[(params.case == r.case_name) & (params.stage == "product"), "parameter"]) | {r.spec_variable}
        unknown = set(formula_variables(r.formula)) - names
        if unknown:
            err("products", f"{r.case_name} / {r.activity_name}: formula uses unknown names {sorted(unknown)}")
            continue
        vals = {p.parameter: float(p.typical) for p in params[(params.case == r.case_name) & (params.stage == "product")].itertuples()}
        vals[r.spec_variable] = 1.0
        amount = evaluate_formula(r.formula, vals)
        check = pd.to_numeric(r.amount_at_spec_1_check, errors="coerce")
        if pd.notna(check) and abs(amount - check) > 1e-3 * max(1, abs(check)) + 1e-5:
            warn("products", f"{r.case_name} / {r.activity_name}: formula gives {amount:.5g} at spec = 1, sheet check value is {check:.5g}")

    # baseline end-of-life mapping covers every (activity, route) with a share -------------------
    setup = tables["baseline_eol_setup"]
    have = set(zip(setup["activity_name"], setup["route"]))
    b = tables["baselines"]
    for r in b[b.parameter == "share of waste"].itertuples():
        if (r.item, r.qualifier) not in have:
            err("baseline_eol_setup", f"missing row for activity '{r.item}', route '{r.qualifier}' (used in baselines)")
    return issues


def report(issues: List[Issue]) -> None:
    for i in issues:
        print(i)
    n_err = sum(i.level == "error" for i in issues)
    print(f"{n_err} error(s), {len(issues) - n_err} warning(s)")
