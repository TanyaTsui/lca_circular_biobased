"""Yes/no summary tables agree with a direct comparison of net impacts."""
import pandas as pd

from conftest import BACKGROUND, SNAPSHOT
from raw_lca import Background, Model, load_inputs, run_products
from raw_lca.plots import chart_categories, type_of
from raw_lca.summary import COMPARISONS, better_table

inp = load_inputs(SNAPSHOT)
ORDER = list(inp.raw_cases())


def test_yes_no_matches_direct_comparison_and_marks_missing_baselines():
    model = Model(inp, Background(BACKGROUND, "baseline"))
    results = {c: run_products(model, c) for c in ORDER}
    cats = chart_categories(inp)
    for _, other_type in COMPARISONS:
        table = better_table(inp, results, other_type, ORDER)
        assert list(table.index) == [label for _, label in cats]
        for case in ORDER:
            res = results[case]
            scaled = next(r for l, r in res.items() if type_of(inp, l) == "raw scaled up")
            other = next((r for l, r in res.items() if type_of(inp, l) == other_type), None)
            col = case.replace("raw_", "")
            for cat, label in cats:
                if other is None:
                    assert table.loc[label, col] == "n/a"
                else:
                    i = scaled.categories.index(cat)
                    assert table.loc[label, col] == ("yes" if scaled.net[i] < other.net[i] else "no")
    # the membrane has no bio-based conventional baseline
    assert (better_table(inp, results, "conventional bio-based", ORDER)["knit"] == "n/a").all()


def test_top_group_table_picks_the_largest_total_order_index():
    from raw_lca.summary import top_group_table
    cats = chart_categories(inp)
    rows = []
    for cat, _ in cats:
        rows += [dict(name="design", group="design", category=cat, ST=0.6, ST_lo=0.55, ST_hi=0.65),
                 dict(name="location", group="location", category=cat, ST=0.2, ST_lo=0.15, ST_hi=0.25)]
    df = pd.DataFrame(rows)
    df.loc[(df.category == cats[0][0]) & (df.name == "location"), ["ST", "ST_lo", "ST_hi"]] = [0.61, 0.5, 0.7]   # close call
    table = top_group_table(inp, {c: df for c in ORDER}, ORDER)
    assert (table.iloc[1:] == "design").all().all()
    assert (table.iloc[0] == "location*").all()          # larger index but overlapping intervals -> flagged
