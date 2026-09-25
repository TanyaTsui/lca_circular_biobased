"""Figures. Styling (colours, bar thickness) lives here; everything that is a result-relevant choice
(which categories, which scenarios, which specs) comes from the sheet."""
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .inputs import Inputs
from .model import Result

TYPE_COLORS = {"raw": "#3B8C6E", "raw scaled up": "#3FA9F5",
               "conventional bio-based": "#E08A2E", "conventional fossil-based": "#8C8C8C"}


def type_of(inp: Inputs, label: str) -> str:
    if label in inp.raw_cases().values():
        return "raw"
    if label.endswith("scaled up"):
        return "raw scaled up"
    ct = inp.products.drop_duplicates("display_name").set_index("display_name")["case_type"]
    return ct.get(label, "conventional fossil-based")


def color_for(inp: Inputs, label: str) -> str:
    return TYPE_COLORS[type_of(inp, label)]


def chart_categories(inp: Inputs) -> List[Tuple[str, str]]:
    """[(category, label)] flagged plot_in_bar_charts on the sheet, in sheet order."""
    c = inp.categories
    c = c[c["plot_in_bar_charts"].astype(str).str.upper() == "TRUE"]
    return list(zip(c["category"], c["label"]))


def plot_today_vs_2050(inp: Inputs, title: str, res_a: Dict[str, Result], label_a: str, res_b: Dict[str, Result],
                       label_b: str, intervals: Optional[dict] = None, unit_in: float = 0.2, clip: float = 300.0):
    """Burdens (solid, right), benefits (light, left) and net impact (dot) per impact category, each category shown for
    background a then background b. 100 % = largest burden or benefit of any case in either background.
    Bars have the same thickness in every chart (unit_in inches per bar); figure height follows the number of bars.
    intervals: optional {(background label, case label): (net low, net high)} arrays over categories; the axis is clipped
    at +-clip % and whiskers that continue beyond it end in an arrowhead."""
    cats = chart_categories(inp)
    labels = list(res_a)
    n = len(labels)
    ref = next(iter(res_a.values()))
    idx = [ref.categories.index(c) for c, _ in cats]
    tab = {lab: {l: (r.burdens[idx], r.benefits[idx], r.net[idx]) for l, r in res.items()}
           for lab, res in ((label_a, res_a), (label_b, res_b))}
    scale = np.max([np.maximum(np.abs(t[0]), np.abs(t[1])) for d in tab.values() for t in d.values()], axis=0)
    scale = np.where(scale == 0, 1, scale)

    gap_within, gap_between = 0.5, 1.5
    starts, y0 = [], 0.0
    for _ in cats:
        a = y0; b = a + n + gap_within
        starts.append((a, b)); y0 = b + n + gap_between
    ymin, ymax = -gap_between / 2, y0 - gap_between / 2

    w, left, right, top, bottom = 9.5, 2.1, 0.3, 0.75, 1.5
    axes_h = (ymax - ymin) * unit_in
    H = axes_h + top + bottom
    fig = plt.figure(figsize=(w, H))
    ax = fig.add_axes([left / w, bottom / H, (w - left - right) / w, axes_h / H])
    yticks, ylabels = [], []
    ends = [0.0, 100.0]
    for ci, ((cat, clabel), (ya, yb)) in enumerate(zip(cats, starts)):
        if ci % 2 == 0:
            ax.axhspan(ya - gap_between / 2, yb + n + gap_between / 2, color="#F5F5F5", zorder=0, linewidth=0)
        for y_start, lab in ((ya, label_a), (yb, label_b)):
            for i, l in enumerate(labels):
                bur, ben, net = (v[ci] / scale[ci] * 100 for v in tab[lab][l])
                yi = y_start + i + 0.5
                c = color_for(inp, l)
                ax.barh(yi, bur, height=0.9, color=c, zorder=2)
                ax.barh(yi, ben, height=0.9, color=c, alpha=0.4, zorder=2)
                ends += [bur, ben, net]
                if intervals and (lab, l) in intervals:
                    lo, hi = (v[idx[ci]] / scale[ci] * 100 for v in intervals[(lab, l)])
                    ends += [lo, hi]
                    ax.plot([max(lo, -clip), min(hi, clip)], [yi, yi], color="black", linewidth=1.0, zorder=3)
                    if hi > clip:
                        ax.plot(clip, yi, marker=">", color="black", markersize=4, zorder=3)
                    if lo < -clip:
                        ax.plot(-clip, yi, marker="<", color="black", markersize=4, zorder=3)
                ax.scatter(net, yi, s=22, color="black", edgecolor="white", linewidth=0.7, zorder=4)
            yticks.append(y_start + n / 2)
            ylabels.append(f"{clabel}\n{lab}")
    ax.axvline(0, color="black", linewidth=0.8, zorder=3)
    ax.set_axisbelow(True); ax.grid(axis="x", color="#E3E3E3", linewidth=0.8)
    ax.set_ylim(ymax, ymin)
    ax.set_xlim(max(min(ends), -clip) - 5, min(max(ends), clip) + 5)
    ax.set_yticks(yticks); ax.set_yticklabels(ylabels, fontsize=8); ax.tick_params(axis="y", length=0)
    ax.set_xlabel("% of largest burden or benefit in category (both backgrounds)")
    fig.suptitle(title, fontsize=11, y=1 - 0.24 / H)
    handles = [Patch(color=color_for(inp, l), label=l) for l in labels]
    handles += [Patch(color="#777777", alpha=0.4, label="benefits (lighter, left)"),
                Line2D([0], [0], marker="o", color="none", markerfacecolor="black", markeredgecolor="white",
                       markersize=7, label="net impact" + (" (line: uncertainty interval, arrowhead: continues beyond the axis)" if intervals else ""))]
    fig.legend(handles=handles, frameon=False, loc="lower center", ncol=2, fontsize=8)
    return fig


def plot_sweep(inp: Inputs, spec_label: str, spec_unit: str, xs: np.ndarray, series: Dict[str, List[float]],
               spec_value: float, title: str):
    fig, ax = plt.subplots(figsize=(7, 4))
    for label, ys in series.items():
        ax.plot(xs, ys, marker="o", color=color_for(inp, label), label=label)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.axvline(spec_value, color="grey", linestyle=":")
    ax.set_xlabel(f"{spec_label} ({spec_unit})"); ax.set_ylabel("net kg CO2-eq")
    ax.set_title(title, fontsize=10); ax.legend(frameon=False)
    fig.tight_layout()
    return fig


GROUP_COLORS = {"design": "#4C78A8", "manufacturing": "#F58518", "circularity": "#54A24B", "location": "#B279A2"}


def plot_group_sensitivity(inp: Inputs, title: str, by_scenario: Dict[str, pd.DataFrame]):
    """Total-order Sobol' index of each parameter group per charted impact category; one panel per background."""
    cats = chart_categories(inp)
    groups = [g for g in GROUP_COLORS if any(g in df["name"].values for df in by_scenario.values())]
    fig, axes = plt.subplots(1, len(by_scenario), figsize=(5.6 * len(by_scenario), 0.55 * len(cats) + 1.6),
                             sharey=True, squeeze=False)
    h = 0.8 / len(groups)
    for ax, (scn, df) in zip(axes[0], by_scenario.items()):
        for gi, g in enumerate(groups):
            sub = df[df["name"] == g].set_index("category")
            for ci, (cat, _) in enumerate(cats):
                if cat not in sub.index:
                    continue
                y = ci + (gi - (len(groups) - 1) / 2) * h
                v = sub.loc[cat]
                ax.barh(y, v["ST"], height=h * 0.95, color=GROUP_COLORS[g], label=g if ci == 0 else None)
                ax.plot([v["ST_lo"], v["ST_hi"]], [y, y], color="black", linewidth=0.8)
        ax.set_yticks(range(len(cats))); ax.set_yticklabels([l for _, l in cats])
        ax.set_ylim(len(cats) - 0.5, -0.5)
        ax.set_xlim(0, max(1.05, float(df["ST_hi"].max()) + 0.05)); ax.set_xlabel("total-order Sobol' index"); ax.set_title(scn, fontsize=10)
        ax.set_axisbelow(True); ax.grid(axis="x", color="#E3E3E3")
    fig.suptitle(title, fontsize=11)
    fig.legend(handles=[Patch(color=GROUP_COLORS[g], label=g) for g in groups], frameon=False, fontsize=8,
               loc="lower center", ncol=len(groups))
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return fig


def plot_parameter_sensitivity(title: str, df: pd.DataFrame, category: str, top: int = 12):
    """Most influential single parameters (total-order Sobol' index) for one category."""
    d = df[df["category"] == category].sort_values("ST", ascending=False).head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.35 * len(d) + 1.4))
    ax.barh(range(len(d)), d["ST"], color=[GROUP_COLORS[g] for g in d["group"]])
    ax.errorbar(d["ST"], range(len(d)), xerr=[d["ST"] - d["ST_lo"], d["ST_hi"] - d["ST"]], fmt="none", ecolor="black", lw=0.8)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels([n.split("|")[2] + " - " + n.split("|")[4] + (f" ({n.split('|')[1]})" if n.split("|")[1] in ("repair",) else "")
                        for n in d["name"]], fontsize=8)
    ax.set_xlabel("total-order Sobol' index"); ax.set_title(f"{title}\n{category}", fontsize=10)
    ax.legend(handles=[Patch(color=c, label=g) for g, c in GROUP_COLORS.items()], frameon=False, fontsize=8, loc="lower right")
    ax.set_axisbelow(True); ax.grid(axis="x", color="#E3E3E3")
    fig.tight_layout()
    return fig


def plot_tornado(title: str, df: pd.DataFrame, category_unit: str, top: int = 12):
    """One-at-a-time swings between each parameter's min and max."""
    d = df.head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.35 * len(d) + 1.4))
    for y, r in enumerate(d.itertuples()):
        ax.barh(y, r.high - r.low, left=r.low, color=GROUP_COLORS[r.group], height=0.7)
    ax.axvline(d["baseline"].iloc[0], color="black", linewidth=0.8)
    ax.set_yticks(range(len(d))); ax.set_yticklabels([f"{r.item} - {r.parameter}" for r in d.itertuples()], fontsize=8)
    ax.set_xlabel(category_unit); ax.set_title(title, fontsize=10)
    ax.legend(handles=[Patch(color=c, label=g) for g, c in GROUP_COLORS.items()], frameon=False, fontsize=8, loc="lower right")
    ax.set_axisbelow(True); ax.grid(axis="x", color="#E3E3E3")
    fig.tight_layout()
    return fig


YESNO_STYLE = {"yes": ("#CFEBD8", "#12703A"), "no": ("#F6CFCF", "#A61C1C"), "n/a": ("#E6E6E6", "#777777")}


def plot_yes_no_tables(tables: Dict[Tuple[str, str], pd.DataFrame], row_titles: List[str], col_titles: List[str],
                       title: str = ""):
    """Grid of yes/no tables: one row of tables per comparison (row_titles), one column per background (col_titles).
    tables[(row title, column title)] = DataFrame of 'yes' / 'no' / 'n/a' (rows: impact categories, columns: cases)."""
    first = next(iter(tables.values()))
    n_rows, n_cols = first.shape
    cell_w, cell_h = 0.75, 0.32
    label_w = 2.1
    fig_w = len(col_titles) * (label_w + n_cols * cell_w) + 0.6
    fig_h = len(row_titles) * (n_rows * cell_h + 1.15) + 0.6
    fig, axes = plt.subplots(len(row_titles), len(col_titles), figsize=(fig_w, fig_h), squeeze=False)
    for ri, rt in enumerate(row_titles):
        for ci, ct in enumerate(col_titles):
            ax, df = axes[ri][ci], tables[(rt, ct)]
            ax.set_xlim(-label_w / cell_w, n_cols); ax.set_ylim(n_rows, -1.1)
            ax.axis("off")
            ax.set_title(f"{rt}  -  {ct}", fontsize=10, loc="left", fontweight="bold", pad=4)
            for j, col in enumerate(df.columns):
                ax.text(j + 0.5, -0.55, col, ha="center", va="center", fontsize=9, fontweight="bold")
            for i, (cat, row) in enumerate(df.iterrows()):
                ax.text(-0.1, i + 0.5, cat, ha="right", va="center", fontsize=8.5)
                for j, v in enumerate(row):
                    fill, ink = YESNO_STYLE[v]
                    ax.add_patch(plt.Rectangle((j + 0.03, i + 0.03), 0.94, 0.94, facecolor=fill, edgecolor="white"))
                    ax.text(j + 0.5, i + 0.5, v, ha="center", va="center", fontsize=9, color=ink, fontweight="bold")
    if title:
        fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97 if title else 1))
    return fig


def plot_top_group_tables(tables: Dict[str, pd.DataFrame], title: str = ""):
    """Tables of the most important parameter group per impact category (rows) and RAW case (columns), one per
    background, cells coloured by group (same colours as the sensitivity charts)."""
    first = next(iter(tables.values()))
    n_rows, n_cols = first.shape
    cell_w, cell_h, label_w = 1.25, 0.32, 2.1
    fig, axes = plt.subplots(1, len(tables), figsize=(len(tables) * (label_w + n_cols * cell_w) + 0.6, n_rows * cell_h + 1.3),
                             squeeze=False)
    for ax, (lab, df) in zip(axes[0], tables.items()):
        ax.set_xlim(-label_w / cell_w, n_cols); ax.set_ylim(n_rows, -1.1); ax.axis("off")
        ax.set_title(lab, fontsize=10, loc="left", fontweight="bold", pad=4)
        for j, col in enumerate(df.columns):
            ax.text(j + 0.5, -0.55, col, ha="center", va="center", fontsize=9, fontweight="bold")
        for i, (cat, row) in enumerate(df.iterrows()):
            ax.text(-0.05, i + 0.5, cat, ha="right", va="center", fontsize=8.5)
            for j, v in enumerate(row):
                g = str(v).rstrip("*")
                color = GROUP_COLORS.get(g, "#AAAAAA")
                ax.add_patch(plt.Rectangle((j + 0.03, i + 0.03), 0.94, 0.94, facecolor=color, alpha=0.85, edgecolor="white"))
                ax.text(j + 0.5, i + 0.5, v, ha="center", va="center", fontsize=8.5, color="white", fontweight="bold")
    fig.text(0.01, 0.01, "* close call: the 95 % interval of the top group overlaps that of the runner-up", fontsize=7.5, color="#555")
    if title:
        fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95 if title else 1))
    return fig


def plot_group_boxplots(inp: Inputs, title: str, samples: Dict[str, np.ndarray], typical: np.ndarray, whis,
                        category_names: List[str], units: Dict[str, str], unit_in: float = 0.24):
    """One chart for one background: for each charted impact category four horizontal box plots, one per parameter group.
    In a box plot only the parameters of that group are varied by Monte Carlo (all others at typical values). Box: 25-75 %,
    whiskers: `whis` percentiles, line: median; the dotted line marks the net impact at typical values.
    Axis: % of the largest net impact of the category in this chart (100 % = the largest absolute value among the whisker ends
    and the typical-value result, over the four groups; the absolute value is given next to the category name).
    Negative values are net benefits. All boxes have the same thickness (unit_in inches per box)."""
    cats = chart_categories(inp)
    groups = [g for g in GROUP_COLORS if g in samples]
    n = len(groups)
    gap = 1.0
    ymax = len(cats) * (n + gap) - gap
    w, left, right, top, bottom = 9.0, 2.6, 0.3, 0.8, 1.3
    axes_h = (ymax + gap) * unit_in
    H = axes_h + top + bottom
    fig = plt.figure(figsize=(w, H))
    ax = fig.add_axes([left / w, bottom / H, (w - left - right) / w, axes_h / H])
    yticks, ylabels = [], []
    for ci, (cat, clabel) in enumerate(cats):
        k = category_names.index(cat)
        y0 = ci * (n + gap)
        scale = max([abs(np.percentile(samples[g][:, k], q)) for g in groups for q in whis] + [abs(typical[k])]) or 1.0
        if ci % 2 == 0:
            ax.axhspan(y0 - gap / 2, y0 + n - 1 + gap / 2 + 0.0, color="#F5F5F5", zorder=0, linewidth=0)
        bp = ax.boxplot([samples[g][:, k] / scale * 100 for g in groups], vert=False, whis=whis, showfliers=False,
                        patch_artist=True, widths=0.78, positions=[y0 + j for j in range(n)])
        for patch, g in zip(bp["boxes"], groups):
            patch.set(facecolor=GROUP_COLORS[g], edgecolor="#333333", linewidth=0.8, zorder=2)
        for med in bp["medians"]:
            med.set(color="black", linewidth=1.3, zorder=3)
        for wk in bp["whiskers"] + bp["caps"]:
            wk.set(color="#333333", linewidth=0.8, zorder=2)
        ax.plot([typical[k] / scale * 100] * 2, [y0 - 0.5, y0 + n - 0.5], color="black", linestyle=":", linewidth=1, zorder=4)
        yticks.append(y0 + (n - 1) / 2)
        ylabels.append(f"{clabel}\n100 % = {scale:.3g}\n{units.get(cat, '')}")
    ax.set_ylim(ymax + gap / 2, -gap / 2 - 0.1)
    ax.set_yticks(yticks); ax.set_yticklabels(ylabels, fontsize=8); ax.tick_params(axis="y", length=0)
    ax.axvline(0, color="black", linewidth=0.8, zorder=1)
    ax.set_axisbelow(True); ax.grid(axis="x", color="#E3E3E3", linewidth=0.8)
    ax.set_xlabel("% of the largest net impact of the category in this chart", fontsize=9)
    fig.suptitle(title, fontsize=11, y=1 - 0.2 / H)
    fig.legend(handles=[Patch(facecolor=GROUP_COLORS[g], edgecolor="#333333", label=g) for g in groups]
               + [Line2D([0], [0], color="black", linestyle=":", label="net impact at typical values")],
               frameon=False, loc="lower center", ncol=len(groups) + 1, fontsize=8)
    return fig
