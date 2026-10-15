"""
Regenerates data.js and presets.js of the RAW Impact Explorer from the newest sheet snapshot
(data/sheet_snapshot/<date>/) and the background data (data/background/), using the raw_lca package.

    python build_data.py            # from this folder, in the brightway_env environment

- data.js     RAW_DATA: unit burdens (today and 2050), carbon content, EoL constants and routes, constants,
              GWP_bio and Bern tables - nothing case-specific.
- presets.js  RAW_CASES: the four RAW cases as editable inputs (typical / min / max / scaled-up, with the sheet row
              each number comes from), RAW_BASELINES: the two baselines of each case (typical and 5-95 % of a
              parameter Monte Carlo), RAW_REFERENCE: the Python results of each case, used by check_calc.js.

No numbers are defined here: everything comes from the snapshot, the background data or raw_lca.
"""
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from raw_lca.background import Background  # noqa: E402
from raw_lca.cases import (FILLER_SPLIT, FILLERS, ROUTES, SHARE, SIZE_STAGE, baseline_kind, parse_material,  # noqa: E402
                           repairs_needed, resolve_baseline, resolve_raw_case, scale_up_case)
from raw_lca.formulas import evaluate_formula  # noqa: E402
from raw_lca.inputs import load_inputs  # noqa: E402
from raw_lca.model import Model  # noqa: E402
from raw_lca.params import ParameterSet  # noqa: E402
from raw_lca.paths import BACKGROUND, newest_snapshot  # noqa: E402
from raw_lca.study import activity_amounts, spec_variable  # noqa: E402

TODAY, FUTURE = "baseline", "image_SSP2-L_2050"        # the two backgrounds of the results (scenarios tab, in_results)
N_BASELINE_MC = 500                                     # parameter-only Monte Carlo draws for the baseline whiskers
CHAIN_PARAMS = {"machine weight": "kgMachine", "power": "powerKW", "output rate": "rateKgHr",
                "machine lifetime": "lifetimeHrs", "process yield": "yieldPct"}
PROCESS_ACTIVITIES = {"energy use", "machine wear", "Road transport"}
SPEC_UNIT = {"span": "kg/m span", "length": "kg/m wall length", "coverage": "kg/m² coverage"}


def clean(v):
    """JSON-safe scalar: NaN -> None, numpy -> python."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (np.floating, np.integer)):
        return None if np.isnan(v) else v.item()
    return v


def text(v):
    v = clean(v)
    return "" if v is None else str(v).strip()


# ── cleaned defaults ─────────────────────────────────────────────────────────────────────
# The tool starts from the sheet's numbers, tidied so partners see no avoidable issues: shares and yields (% units)
# within 0-100, no negative values, min <= typical <= max, and (RAW cases only) at most 1 decimal, or 3 significant
# figures below 1. The original sheet values travel with every input (sheet.values) for the export.
SHEET_ROWS = {}            # parameter id -> the uncleaned sheet row


def tidy(x):
    if x is None or x == 0 or not math.isfinite(x):
        return x
    return round(x, 1) if abs(x) >= 1 else float(f"{x:.3g}")


def clean_params(ps, raw_cases):
    df = ps.df.drop(columns=["id", "typical_value"]).copy()
    for i, r in df.iterrows():
        if r.distribution in ("choice", "combination"):
            continue
        vals = {c: float(r[c]) if pd.notna(r[c]) else None for c in ("typical", "min", "max", "scaled_up")}
        for c, v in vals.items():
            if v is None:
                continue
            if str(r.unit).startswith("%"):
                v = min(max(v, 0.0), 100.0)
            v = max(v, 0.0)
            if r.case in raw_cases and r.parameter != FILLER_SPLIT:     # the filler split is not shown, keep it exact
                v = tidy(v)
            vals[c] = v
        t = vals["typical"]
        if vals["min"] is not None:
            vals["min"] = min(vals["min"], t)
        if vals["max"] is not None:
            vals["max"] = max(vals["max"], t)
        for c, v in vals.items():
            df.at[i, c] = v if v is not None else np.nan
    return ParameterSet(df)


def sheet_ref(r):
    """Where a number comes from. `values` = the sheet's own numbers (before the tool tidied them)."""
    raw = SHEET_ROWS.get(r.id)
    ref = {"stage": r.stage, "item": r.item, "qualifier": r.qualifier, "parameter": r.parameter, "unit": text(r.unit),
           "description": text(r.description), "source": text(r.source), "comments": text(r.comments)}
    if raw is not None and raw.distribution not in ("choice", "combination"):
        ref["values"] = {"v": clean(float(raw.typical_value)), "min": clean(raw["min"]), "max": clean(raw["max"]),
                         "up": clean(raw["scaled_up"])}
        notes = [f"{n} {o:g} → {c:g}" for n, o, c in (("typical", raw.typical_value, r.typical_value), ("min", raw["min"], r.min),
                                                         ("max", raw["max"], r.max), ("scaled-up", raw["scaled_up"], r.scaled_up))
                 if pd.notna(o) and pd.notna(c) and abs(float(o) - float(c)) > 1e-12]
        if notes:
            ref["adjusted"] = "Tidied from the sheet: " + ", ".join(notes)
    return ref


def param(r, scalable=False):
    """One editable number of a sheet row. `scalable`: it also gets a scaled-up value `up` (the sheet's `scaled_up`;
    None = same as typical)."""
    p = {"v": clean(float(r.typical_value)), "min": clean(r.min), "max": clean(r.max), "dist": r.distribution,
         "comment": "", "sheet": sheet_ref(r)}
    if p["min"] is None:
        p["min"] = p["v"]
    if p["max"] is None:
        p["max"] = p["v"]
    if scalable:
        p["up"] = clean(r.scaled_up)
    return p


def derived(v, lo, hi, dist, parameter, unit, note, stage="product size", item="product", scalable=True):
    """An input the tool shows that is not one sheet row (derived from several rows). `scalable`: it also gets a
    scaled-up value (None = same as typical)."""
    return {"v": tidy(v), "min": tidy(lo), "max": tidy(hi), "dist": dist, "comment": "", **({"up": None} if scalable else {}),
            "sheet": {"stage": stage, "item": item, "qualifier": "", "parameter": parameter, "unit": unit,
                      "description": note, "source": "derived by the tool", "comments": ""}}


def choice(r):
    return {"v": str(r.typical_value), "comment": "", "sheet": sheet_ref(r)}


def tool_choice(v, stage, item, parameter, note):
    """A choice the tool asks for that is not a sheet row."""
    return {"v": v, "comment": "", "sheet": {"stage": stage, "item": item, "qualifier": "", "parameter": parameter,
                                             "unit": "-", "description": note, "source": "", "comments": ""}}


# ── RAW case inputs ────────────────────────────────────────────────────────────────────
def density_param(inp, case, spec_value):
    """kg of product per unit of spec at the study spec, with the extremes of the size formula over the min/max of
    its 'product size' rows."""
    rows = inp.params.rows(case)
    size = rows[rows.stage == SIZE_STAGE]
    prod = inp.products[inp.products.case_name == case].iloc[0]
    base = {r.parameter: float(r.typical_value) for r in size.itertuples()}
    # rows whose whole range lies below typical are the optimisation savings (savings_param), not density
    varying = [r for r in size.itertuples() if r.distribution != "fixed" and r.min < r.max and not is_saving(r)]
    values = []
    for corner in itertools.product(*[(r.min, r.max) for r in varying]):
        v = dict(base, **{r.parameter: c for r, c in zip(varying, corner)})
        v[prod.spec_variable] = spec_value
        values.append(evaluate_formula(prod.formula, v) / spec_value)
    typical = activity_amounts(inp, case, spec_value)[0][1] / spec_value
    parts = ", ".join(f"{r.parameter} = {r.typical_value:g}" for r in size.itertuples())
    note = (f"kg per {prod.spec_unit} of {prod.spec_label} at {spec_value:g} {prod.spec_unit}, from the "
            f"product_size_formulas formula ({prod.formula}) with {parts}; min/max = formula at the min/max of those rows"
            + "".join(f" ({r.parameter} kept at typical: its range is the material savings below)"
                      for r in size.itertuples() if is_saving(r)))
    return derived(typical, min(values + [typical]), max(values + [typical]), "triangular",
                   "material density", SPEC_UNIT.get(prod.spec_variable, f"kg/{prod.spec_unit}"), note)


def is_saving(r):
    """A design 'product size' row whose range only goes below typical (e.g. CFW fibre length 412.5-550 m/m)."""
    return r.distribution != "fixed" and r.typical_value > 0 and r.min < r.typical_value and r.max <= r.typical_value


def savings_param(inp, case):
    """Typical 0 % (= the sheet's typical mass). The upper bound is the largest reduction of a design 'product size'
    row below its typical value (e.g. CFW fibre length 550 -> 412.5 m/m = 25 %)."""
    rows = inp.params.rows(case)
    size = rows[(rows.stage == SIZE_STAGE) & (rows.distribution != "fixed")]
    cuts = [100 * (1 - r.min / r.typical_value) for r in size.itertuples() if is_saving(r)]
    hi = round(max(cuts), 6) if cuts else 0.0
    note = ("Material saved by the RAW optimisation, relative to the material density above (product mass = density x "
            "spec x (1 - savings)). Typical 0 % reproduces the sheet's typical product mass."
            + (f" Max {hi:g} % = the sheet's min of the product size rows." if hi else ""))
    return derived(0.0, 0.0, hi, "triangular", "material savings from RAW optimisation", "%", note)


def bom_params(inp, case, stage):
    rows = inp.params.rows(case)
    share = rows[(rows.stage == stage) & (rows.parameter == SHARE)]
    fillers = rows[(rows.stage == stage) & (rows.parameter == FILLERS)]
    if not len(fillers):
        return [{"material": r.item, "source": r.qualifier, "share": param(r, stage == "production")} for r in share.itertuples()]
    # recipe with variable fillers: binder row + the typical filler combination, resolved to shares
    b = share.iloc[0]
    split = rows[(rows.stage == stage) & (rows.item == "fillers") & (rows.parameter == FILLER_SPLIT)].iloc[0]
    parts = [parse_material(p) for p in str(fillers.typical_value.iloc[0]).split("+")]
    bv, blo, bhi = float(b.typical_value), float(b["min"]), float(b["max"])
    fv, flo, fhi = float(split.typical_value), float(split["min"]), float(split["max"])
    out = [{"material": b["item"], "source": b["qualifier"], "share": param(next(share.itertuples()), stage == "production")}]
    k = len(parts)
    for j, (m, src) in enumerate(parts):
        if k == 1:
            v, lo, hi = 100 - bv, 100 - bhi, 100 - blo
        elif j == 0:
            v, lo, hi = (100 - bv) * fv / 100, (100 - bhi) * flo / 100, (100 - blo) * fhi / 100
        else:
            v = (100 - bv) * (100 - fv) / 100 / (k - 1)
            lo, hi = (100 - bhi) * (100 - fhi) / 100 / (k - 1), (100 - blo) * (100 - flo) / 100 / (k - 1)
        note = (f"Filler of the recipe ({fillers.typical_value.iloc[0]}): share = (100 - binder share) x share of "
                f"{'the first' if j == 0 else 'the other'} filler, min/max from the binder and filler-split ranges. "
                f"The sheet also varies which fillers are used ({fillers.choices.iloc[0]}); the tool keeps this "
                f"combination.")
        out.append({"material": m, "source": src,
                    "share": derived(v, lo, hi, "triangular", SHARE, "%", note, stage=stage, item=m,
                                     scalable=(stage == "production"))})
    return out


def chain_params(inp, case, stage):
    rows = inp.params.rows(case)
    r = rows[(rows.stage == stage) & (rows.parameter == "machine weight")]
    steps = []
    for name in dict.fromkeys(r.item):
        s = rows[(rows.stage == stage) & (rows.item == name)]
        step = {"name": name}
        for x in s.itertuples():
            if x.parameter in CHAIN_PARAMS:
                step[CHAIN_PARAMS[x.parameter]] = param(x, scalable=(stage == "production"))
            elif x.parameter == "machine source":
                step["machineSource"] = choice(x)
        if stage == "production":     # which product version the step is part of (not on the sheet yet)
            step["usedIn"] = tool_choice("both", "production", name, "used in",
                                         "Not on the sheet yet: whether this step is part of the prototype, the "
                                         "scaled-up product, or both.")
        steps.append(step)
    return steps


def raw_case_inputs(inp, case):
    fu = inp.fu_comparisons.loc[inp.fu_comparisons.raw_case == case].iloc[0]
    prod = inp.products[inp.products.case_name == case].iloc[0]
    var = spec_variable(inp, case)
    spec_value = inp.specs[var]
    rsl = float(fu.service_life)
    rows = inp.params.rows(case)
    lk = {(r.stage, r.item, r.qualifier, r.parameter): r for r in rows.itertuples()}
    get = lambda st, it, pa, q="": lk.get((st, it, q, pa))
    expected, extension = get("use", "product", "expected lifetime"), get("use", "product", "lifetime extension per repair")
    rep_mat = get("repair", "repair material", "share of product mass per repair")
    enabled = extension is not None and rep_mat is not None
    circ = {"enabled": enabled, "expectedLifetime": param(expected, True),
            "repairIn": tool_choice("both", "use", "product", "repair in",
                                    "Not on the sheet yet: whether the prototype, the scaled-up product or both are "
                                    "repaired.")}
    if enabled:
        e, x = param(expected, True), param(extension, True)
        n = repairs_needed(e["v"], x["v"], rsl)
        n_lo, n_hi = repairs_needed(e["max"], x["max"], rsl), repairs_needed(e["min"], x["min"], rsl)
        note = (f"Not on the sheet: the model takes the smallest number of repairs that makes the product last the "
                f"{rsl:g}-yr functional unit, ceil(({rsl:g} - expected lifetime) / extension). min/max = at the "
                f"range ends of those two rows.")
        circ.update(materialPct=param(rep_mat, True), extension=x,
                    numRepairs=derived(float(n), float(min(n_lo, n)), float(max(n_hi, n)), "triangular",
                                       "number of repair events", "#", note, stage="use"))
    else:   # placeholders shown greyed out until a partner switches repair on
        circ.update(materialPct=derived(10.0, 10.0, 10.0, "fixed", "share of product mass per repair", "%",
                                        "No repair on the sheet for this case.", stage="repair", item="repair material"),
                    extension=derived(10.0, 10.0, 10.0, "fixed", "lifetime extension per repair", "yrs",
                                      "No repair on the sheet for this case.", stage="use"),
                    numRepairs=derived(0.0, 0.0, 0.0, "fixed", "number of repair events", "#",
                                       "No repair on the sheet for this case.", stage="use"))
    eol = {route: param(get("end-of-life", "waste", "share of waste", route)) for route in ROUTES}
    return {
        "id": case,
        "name": inp.raw_cases()[case],
        "fuName": text(fu.fu_name),
        "function": text(fu.function),
        "element": text(prod.element_type),
        "spec": {"variable": var, "label": text(prod.spec_label), "unit": text(prod.spec_unit), "value": spec_value},
        "rsl": rsl,
        "baselines": {"bio": text(fu.baseline_biobased), "fossil": text(fu.baseline_fossil)},
        "inputs": {
            "product": {
                "density": density_param(inp, case, spec_value),
                "performance": {"v": None, "min": None, "max": None, "up": None, "unit": "", "dist": "fixed", "comment": "",
                                "sheet": {"stage": "product size", "item": "product", "qualifier": "",
                                          "parameter": "building component performance", "unit": "",
                                          "description": "Not on the sheet: the performance of the component (e.g. "
                                          "structural strength), with its unit. Recorded for the LCA team; not used "
                                          "in the calculation.", "source": "", "comments": ""}},
                "savings": savings_param(inp, case),
            },
            "location": choice(get("general", "product", "location")),
            "productionBom": bom_params(inp, case, "production"),
            "productionChain": chain_params(inp, case, "production"),
            "circularity": circ,
            "repairBom": bom_params(inp, case, "repair") if enabled else [],
            "repairChain": chain_params(inp, case, "repair") if enabled else [],
            "eol": eol,
        },
    }


# ── results computed in Python ───────────────────────────────────────────────────────────
def vectors(r, categories):
    order = [r.categories.index(c) for c in categories]
    pick = lambda a: [float(a[i]) for i in order]
    return {"materials": pick(r.materials), "production": pick(r.production), "repair": pick(r.repair),
            "eolBurden": pick(r.eol_burden), "sequestration": pick(r.sequestration),
            "circularity": pick(r.circularity), "net": pick(r.net)}


def baseline_result(model, inp, b, values, spec_value, rsl, label):
    kg = activity_amounts(inp, b, spec_value, values)[0][1]
    if baseline_kind(inp.params.rows(b)) == "process":
        return model.run_raw(resolve_raw_case(inp.params, b, label, values, rsl), kg, rsl, None, label)
    return model.run_baseline(resolve_baseline(inp.params, b, values), kg, rsl, None, label)


def main():
    snapshot = newest_snapshot()
    inp = load_inputs(snapshot)
    SHEET_ROWS.update({r["id"]: r for _, r in inp.params.df.iterrows()})
    inp.params = clean_params(inp.params, set(inp.fu_comparisons.raw_case))
    models = {s: Model(inp, Background(BACKGROUND, s)) for s in (TODAY, FUTURE)}
    cat_order = [c for c in inp.categories["category"] if c in models[TODAY].bg.categories]
    charted = [c for c, flag in zip(inp.categories["category"], inp.categories["plot_in_bar_charts"])
               if str(flag).lower() == "true" and c in cat_order]
    labels = dict(zip(inp.categories["category"], inp.categories["label"]))

    # ── data.js ──
    ub = pd.read_csv(BACKGROUND / "unit_burdens.csv")
    ub = ub[ub.scenario.isin([TODAY, FUTURE])].fillna({"location": "", "material_source": ""})
    burdens = {}
    for (scn, name, loc, src), g in ub.groupby(["scenario", "material_name", "location", "material_source"]):
        s = g.set_index("impact_category")["score"]
        burdens.setdefault(scn, {})[f"{name}|{loc}|{src}"] = [float(s.get(c, 0.0)) for c in cat_order]
    units = ub.drop_duplicates("impact_category").set_index("impact_category")["impact_category_unit"].to_dict()
    carbon = {r.material_name: {"C": float(r.carbon_content_kgC_per_kgWet),
                                "rot": float(r.rotation_period_yr) if pd.notna(r.rotation_period_yr) else 0.0}
              for r in models[TODAY].bg.materials.reset_index().itertuples()}
    eolc = {name: {"A": clean(r.allocation_factor), "Q": clean(r.quality_ratio),
                   "LHV": clean(r.lower_heating_value_MJperKgDry), "effHeat": clean(r.conversionEfficiency_heat),
                   "effElec": clean(r.conversionEfficiency_electricity)}
            for name, r in inp.eol_constants.iterrows()}
    routes = {route: {"treatment": r.treatment_activity,
                      "cff": r.cff_factor_applies in (True, "True", "TRUE"),
                      "credit": r.material_credit_activity or None,
                      "heat": r.energy_credit_heat_activity or None,
                      "elec": r.energy_credit_electricity_activity or None}
              for route, r in inp.eol_routes.iterrows()}
    g = inp.gwpbio.set_index("rotation_period_yr")
    gcols = [k for k in g.columns if k.startswith("storage_")]
    b = inp.bern.set_index("term")
    keys = {k.split("|")[0] for k in burdens[TODAY]}
    bom_materials = {}
    for k in sorted(burdens[TODAY]):
        name, loc, src = k.split("|")
        if src and name not in PROCESS_ACTIVITIES:
            bom_materials.setdefault(name, []).append(src)
    scen = inp.scenarios.set_index("scenario_id")
    raw_data = {
        "snapshot": snapshot.name,
        "categories": cat_order,
        "chartedCategories": charted,
        "categoryLabels": {c: labels.get(c, c) for c in cat_order},
        "units": {c: units.get(c, "") for c in cat_order},
        "scenarios": {"today": TODAY, "future": FUTURE},
        "scenarioLabels": {TODAY: text(scen.loc[TODAY, "label"]), FUTURE: text(scen.loc[FUTURE, "label"])},
        "burdens": burdens,
        "carbon": carbon,
        "eolConstants": eolc,
        "eolRoutes": routes,
        "constants": {k: clean(v) for k, v in inp.constants.items()},
        "gwpbio": {"rotations": [int(x) for x in g.index], "storage": [int(c.split("_")[1].rstrip("yr")) for c in gcols],
                   "table": [[float(v) for v in g.loc[r, gcols]] for r in g.index]},
        "bern": {"a": [float(b.loc[t, "coefficient_a"]) for t in ("a0", "a1", "a2", "a3")],
                 "tau": [None] + [float(b.loc[t, "time_constant_tau_yr"]) for t in ("a1", "a2", "a3")]},
        "bomMaterials": bom_materials,
        "locations": sorted(k.split("|")[1] for k in burdens[TODAY] if k.startswith(inp.constants["electricity_activity"] + "|")),
        "mcSeed": int(inp.setup.get("mc_seed", 42)),
    }
    missing = {"machine wear", "energy use"} - keys
    if missing:
        raise ValueError(f"background lacks {missing}")
    with open(HERE / "data.js", "w", encoding="utf-8") as f:
        f.write(f"// Auto-generated by build_data.py from data/background/ and sheet snapshot {snapshot.name}. Do not edit.\n")
        f.write("const RAW_DATA = ")
        json.dump(raw_data, f, allow_nan=False, separators=(",", ":"))
        f.write(";\n")

    # ── presets.js ──
    typical = inp.params.typical()
    rng = np.random.default_rng(raw_data["mcSeed"])
    samples = inp.params.sample(N_BASELINE_MC, rng).to_dict("records")
    cases, baselines, reference = [], {}, {}
    for case in inp.fu_comparisons.raw_case:
        c = raw_case_inputs(inp, case)
        cases.append(c)
        spec_value, rsl = c["spec"]["value"], c["rsl"]
        ref, bl = {}, {}
        # Python results at the tool's default values: cleaned parameters, product mass = spec x material density
        kg = spec_value * c["inputs"]["product"]["density"]["v"]
        raw = resolve_raw_case(inp.params, case, c["name"], typical, rsl)
        raw_up = scale_up_case(raw, inp.params, case)
        for key, scn in (("today", TODAY), ("future", FUTURE)):
            proto, up = models[scn].run_raw(raw, kg, rsl), models[scn].run_raw(raw_up, kg, rsl)
            ref[key] = {"prototype": vectors(proto, cat_order), "scaledUp": vectors(up, cat_order),
                        "productKg": proto.info["product_kg"], "serviceLife": proto.info["service_life_yr"]}
            for kind in ("bio", "fossil"):
                bname = c["baselines"][kind]
                if not bname:
                    continue
                label = inp.products.loc[inp.products.case_name == bname, "display_name"].iloc[0]
                draws = np.array([baseline_result(models[scn], inp, bname, v, spec_value, rsl, label).net for v in samples])
                order = [models[scn].bg.categories.index(x) for x in cat_order]
                lo, hi = np.percentile(draws[:, order], [5, 95], axis=0)
                entry = bl.setdefault(kind, {"name": bname, "label": label})
                typ = baseline_result(models[scn], inp, bname, typical, spec_value, rsl, label)
                entry[key] = dict(vectors(typ, cat_order), lo=lo.tolist(), hi=hi.tolist())
        reference[case] = ref
        baselines[case] = bl
        print(f"{case}: product {ref['today']['productKg']:.4g} kg, net GWP prototype "
              f"{ref['today']['prototype']['net'][0]:.4g} / scaled-up {ref['today']['scaledUp']['net'][0]:.4g} / "
              f"scaled-up 2050 {ref['future']['scaledUp']['net'][0]:.4g} kg CO2-eq; baselines "
              + ", ".join(f"{v['label']} {v['today']['net'][0]:.4g}" for v in bl.values()))

    with open(HERE / "presets.js", "w", encoding="utf-8") as f:
        f.write(f"// Auto-generated by build_data.py from sheet snapshot {snapshot.name}. Do not edit: change the sheet,\n"
                f"// fetch a snapshot (pipeline/01_fetch_sheet.py) and rerun build_data.py.\n")
        for name, obj in (("RAW_CASES", cases), ("RAW_BASELINES", baselines), ("RAW_REFERENCE", reference)):
            f.write(f"const {name} = ")
            json.dump(obj, f, allow_nan=False, indent=1 if name == "RAW_CASES" else None,
                      separators=None if name == "RAW_CASES" else (",", ":"))
            f.write(";\n")
    print(f"Wrote {HERE / 'data.js'} and {HERE / 'presets.js'} (snapshot {snapshot.name})")
    print("Check the JS model against these results:  jsc data.js presets.js calc.js check_calc.js")


if __name__ == "__main__":
    main()
