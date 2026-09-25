"""
Background data: unit burdens per material/process and impact category for one scenario, produced by
pipeline/02_background_lci.ipynb (Brightway + ecoinvent + premise) and committed in data/background/.
Optionally also Monte Carlo samples of those burdens (ecoinvent uncertainty).
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

Key = Tuple[str, str, str]      # (activity name, location, material source) - "" when not applicable


class Background:
    def __init__(self, data_dir, scenario: str):
        d = Path(data_dir)
        df = pd.read_csv(d / "unit_burdens.csv")
        df = df[df["scenario"] == scenario]
        if df.empty:
            raise ValueError(f"scenario '{scenario}' not in {d / 'unit_burdens.csv'}")
        self.scenario = scenario
        self.categories: List[str] = list(dict.fromkeys(df["impact_category"]))
        self.units: Dict[str, str] = df.drop_duplicates("impact_category").set_index("impact_category")["impact_category_unit"].to_dict()
        df = df.assign(location=df["location"].fillna(""), material_source=df["material_source"].fillna(""))
        wide = df.pivot_table(index=["material_name", "location", "material_source"], columns="impact_category",
                              values="score", aggfunc="first").reindex(columns=self.categories)
        self._mean: Dict[Key, np.ndarray] = {k: v.to_numpy(float) for k, v in wide.iterrows()}
        self._by_name: Dict[str, List[Key]] = {}
        for k in self._mean:
            self._by_name.setdefault(k[0], []).append(k)
        self._cache: Dict[tuple, Key] = {}
        self.gwp_index = self.categories.index("climate change")
        self.materials = pd.read_csv(d / "materials_carbon.csv").set_index("material_name")
        self.samples: Optional[Dict[Key, np.ndarray]] = None
        s = d / f"unit_burden_samples_{scenario}.npz"
        if s.exists():
            z = np.load(s, allow_pickle=True)
            order = [list(z["__categories__"]).index(c) for c in self.categories]     # match the category order of the mean
            self.samples = {tuple(k.split("|")): z[k][:, order] for k in z.files if k != "__categories__"}

    @property
    def n_samples(self) -> int:
        return 0 if self.samples is None else next(iter(self.samples.values())).shape[0]

    def _key(self, name: str, location: Optional[str], source: Optional[str]) -> Key:
        ck = (name, location, source)
        if ck not in self._cache:
            cands = [k for k in self._by_name.get(name, []) if (location is None or k[1] == location)
                     and (source is None or k[2] == source)]
            if not cands:
                raise ValueError(f"No burden data for '{name}'" + (f" in {location}" if location else "")
                                 + (f" as {source}" if source else "") + f" (scenario '{self.scenario}')")
            if len(cands) > 1:
                raise ValueError(f"'{name}' is ambiguous ({len(cands)} rows) - give a location or source")
            self._cache[ck] = cands[0]
        return self._cache[ck]

    def get(self, name: str, location: Optional[str] = None, source: Optional[str] = None,
            iteration: Optional[int] = None) -> np.ndarray:
        """Burden of one unit of `name` in all impact categories (mean, or Monte Carlo iteration `iteration`)."""
        key = self._key(name, location, source)
        if iteration is not None and self.samples is not None and key in self.samples:
            return self.samples[key][iteration % self.samples[key].shape[0]]
        return self._mean[key]

    def carbon(self, material: str) -> Tuple[float, float]:
        """(carbon content kgC per kg wet material, rotation period yr)."""
        if material not in self.materials.index:
            raise ValueError(f"No carbon data for '{material}' in materials_carbon.csv")
        r = self.materials.loc[material]
        return float(r["carbon_content_kgC_per_kgWet"]), float(r["rotation_period_yr"]) if pd.notna(r["rotation_period_yr"]) else 0.0
