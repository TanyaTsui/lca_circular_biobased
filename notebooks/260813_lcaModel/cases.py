"""
RAW cases, loaded from the Google Sheet - there are no case parameters in this file.

Sheet tabs -> data/processed/raw_*.csv (written by 01c_dataPrep_productLCI.ipynb) -> `load_raw_cases`:
    raw_cases       one row per case: raw_case (= case_name in product_LCIs), display_name, comments
    raw_bom         production / repair bill of materials
    raw_chain       production / repair process chains (machine weight, power, output, lifetime, ...)
    raw_parameters  repair settings, end-of-life shares, disposal grid location

The product *mass* of a case is not defined here - it comes from `product_LCIs` (the `raw_*` rows) as a
function of the product spec.

Scaled-up variants are also sheet-driven (tab `processes_typicalValues`, saved as machine_params.csv):
    - a PRODUCTION step whose `step_name` is exactly a `machining process` on that tab takes that machine's
      LARGE-scale machine weight, machine lifetime, output efficiency and power from the sheet;
    - every other step (and the whole repair chain, BOM, lifetimes and end of life) is left unchanged.
"""
from dataclasses import replace
from pathlib import Path

import pandas as pd

from lca_engine import BOMItem, EolShares, ProcessStep, RawCase, RepairSpec

MATERIAL_SOURCES = {"virgin", "co-product", "recycled", "wild-harvested"}
MACHINE_SOURCES = {"virgin", "recycled"}

# column names of the sheet tabs (labels, not values)
_COLUMNS = {
    "raw_cases": ["raw_case", "display_name", "comments"],
    "raw_bom": ["raw_case", "stage", "material_name", "material_source", "percentage"],
    "raw_chain": ["raw_case", "stage", "step_order", "step_name", "machine_weight_kg", "power_kW",
                  "output_efficiency_kg_per_hr", "machine_lifetime_hrs", "retained_pct",
                  "electricity_location", "machine_source"],
    "raw_parameters": ["raw_case", "parameter", "value", "unit"],
}
_PARAMETERS = ["repair_enabled", "repair_material_pct_of_product", "expected_lifetime",
               "lifetime_extension_per_repair", "number_of_repair_events",
               "eol_share_composted", "eol_share_recycled_open_loop", "eol_share_recycled_closed_loop",
               "eol_share_incinerated", "eol_share_landfilled", "disposal_electricity_location"]


def _read(data_dir, name):
    path = Path(data_dir) / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run 01c_dataPrep_productLCI.ipynb")
    df = pd.read_csv(path, dtype={"value": str})
    missing = [c for c in _COLUMNS[name] if c not in df.columns]
    if missing:
        raise ValueError(f"Sheet tab '{name}': missing columns {missing} (has {list(df.columns)})")
    return df


def load_raw_cases(data_dir) -> dict:
    """{raw_case_id: RawCase} built from the raw_* tabs of the sheet (exported by 01c)."""
    cases, bom, chain, par = (_read(data_dir, n) for n in ("raw_cases", "raw_bom", "raw_chain", "raw_parameters"))
    out = {}
    for _, c in cases.iterrows():
        cid = c["raw_case"]

        def bom_items(stage):
            rows = bom[(bom["raw_case"] == cid) & (bom["stage"] == stage)]
            bad = set(rows["material_source"]) - MATERIAL_SOURCES
            if bad:
                raise ValueError(f"raw_bom: {cid}/{stage}: unknown material_source {sorted(bad)} (use {sorted(MATERIAL_SOURCES)})")
            return [BOMItem(r.material_name, float(r.percentage), r.material_source) for r in rows.itertuples()]

        def steps(stage):
            rows = chain[(chain["raw_case"] == cid) & (chain["stage"] == stage)].sort_values("step_order")
            bad = set(rows["machine_source"]) - MACHINE_SOURCES
            if bad:
                raise ValueError(f"raw_chain: {cid}/{stage}: unknown machine_source {sorted(bad)} (use {sorted(MACHINE_SOURCES)})")
            return [ProcessStep(r.step_name, float(r.machine_weight_kg), float(r.power_kW),
                                float(r.output_efficiency_kg_per_hr), float(r.machine_lifetime_hrs),
                                r.electricity_location, float(r.retained_pct), r.machine_source)
                    for r in rows.itertuples()]

        p = par[par["raw_case"] == cid].set_index("parameter")["value"].to_dict()
        missing = [k for k in _PARAMETERS if k not in p]
        if missing:
            raise ValueError(f"raw_parameters: case '{cid}' is missing parameters {missing}")
        f = lambda k: float(p[k])
        eol = EolShares(composted=f("eol_share_composted"), recycled_open=f("eol_share_recycled_open_loop"),
                        recycled_closed=f("eol_share_recycled_closed_loop"), incinerated=f("eol_share_incinerated"),
                        landfilled=f("eol_share_landfilled"), disposal_location=p["disposal_electricity_location"])
        repair = RepairSpec(enabled=bool(int(f("repair_enabled"))), material_pct_of_product=f("repair_material_pct_of_product"),
                            expected_lifetime_yr=f("expected_lifetime"), extension_per_repair_yr=f("lifetime_extension_per_repair"),
                            n_repairs=int(f("number_of_repair_events")))
        case = RawCase(case_id=cid, name=c["display_name"], production_bom=bom_items("production"),
                       production_chain=steps("production"), eol=eol, repair=repair,
                       repair_bom=bom_items("repair"), repair_chain=steps("repair"),
                       notes="" if pd.isna(c["comments"]) else c["comments"])
        if not case.production_bom or not case.production_chain:
            raise ValueError(f"raw case '{cid}' has no production BOM or production chain in the sheet")
        out[cid] = case
    return out


# ── Scaled-up variants (sheet-driven, see module docstring) ───────────────────
SHEET_MACHINE_PARAMS = {          # `parameter` label on processes_typicalValues -> ProcessStep field
    "machine weight": "kg_machine",
    "machine lifetime": "machine_lifetime_hrs",
    "output efficiency": "rate_kg_per_hr",
    "power": "power_kW",
}


def _large_scale(machine_params: pd.DataFrame) -> pd.DataFrame:
    large = machine_params.pivot(index="machining_process", columns="parameter", values="large_scale")
    missing = set(SHEET_MACHINE_PARAMS) - set(large.columns)
    if missing:
        raise ValueError(f"machine_params.csv is missing parameters {sorted(missing)} - check the sheet tab")
    return large


def scale_up_case(case: RawCase, machine_params: pd.DataFrame) -> RawCase:
    """Copy of `case` whose production steps that exist on the sheet's machine tab use the large-scale values."""
    large = _large_scale(machine_params)
    chain = []
    for st in case.production_chain:
        if st.step_name in large.index:
            chain.append(replace(st, **{field: float(large.loc[st.step_name, label])
                                        for label, field in SHEET_MACHINE_PARAMS.items()}))
        else:
            chain.append(st)
    return replace(case, name=f"{case.name} - scaled up", production_chain=chain,
                   notes=(case.notes + " | scaled up: production machines from the sheet's large-scale column").strip(" |"))


def scaled_up_variants(cases: dict, ds) -> dict:
    """{raw_case_id: [scaled-up RawCase]} for ds.raw_variants."""
    return {cid: [scale_up_case(c, ds.machine_params)] for cid, c in cases.items()}


def compare_chains(cases: dict, case_id: str, ds) -> pd.DataFrame:
    """Production chain of a RAW case, today vs. scaled up, as one table (to check what changed)."""
    base = cases[case_id]
    up = scale_up_case(base, ds.machine_params)
    on_sheet = set(_large_scale(ds.machine_params).index)
    rows = []
    for a, b in zip(base.production_chain, up.production_chain):
        rows.append({"step": a.step_name,
                     "source of scaled-up values": "sheet: processes_typicalValues (large scale)"
                     if a.step_name in on_sheet else "unchanged (no machine of this name on the sheet)",
                     "machine kg": f"{a.kg_machine:g} -> {b.kg_machine:g}",
                     "power kW": f"{a.power_kW:g} -> {b.power_kW:g}",
                     "output kg/hr": f"{a.rate_kg_per_hr:g} -> {b.rate_kg_per_hr:g}",
                     "lifetime hrs": f"{a.machine_lifetime_hrs:g} -> {b.machine_lifetime_hrs:g}"})
    return pd.DataFrame(rows)
