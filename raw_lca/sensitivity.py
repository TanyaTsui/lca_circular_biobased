"""
Sensitivity analysis of a RAW case's net impact to its sheet parameters, grouped into
design / manufacturing / circularity / location choices.

 - tornado: one-at-a-time swing of the output between each parameter's min and max (all others typical);
   categorical parameters are switched between their choices (combination parameters: between all combinations).
 - sobol: variance-based first-order (S1) and total-order (ST) indices (Saltelli 2010 / Jansen 1999 estimators),
   per parameter or per group, with bootstrap confidence intervals.
Background (ecoinvent) uncertainty is not part of the sensitivity analysis.
"""
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from .model import Model
from .params import combinations
from .study import run_raw_only


def sobol_from_evaluations(f_A: np.ndarray, f_B: np.ndarray, f_AB: List[np.ndarray], n_boot: int = 200,
                           seed: int = 0) -> Dict[str, np.ndarray]:
    """S1, ST and bootstrap 95 % CI of ST. f_* have shape (N, n_outputs); f_AB[k] = A with block k taken from B."""
    rng = np.random.default_rng(seed)

    def indices(idx):
        a, b = f_A[idx], f_B[idx]
        V = np.var(np.concatenate([a, b]), axis=0, ddof=1)
        V = np.where(V == 0, np.nan, V)
        s1 = np.array([np.mean(b * (ab[idx] - a), axis=0) / V for ab in f_AB])
        st = np.array([0.5 * np.mean((a - ab[idx]) ** 2, axis=0) / V for ab in f_AB])
        return s1, st

    s1, st = indices(np.arange(len(f_A)))
    boots = np.array([indices(rng.integers(0, len(f_A), len(f_A)))[1] for _ in range(n_boot)])
    return {"S1": s1, "ST": st, "ST_lo": np.nanpercentile(boots, 2.5, axis=0), "ST_hi": np.nanpercentile(boots, 97.5, axis=0)}


def sobol_function(f: Callable[[np.ndarray], np.ndarray], blocks: List[List[int]], n_dims: int, N: int, seed: int,
                   n_boot: int = 200) -> Dict[str, np.ndarray]:
    """Sobol indices of f (maps U of shape (n, n_dims) in [0,1) to (n, n_outputs)) for blocks of input columns."""
    rng = np.random.default_rng(seed)
    A, B = rng.random((N, n_dims)), rng.random((N, n_dims))
    fA, fB = f(A), f(B)
    fAB = []
    for cols in blocks:
        AB = A.copy()
        AB[:, cols] = B[:, cols]
        fAB.append(f(AB))
    return sobol_from_evaluations(fA, fB, fAB, n_boot, seed)


def _output_fn(model: Model, raw_case_id: str, ids: List[str], spec_value: Optional[float], scaled_up: bool):
    inp = model.inp

    def f(U: np.ndarray) -> np.ndarray:
        values = inp.params.from_unit(U, ids, inp.location_choices).to_dict("records")
        return np.array([run_raw_only(model, raw_case_id, spec_value, v, scaled_up).net for v in values])
    return f


def sobol(model: Model, raw_case_id: str, N: int, seed: int, by: str = "group", spec_value: Optional[float] = None,
          scaled_up: bool = False, n_boot: int = 200) -> pd.DataFrame:
    """Sobol' indices of the RAW case's net impact per category. by = 'group' (4 groups) or 'parameter'."""
    inp = model.inp
    ids = inp.params.varying_ids(raw_case_id, inp.location_choices)
    groups = inp.params.group_of()
    if by == "group":
        names = [g for g in ("design", "manufacturing", "circularity", "location") if any(groups[i] == g for i in ids)]
        blocks = [[j for j, i in enumerate(ids) if groups[i] == g] for g in names]
        group_of = dict(zip(names, names))
    else:
        names, blocks = list(ids), [[j] for j in range(len(ids))]
        group_of = {i: groups[i] for i in ids}
    res = sobol_function(_output_fn(model, raw_case_id, ids, spec_value, scaled_up), blocks, len(ids), N, seed, n_boot)
    rows = []
    for k, name in enumerate(names):
        for c, cat in enumerate(model.bg.categories):
            rows.append(dict(name=name, group=group_of[name], category=cat, S1=res["S1"][k, c], ST=res["ST"][k, c],
                             ST_lo=res["ST_lo"][k, c], ST_hi=res["ST_hi"][k, c]))
    return pd.DataFrame(rows)


def tornado(model: Model, raw_case_id: str, category: str, spec_value: Optional[float] = None,
            scaled_up: bool = False) -> pd.DataFrame:
    """Output at each parameter's min and max (others typical); categorical parameters: at each choice
    (combination parameters: at each combination)."""
    inp = model.inp
    ps = inp.params
    ci = model.bg.categories.index(category)
    base = ps.typical()
    y0 = run_raw_only(model, raw_case_id, spec_value, base, scaled_up).net[ci]
    by_id = ps.df.set_index("id")
    rows = []
    for i in ps.varying_ids(raw_case_id, inp.location_choices):
        r = by_id.loc[i]
        if r["distribution"] in ("choice", "combination"):
            opts = (combinations(r["choices"], r["min"], r["max"]) if r["distribution"] == "combination" else
                    [c for c in r["choices"].split(";") if c] or list(inp.location_choices))
            ys = [run_raw_only(model, raw_case_id, spec_value, {**base, i: o}, scaled_up).net[ci] for o in opts]
        else:
            ys = [run_raw_only(model, raw_case_id, spec_value, {**base, i: v}, scaled_up).net[ci] for v in (r["min"], r["max"])]
        rows.append(dict(id=i, group=r["group"], stage=r["stage"], item=r["item"], parameter=r["parameter"],
                         low=min(ys), high=max(ys), swing=max(ys) - min(ys), baseline=y0))
    return pd.DataFrame(rows).sort_values("swing", ascending=False).reset_index(drop=True)


GROUP_ORDER = ("design", "manufacturing", "circularity", "location")


def group_samples(model: Model, raw_case_id: str, n: int, seed: int, spec_value: Optional[float] = None,
                  scaled_up: bool = False) -> Dict[str, np.ndarray]:
    """Net impact (n draws x impact categories) of a RAW case when only the parameters of ONE group are varied by Monte
    Carlo (from their sheet distributions; locations uniformly from `location_choices`) and all others stay at their
    typical value. {group: array}."""
    inp = model.inp
    ids_all = inp.params.varying_ids(raw_case_id, inp.location_choices)
    groups = inp.params.group_of()
    rng = np.random.default_rng(seed)
    out = {}
    for g in GROUP_ORDER:
        ids = [i for i in ids_all if groups[i] == g]
        if ids:
            out[g] = _output_fn(model, raw_case_id, ids, spec_value, scaled_up)(rng.random((n, len(ids))))
    return out
