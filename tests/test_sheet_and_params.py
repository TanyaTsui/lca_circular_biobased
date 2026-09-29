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


# ── sheet validation ──────────────────────────────────────────────────────────────────
def test_snapshot_has_no_validation_errors(tables):
    assert [str(i) for i in validate(tables) if i.level == "error"] == []


def _broken(tables, tab, mutate):
    t = copy.deepcopy(tables)
    mutate(t[tab])
    return [str(i) for i in validate(t) if i.level == "error"]


def test_validation_catches_bad_inputs(tables):
    case_tab = next(t for t in tables if t.startswith("case_"))

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
    assert any("unknown names" in m for m in _broken(tables, "products", bad_formula))


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
    case = resolve_raw_case(ps, "raw_biopol", "x", vals)
    assert sum(b.percentage for b in case.production_bom) == pytest.approx(100)
    e = case.eol
    assert e.composted + e.recycled_open + e.recycled_closed + e.incinerated + e.landfilled == pytest.approx(100)
    b = resolve_baseline(ps, "glulam beam", vals)
    for shares in b.eol_shares.values():
        assert sum(shares.values()) == pytest.approx(100)


# ── scaled-up variant ─────────────────────────────────────────────────────────────────────
def test_scale_up_changes_only_sheet_machines(inp):
    ps = inp.params
    for cid, name in inp.raw_cases().items():
        rows = ps.rows(cid)
        scaled_steps = set(rows[(rows.stage == "production") & rows.scaled_up.notna()]["item"])
        base = resolve_raw_case(ps, cid, name, ps.typical())
        up = scale_up_case(base, ps, cid)
        for a, b in zip(base.production_chain, up.production_chain):
            if a.step_name in scaled_steps:
                assert (a.kg_machine, a.power_kW, a.rate_kg_per_hr, a.machine_lifetime_hrs) != \
                       (b.kg_machine, b.power_kW, b.rate_kg_per_hr, b.machine_lifetime_hrs)
            else:
                assert a == b
        assert up.repair_chain == base.repair_chain and up.production_bom == base.production_bom and up.eol == base.eol
