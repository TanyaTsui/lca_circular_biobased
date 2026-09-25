"""Yes/no summary tables: is the scaled-up RAW case better (lower net impact) than another case, per impact category?"""
from typing import Dict, List, Tuple

import pandas as pd

from .inputs import Inputs
from .model import Result
from .plots import chart_categories, type_of

# (title, type of the case the scaled-up RAW case is compared with)
COMPARISONS: List[Tuple[str, str]] = [
    ("scaled up vs. prototype", "raw"),
    ("scaled up vs. conventional bio-based", "conventional bio-based"),
    ("scaled up vs. conventional fossil-based", "conventional fossil-based"),
]


def better_table(inp: Inputs, results: Dict[str, Dict[str, Result]], other_type: str, case_order: List[str]) -> pd.DataFrame:
    """Rows: charted impact categories; columns: RAW cases (`case_order`). Cell 'yes' if the scaled-up variant has a lower
    net impact than the case of type `other_type` (raw prototype, or the baseline of that type), 'no' if not, 'n/a' if the
    RAW case has no such comparison case. `results`: {raw case id: {label: Result}} for one background."""
    cats = chart_categories(inp)
    table = pd.DataFrame(index=[label for _, label in cats], columns=[c.replace("raw_", "") for c in case_order], dtype=object)
    for case_id in case_order:
        res = results[case_id]
        scaled = next((r for l, r in res.items() if type_of(inp, l) == "raw scaled up"), None)
        other = next((r for l, r in res.items() if type_of(inp, l) == other_type), None)
        col = case_id.replace("raw_", "")
        for cat, label in cats:
            if scaled is None or other is None:
                table.loc[label, col] = "n/a"
                continue
            i = scaled.categories.index(cat)
            table.loc[label, col] = "yes" if scaled.net[i] < other.net[i] else "no"
    return table


def top_group_table(inp: Inputs, group_sobol: Dict[str, pd.DataFrame], case_order: List[str]) -> pd.DataFrame:
    """Most important parameter group per impact category and RAW case: the group with the largest total-order Sobol'
    index. A trailing * marks a close call (the 95 % interval of the top group overlaps that of the runner-up).
    group_sobol: {raw case id: output of raw_lca.sensitivity.sobol(..., by='group')} for one background."""
    cats = chart_categories(inp)
    table = pd.DataFrame(index=[label for _, label in cats], columns=[c.replace("raw_", "") for c in case_order], dtype=object)
    for case_id in case_order:
        df = group_sobol[case_id]
        for cat, label in cats:
            sub = df[df["category"] == cat].dropna(subset=["ST"]).sort_values("ST", ascending=False)
            col = case_id.replace("raw_", "")
            if sub.empty:
                table.loc[label, col] = "n/a"
                continue
            top = sub.iloc[0]
            close = len(sub) > 1 and top["ST_lo"] <= sub.iloc[1]["ST_hi"]
            table.loc[label, col] = top["name"] + ("*" if close else "")
    return table
