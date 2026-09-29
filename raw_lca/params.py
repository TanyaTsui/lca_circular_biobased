"""
The parameter table: every number a partner or the LCA team enters on the sheet (tabs `case_*` and `baselines`).
One row per parameter: typical value, range (min/max), distribution, group. This one table drives the model,
the uncertainty analysis (sampling) and the sensitivity analysis (grouping).
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

GROUPS = ("design", "manufacturing", "circularity", "location")
DISTRIBUTIONS = ("fixed", "triangular", "uniform", "choice")


def pid(case, stage, item, qualifier, parameter) -> str:
    return f"{case}|{stage}|{item}|{qualifier}|{parameter}"


class ParameterSet:
    def __init__(self, df: pd.DataFrame):
        df = df.copy()
        for c in ("qualifier", "choices"):
            df[c] = df[c].fillna("").astype(str)
        df["id"] = [pid(r.case, r.stage, r.item, r.qualifier, r.parameter) for r in df.itertuples()]
        is_choice = df["distribution"] == "choice"
        df["typical_value"] = [str(t) if ch else float(t) for t, ch in zip(df["typical"], is_choice)]
        for c in ("min", "max", "scaled_up"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        if df["id"].duplicated().any():
            raise ValueError(f"duplicate parameters: {df.loc[df['id'].duplicated(), 'id'].tolist()[:5]}")
        self.df = df.reset_index(drop=True)
        self._rows: Dict[str, pd.DataFrame] = {c: g for c, g in self.df.groupby("case", sort=False)}
        self._lookup: Dict[str, dict] = {}

    @classmethod
    def from_tables(cls, tables: Dict[str, pd.DataFrame]) -> "ParameterSet":
        parts = [t for name, t in tables.items() if name.startswith("case_") or name == "baselines"]
        return cls(pd.concat(parts, ignore_index=True))

    def rows(self, case: str) -> pd.DataFrame:
        return self._rows[case]

    def lookup(self, case: str) -> dict:
        """(stage, item, qualifier, parameter) -> id for one case."""
        if case not in self._lookup:
            self._lookup[case] = {(r.stage, r.item, r.qualifier, r.parameter): r.id for r in self._rows[case].itertuples()}
        return self._lookup[case]

    def typical(self) -> dict:
        return dict(zip(self.df["id"], self.df["typical_value"]))

    def group_of(self) -> pd.Series:
        return self.df.set_index("id")["group"]

    def cases(self) -> List[str]:
        return list(self._rows)

    def sample(self, n: int, rng: np.random.Generator, location_choices: Optional[List[str]] = None,
               vary_choices: bool = False) -> pd.DataFrame:
        """n samples of every parameter (columns = ids). Numeric: triangular(min, typical, max) or uniform;
        categorical ('choice') parameters keep their typical value unless vary_choices, in which case
        they are drawn uniformly from their choices (locations: from `location_choices`)."""
        cols = {}
        for r in self.df.itertuples():
            t = r.typical_value
            if r.distribution == "choice":
                if vary_choices:
                    options = [c for c in r.choices.split(";") if c] or ((location_choices or [t]) if "location" in r.parameter else [t])
                    cols[r.id] = rng.choice(options, n)
                else:
                    cols[r.id] = np.full(n, t, dtype=object)
            elif r.distribution == "triangular" and r.min < r.max:
                cols[r.id] = rng.triangular(min(r.min, t), t, max(r.max, t), n)
            elif r.distribution == "uniform" and r.min < r.max:
                cols[r.id] = rng.uniform(r.min, r.max, n)
            else:
                cols[r.id] = np.full(n, t)
        return pd.DataFrame(cols)

    # ── quasi-random / Sobol' sampling support ──────────────────────────────────────────────
    def varying_ids(self, case: str, location_choices: Optional[List[str]] = None) -> List[str]:
        """Ids of a case's parameters that can vary: numeric with min < max, or categorical with several choices."""
        out = []
        for r in self.rows(case).itertuples():
            if r.distribution == "choice":
                opts = [c for c in r.choices.split(";") if c] or ((location_choices or []) if "location" in r.parameter else [])
                if len(set(opts)) > 1:
                    out.append(r.id)
            elif r.distribution in ("triangular", "uniform") and r.min < r.max:
                out.append(r.id)
        return out

    def from_unit(self, U: np.ndarray, ids: List[str], location_choices: Optional[List[str]] = None) -> pd.DataFrame:
        """Map U (n x len(ids), values in [0,1)) to parameter values through each parameter's distribution.
        Parameters not in `ids` stay at their typical value. Categorical parameters take a uniformly chosen option."""
        n = U.shape[0]
        by_id = self.df.set_index("id")
        cols = {i: np.full(n, t, dtype=object if isinstance(t, str) else float) for i, t in self.typical().items()}
        for j, i in enumerate(ids):
            r, u = by_id.loc[i], U[:, j]
            if r["distribution"] == "choice":
                opts = [c for c in r["choices"].split(";") if c] or list(location_choices or [])
                cols[i] = np.array(opts, dtype=object)[np.minimum((u * len(opts)).astype(int), len(opts) - 1)]
            elif r["distribution"] == "uniform":
                cols[i] = r["min"] + u * (r["max"] - r["min"])
            else:                                       # triangular, mode = typical
                a, c, b = min(r["min"], r["typical_value"]), r["typical_value"], max(r["max"], r["typical_value"])
                fc = (c - a) / (b - a)
                cols[i] = np.where(u < fc, a + np.sqrt(u * (b - a) * (c - a)), b - np.sqrt((1 - u) * (b - a) * (b - c)))
        return pd.DataFrame(cols)
