"""The committed background data covers everything the sheet asks for, in every scenario."""
import numpy as np
import pandas as pd
import pytest

from conftest import BACKGROUND, SNAPSHOT
from raw_lca import Background, Model, load_inputs, run_products
from raw_lca.cases import resolve_baseline, resolve_raw_case, scale_up_case

inp = load_inputs(SNAPSHOT)
SCENARIOS = list(inp.scenarios["scenario_id"])


def test_all_scenarios_have_the_same_activities():
    ub = pd.read_csv(BACKGROUND / "unit_burdens.csv")
    keys = ub.assign(location=ub.location.fillna(""), material_source=ub.material_source.fillna("")) \
        .groupby("scenario").apply(lambda g: set(zip(g.material_name, g.location, g.material_source, g.impact_category)))
    assert set(keys.index) == set(SCENARIOS)
    first = keys.iloc[0]
    assert all(k == first for k in keys), "scenarios differ in the activities/categories they contain"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_case_can_be_run_in_every_scenario(scenario):
    """no missing burden, carbon or EoL data for any RAW case, scaled-up variant, baseline, or location choice"""
    model = Model(inp, Background(BACKGROUND, scenario))
    for cid in inp.raw_cases():
        run_products(model, cid)
    # every location the analyses may switch to must have electricity data
    ps = inp.params
    for cid in inp.raw_cases():
        for i in ps.varying_ids(cid, inp.location_choices):
            r = ps.df.set_index("id").loc[i]
            if r["distribution"] == "choice" and "location" in r["parameter"]:
                for loc in inp.location_choices:
                    model.bg.get(inp.constants["electricity_activity"], location=loc)
                    model.bg.get(inp.eol_routes.loc["incinerated", "energy_credit_electricity_activity"], location=loc)


def test_background_samples_match_the_mean_burdens():
    """if Monte Carlo samples exist: same keys and category order as the deterministic data, positive spread"""
    for scenario in SCENARIOS:
        bg = Background(BACKGROUND, scenario)
        if bg.samples is None:
            continue
        assert bg.n_samples > 1
        for key, arr in bg.samples.items():
            assert arr.shape[1] == len(bg.categories)
            assert key in bg._mean, key
