"""
Monte Carlo uncertainty analysis: every parameter of the sheet is sampled from its distribution (typical/min/max) and,
if background samples exist, each draw also uses one Monte Carlo iteration of the background (ecoinvent) burdens.
Draws are paired across backgrounds (the same parameter draw is evaluated in every scenario).
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from .inputs import Inputs
from .model import Model
from .study import run_products


@dataclass
class UAResult:
    raw_case: str
    scenario: str
    categories: List[str]
    burdens: Dict[str, np.ndarray]      # label -> (n draws, n categories)
    benefits: Dict[str, np.ndarray]
    net: Dict[str, np.ndarray]

    def interval(self, label: str, percentiles: Tuple[float, float]) -> Tuple[np.ndarray, np.ndarray]:
        lo, hi = np.percentile(self.net[label], percentiles, axis=0)
        return lo, hi

    def median(self, label: str) -> np.ndarray:
        return np.median(self.net[label], axis=0)

    def prob_lower(self, label: str, other: str) -> np.ndarray:
        """Share of (paired) draws in which `label` has a lower net impact than `other`, per category."""
        return (self.net[label] < self.net[other]).mean(axis=0)


def run_uncertainty(inp: Inputs, models: Dict[str, Model], raw_case_id: str, n: int, seed: int) -> Dict[str, UAResult]:
    """One UAResult per scenario in `models` ({scenario id: Model})."""
    rng = np.random.default_rng(seed)
    samples = inp.params.sample(n, rng).to_dict("records")
    out = {}
    for scenario, model in models.items():
        acc: Dict[str, List] = {}
        for i, values in enumerate(samples):
            for label, r in run_products(model, raw_case_id, values=values, iteration=i).items():
                a = acc.setdefault(label, [[], [], []])
                a[0].append(r.burdens); a[1].append(r.benefits); a[2].append(r.net)
        out[scenario] = UAResult(raw_case_id, scenario, model.bg.categories,
                                 {l: np.array(v[0]) for l, v in acc.items()}, {l: np.array(v[1]) for l, v in acc.items()},
                                 {l: np.array(v[2]) for l, v in acc.items()})
    return out
