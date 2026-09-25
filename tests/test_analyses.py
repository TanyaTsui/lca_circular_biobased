"""Uncertainty and sensitivity machinery."""
import numpy as np
import pytest

from conftest import BACKGROUND, SNAPSHOT
from raw_lca import Background, Model, load_inputs, run_products
from raw_lca.sensitivity import sobol_function
from raw_lca.uncertainty import run_uncertainty


def test_sobol_matches_the_analytic_ishigami_function():
    """Ishigami: S1 = (0.314, 0.442, 0), ST = (0.558, 0.442, 0.244)"""
    def f(U):
        x = -np.pi + 2 * np.pi * U
        return (np.sin(x[:, 0]) + 7 * np.sin(x[:, 1]) ** 2 + 0.1 * x[:, 2] ** 4 * np.sin(x[:, 0]))[:, None]
    r = sobol_function(f, [[0], [1], [2]], 3, 40000, 1, n_boot=10)
    assert r["S1"].ravel() == pytest.approx([0.314, 0.442, 0.0], abs=0.03)
    assert r["ST"].ravel() == pytest.approx([0.558, 0.442, 0.244], abs=0.03)


def test_uncertainty_collapses_to_the_typical_result_without_ranges():
    inp = load_inputs(SNAPSHOT)
    df = inp.params.df
    df["min"], df["max"] = df["typical_value"].where(df["distribution"] != "choice"), df["typical_value"].where(df["distribution"] != "choice")
    model = Model(inp, Background(BACKGROUND, "baseline"))
    ua = run_uncertainty(inp, {"baseline": model}, "raw_knit", 5, 1)["baseline"]
    typical = run_products(model, "raw_knit")
    for label, r in typical.items():
        assert np.allclose(ua.net[label], r.net, rtol=1e-9)


def test_paired_draws_and_reproducibility():
    inp = load_inputs(SNAPSHOT)
    m = Model(inp, Background(BACKGROUND, "baseline"))
    a = run_uncertainty(inp, {"baseline": m}, "raw_knit", 20, 7)["baseline"]
    b = run_uncertainty(inp, {"baseline": m}, "raw_knit", 20, 7)["baseline"]
    for label in a.net:
        assert np.array_equal(a.net[label], b.net[label])
