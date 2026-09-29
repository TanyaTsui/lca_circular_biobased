"""Sheet validation, formula evaluator, parameter table, sampling and scale-up."""
import copy

import numpy as np
import pandas as pd
import pytest

from conftest import BACKGROUND, SNAPSHOT
from raw_lca import Background, Model, load_inputs
from raw_lca.cases import resolve_baseline, resolve_raw_case, scale_up_case
from raw_lca.formulas import evaluate_formula
from raw_lca.sheet import load_tables, validate


@pytest.fixture(scope="module")
def tables():
    return load_tables(SNAPSHOT)


@pytest.fixture(scope="module")
def inp():
    return load_inputs(SNAPSHOT)


# ── formulas ──────────────────────────────────────────────────────────────────────────
def test_formula_evaluator_rejects_code():
    for bad in ("__import__('os')", "span.real", "span if 1 else 2", "open('x')", "span; 1"):
        with pytest.raises((ValueError, SyntaxError)):
            evaluate_formula(bad, {"span": 1})


def test_formulas_reproduce_the_sheet_check_values(inp):
    """every product formula at spec = 1 equals the amount_at_spec_1_check column of the products tab"""
    from raw_lca.study import activity_amounts
    for case in inp.products.case_name.unique():
        got = {a: v for a, v, _ in activity_amounts(inp, case, 1.0)}
        for r in inp.products[inp.products.case_name == case].itertuples():
            assert got[r.activity_name] == pytest.approx(float(r.amount_at_spec_1_check), rel=1e-3, abs=1e-5), (case, r.activity_name)


def test_size_constants_vary_except_the_functional_unit(inp):
    """product size constants follow the parameter values; wall_height (part of the FU) is fixed for every wall"""
    from raw_lca.study import activity_amounts
    ps = inp.params
    rows = ps.rows("raw_knit")
    i = rows.loc[(rows.stage == "product size") & (rows.parameter == "areal_density"), "id"].iloc[0]
    lighter = {**ps.typical(), i: 0.8 * float(ps.typical()[i])}
    assert activity_amounts(inp, "raw_knit", 100, lighter)[0][1] == pytest.approx(0.8 * activity_amounts(inp, "raw_knit", 100)[0][1])
    walls = ps.df[(ps.df.stage == "product size") & (ps.df.parameter == "wall_height")]
    s = ps.sample(200, np.random.default_rng(2))
    assert len(walls) == 3 and all((s[w] == 3).all() for w in walls.id)


# ── sheet validation ──────────────────────────────────────────────────────────────────
def test_snapshot_has_no_validation_errors(tables):
    assert [str(i) for i in validate(tables) if i.level == "error"] == []


def _broken(tables, tab, mutate):
    t = copy.deepcopy(tables)
    mutate(t[tab])
    return [str(i) for i in validate(t) if i.level == "error"]


def test_validation_catches_bad_inputs(tables):
    case_tab = next(t for t in tables if t.startswith("lci_raw_"))

    def min_above_typical(df):
        i = df.index[df["distribution"] == "triangular"][0]
        df.loc[i, "min"] = float(df.loc[i, "typical"]) + 1
    assert any("min <= typical <= max" in m for m in _broken(tables, case_tab, min_above_typical))

    def bom_not_100(df):
        i = df.index[df["parameter"] == "share of input mass"][0]
        df.loc[i, "typical"] = float(df.loc[i, "typical"]) + 10
    assert any("add up to" in m for m in _broken(tables, case_tab, bom_not_100))

    def unknown_group(df):
        df.loc[0, "group"] = "nonsense"
    assert any("group" in m for m in _broken(tables, case_tab, unknown_group))

    def bad_formula(df):
        df.loc[0, "formula"] = df.loc[0, "formula"] + " * mystery"
    assert any("unknown names" in m for m in _broken(tables, "product_size_formulas", bad_formula))


# ── parameters ──────────────────────────────────────────────────────────────────────────
def test_sampling_respects_ranges_and_fixed_values(inp):
    ps = inp.params
    s = ps.sample(500, np.random.default_rng(1))
    for r in ps.df.itertuples():
        col = s[r.id]
        if r.distribution == "choice":
            assert (col == r.typical_value).all()
        elif r.min < r.max:
            assert col.min() >= r.min - 1e-9 and col.max() <= r.max + 1e-9
        else:
            assert (col == r.typical_value).all()


def test_from_unit_maps_quantiles_of_the_triangular_distribution(inp):
    ps = inp.params
    i = next(i for i in ps.varying_ids("raw_timber") if ps.df.set_index("id").loc[i, "distribution"] == "triangular")
    r = ps.df.set_index("id").loc[i]
    lo, hi = ps.from_unit(np.array([[0.0], [0.999999]]), [i])[i]
    assert lo == pytest.approx(r["min"], abs=1e-6) and hi == pytest.approx(r["max"], rel=1e-2)
    median = ps.from_unit(np.array([[0.5]]), [i])[i].iloc[0]
    assert r["min"] < median < r["max"]


def test_shares_are_renormalised_after_sampling(inp):
    ps = inp.params
    vals = ps.sample(1, np.random.default_rng(3), vary_choices=False).iloc[0].to_dict()
    case = resolve_raw_case(ps, "raw_biopol", "x", vals, inp.reference_service_life_for("raw_biopol"))
    assert sum(b.percentage for b in case.production_bom) == pytest.approx(100)
    e = case.eol
    assert e.composted + e.recycled_open + e.recycled_closed + e.incinerated + e.landfilled == pytest.approx(100)
    b = resolve_baseline(ps, "glulam beam", vals)
    typical = resolve_baseline(ps, "glulam beam", ps.typical())
    assert sum(e.kg_per_kg for e in b.eol) == pytest.approx(sum(e.kg_per_kg for e in typical.eol))


# ── scaled-up variant ─────────────────────────────────────────────────────────────────────
def test_scale_up_changes_only_sheet_machines(inp):
    ps = inp.params
    for cid, name in inp.raw_cases().items():
        rows = ps.rows(cid)
        scaled_steps = set(rows[(rows.stage == "production") & rows.scaled_up.notna()]["item"])
        base = resolve_raw_case(ps, cid, name, ps.typical(), inp.reference_service_life_for(cid))
        up = scale_up_case(base, ps, cid)
        for a, b in zip(base.production_chain, up.production_chain):
            if a.step_name in scaled_steps:
                assert (a.kg_machine, a.power_kW, a.rate_kg_per_hr, a.machine_lifetime_hrs) != \
                       (b.kg_machine, b.power_kW, b.rate_kg_per_hr, b.machine_lifetime_hrs)
            else:
                assert a == b
        assert up.repair_chain == base.repair_chain and up.production_bom == base.production_bom and up.eol == base.eol
