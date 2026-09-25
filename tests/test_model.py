"""
Model tests.
 1. golden: reproduces the frozen results of 02_model.ipynb (its biopol setup, 1 kg) for three backgrounds.
    02_model multiplied the electricity credit of incineration (MJ of fuel energy) by a burden per kWh; the new model
    converts MJ to kWh (constant mj_per_kwh = 3.6 on the sheet). Setting it to 1 reproduces 02_model exactly.
 2. the unit fix changes only the incineration electricity credit, by the factor 1/3.6.
"""
import json

import numpy as np
import pytest

from conftest import BACKGROUND, GOLDEN, SNAPSHOT
from raw_lca import Background, Model, load_inputs
from raw_lca.cases import BOMItem, EolShares, ProcessStep, RawCase, RepairSpec

SCENARIOS = ["baseline", "image_SSP2-M_2050", "image_SSP2-L_2050"]

# the biopol setup of 02_model.ipynb (lives here because it is a test fixture, not a RAW case of the sheet)
FIXTURE = RawCase(
    case_id="fixture", name="02_model.ipynb biopol",
    production_bom=[BOMItem("Pea protein binder", 70, "virgin"), BOMItem("Sawdust", 20, "co-product"),
                    BOMItem("Seagrass", 10, "wild-harvested")],
    production_chain=[ProcessStep("Mixing", 80, 1.5, 15.0, 15000, "NL", 98),
                      ProcessStep("3D printing", 250, 2.5, 0.5, 20000, "NL", 92, "recycled"),
                      ProcessStep("Baking", 500, 8.0, 4.0, 25000, "NL", 30)],
    eol=EolShares(30, 20, 30, 10, 10, "NL"), repair=RepairSpec(10, 20, 10, 3),
    repair_bom=[BOMItem("Pea protein binder", 80, "virgin"), BOMItem("Seagrass", 10, "wild-harvested"),
                BOMItem("Hemp fiber", 10, "virgin")],
    repair_chain=[ProcessStep("Mixing", 80, 1.5, 15.0, 15000, "NL", 98), ProcessStep("3D printing", 250, 2.5, 0.5, 20000, "NL", 92)])


@pytest.fixture(scope="module")
def inp():
    inp = load_inputs(SNAPSHOT)
    assert inp.reference_service_life == 50, "fixture life is 50 yr; scaling factor must be 1"
    return inp


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_golden_02_model(inp, scenario):
    bg = Background(BACKGROUND, scenario)
    m = Model(inp, bg, constant_overrides={"mj_per_kwh": 1.0})
    m.lhv = 16.4      # 02_model used LHV = 16.4 MJ/kg for 'RAW product'; the sheet has since been updated to 16.35
    res = m.run_raw(FIXTURE, 1.0)
    gold = json.load(open(GOLDEN))["scenarios"][scenario]
    got = dict(materials=res.materials, production=res.production, repair=res.repair, eol_burden=res.eol_burden,
               sequestration=res.sequestration, circularity=res.circularity)
    for comp, series in gold.items():
        want = np.array([series[c] for c in bg.categories])
        assert np.allclose(got[comp], want, rtol=1e-6, atol=1e-9), f"{scenario}: {comp} differs from 02_model.ipynb"


def test_unit_fix_only_changes_electricity_credit(inp):
    bg = Background(BACKGROUND, "baseline")
    old = Model(inp, bg, constant_overrides={"mj_per_kwh": 1.0}).run_raw(FIXTURE, 1.0)   # sheet LHV, old units
    new = Model(inp, bg).run_raw(FIXTURE, 1.0)
    for comp in ("materials", "production", "repair", "eol_burden", "sequestration"):
        assert np.allclose(getattr(old, comp), getattr(new, comp))
    m = Model(inp, bg)
    kg = 1.0 + 0.1 * 3                                    # product + 3 repairs of 10 %
    elec = bg.get("avoided burden - incineration, electricity", location="NL")
    removed = 0.10 * m.lhv * kg * m.eff_elec * elec * (1 - 1 / 3.6)     # 10 % incinerated
    assert np.allclose(new.circularity - old.circularity, removed)
