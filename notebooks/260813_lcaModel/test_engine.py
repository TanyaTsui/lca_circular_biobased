"""
Checks for the product-level LCA pipeline. Run from this folder:
    python test_engine.py        (or: pytest test_engine.py)

1. formula evaluator: every product-LCI formula reproduces the sheet's activity_amount at FU = 1
2. sheet loader: the raw_* tabs build valid cases; scaled-up variants change only sheet machines
3. regression: the engine reproduces 02_model.ipynb for its biopol setup (BASELINE and a prospective scenario)
   - that setup is a fixture of the 02 notebook and intentionally lives here, not in the sheet
"""
import contextlib
import io
import json
import re

import matplotlib
import pandas as pd

matplotlib.use("Agg")
from cases import load_raw_cases, scale_up_case
from lca_engine import (BOMItem, DataStore, EolShares, ProcessStep, RawCase, RepairSpec, evaluate_formula,
                        run_raw_case)

DATA_DIR = "../../data/processed"

NOTEBOOK02_BIOPOL = RawCase(
    case_id="raw_biopol", name="02_model.ipynb biopol",
    production_bom=[BOMItem("Pea protein binder", 70, "virgin"), BOMItem("Sawdust", 20, "co-product"),
                    BOMItem("Seagrass", 10, "wild-harvested")],
    production_chain=[ProcessStep("Mixing", 80, 1.5, 15.0, 15000, "NL", 98),
                      ProcessStep("3D printing", 250, 2.5, 0.5, 20000, "NL", 92, machine_source="recycled"),
                      ProcessStep("Baking", 500, 8.0, 4.0, 25000, "NL", 30)],
    repair=RepairSpec(True, 10, 20, 10, 3),
    repair_bom=[BOMItem("Pea protein binder", 80, "virgin"), BOMItem("Seagrass", 10, "wild-harvested"),
                BOMItem("Hemp fiber", 10, "virgin")],
    repair_chain=[ProcessStep("Mixing", 80, 1.5, 15.0, 15000, "NL", 98),
                  ProcessStep("3D printing", 250, 2.5, 0.5, 20000, "NL", 92)],
    eol=EolShares(composted=30, recycled_open=20, recycled_closed=30, incinerated=10, landfilled=10, disposal_location="NL"),
)


def test_formulas_reproduce_sheet_at_fu1():
    lci = pd.read_csv(f"{DATA_DIR}/product_lci.csv")
    for r in lci.itertuples():
        val = evaluate_formula(r.formula, {r.spec_var: 1.0})
        assert abs(val - r.sheet_amount_at_fu1) < 1e-3 * max(1, abs(r.sheet_amount_at_fu1)) + 1e-5, (r.case_name, r.activity_name)


def test_formula_evaluator_rejects_code():
    for bad in ("__import__('os')", "span.real", "span if 1 else 2", "open('x')"):
        try:
            evaluate_formula(bad, {"span": 1})
        except ValueError:
            continue
        raise AssertionError(f"evaluator accepted {bad!r}")


def test_sheet_cases_and_scale_up():
    cases = load_raw_cases(DATA_DIR)
    ds = DataStore(DATA_DIR, "baseline")
    assert set(cases) == {"raw_biopol", "raw_timber", "raw_cfw", "raw_knit"}
    machines = set(ds.machine_params["machining_process"])
    for c in cases.values():
        assert abs(sum(i.percentage for i in c.production_bom) - 100) < 0.01
        c.eol.check(c.case_id)
        up = scale_up_case(c, ds.machine_params)
        for a, b in zip(c.production_chain, up.production_chain):
            if a.step_name in machines:
                assert (a.kg_machine, a.power_kW, a.rate_kg_per_hr, a.machine_lifetime_hrs) != \
                       (b.kg_machine, b.power_kW, b.rate_kg_per_hr, b.machine_lifetime_hrs)
            else:
                assert a == b, f"{a.step_name} must be unchanged"
        assert up.repair_chain == c.repair_chain and up.production_bom == c.production_bom and up.eol == c.eol


def _run_notebook02(scenario):
    nb = json.load(open("02_model.ipynb"))
    ns = {}
    with contextlib.redirect_stdout(io.StringIO()):
        for i, cell in enumerate(nb["cells"]):
            if cell["cell_type"] != "code" or i > 41:
                continue
            src = "".join(cell["source"])
            src = re.sub(r'SCENARIO = "[^"]+"', f'SCENARIO = "{scenario}"', src, count=1)
            exec(compile(src, f"02_cell{i}", "exec"), ns)
    return ns


def _check_regression(scenario):
    ns = _run_notebook02(scenario)
    ds = DataStore(DATA_DIR, scenario)
    r = run_raw_case(ds, NOTEBOOK02_BIOPOL, 1.0)
    pairs = {"materials": (ns["material_burdens"], r.materials), "production": (ns["production_process_burdens"], r.production),
             "repair": (ns["repair_burdens"], r.repair), "eol": (ns["eol_burdens"], r.eol_burden),
             "sequestration": (ns["total_sequestration_benefits"], r.sequestration),
             "circularity": (ns["total_circularity_benefits"], r.circularity)}
    for k, (a, b) in pairs.items():
        a, b = a.reindex(ds.categories), b.reindex(ds.categories)
        assert ((a - b).abs() / (a.abs() + 1e-30)).max() < 1e-9, f"{scenario}: {k} differs from 02_model.ipynb"


def test_regression_vs_02_model_baseline():
    _check_regression("baseline")


def test_regression_vs_02_model_prospective():
    _check_regression("image_SSP2-L_2050")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)
