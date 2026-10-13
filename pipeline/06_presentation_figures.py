"""Slide-format (16:9) figures for presentations, from the newest sheet snapshot at typical values.

    python pipeline/06_presentation_figures.py

Writes to results/figures/presentation/:
  gwp_all_cases_today      climate change of every RAW case vs. its baselines, today's background
  timber_three_categories  reclaimed timber beam: climate change, land use, mineral resources, today's background
  yes_no_questions         is the scaled-up case better? three comparisons (columns) x today / 2050 (rows)
  sensitivity_top_group    most influential parameter group (Sobol', RAW prototypes), today and 2050
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from raw_lca import Background, Model, load_inputs, run_products, spec_variable
from raw_lca.paths import BACKGROUND, RESULTS, newest_snapshot
from raw_lca.plots import GROUP_COLORS, TYPE_COLORS, YESNO_STYLE, type_of
from raw_lca.sensitivity import sobol
from raw_lca.summary import COMPARISONS, better_table, top_group_table

OUT = RESULTS / "figures" / "presentation"
SLIDE = (13.33, 6.2)                 # 16:9 slide width, leaves room for a slide title
CASE_ORDER = ["raw_biopol", "raw_timber", "raw_cfw", "raw_knit"]
NO_BIOBASED = {"raw_cfw", "raw_knit"}     # no meaningful conventional bio-based baseline (yet)
TYPE_ORDER = ["raw", "raw scaled up", "conventional bio-based", "conventional fossil-based"]
TYPE_SHORT = {"raw": "Prototype", "raw scaled up": "Scaled up",
              "conventional bio-based": "Bio-based baseline", "conventional fossil-based": "Fossil-based baseline"}
TYPE_TICK = {"raw": "Proto-\ntype", "raw scaled up": "Scaled\nup",
             "conventional bio-based": "Bio-\nbased", "conventional fossil-based": "Fossil-\nbased"}
CASE_TITLES = {"raw_biopol": "3D-printed\nbiopolymer wall", "raw_knit": "Knitted\nhemp membrane",
               "raw_timber": "Reclaimed\ntimber beam", "raw_cfw": "Coreless\nfilament-wound beam"}
CATEGORY_TITLES = {"climate change": ("Climate change", "kg CO$_2$-eq"),
                   "land use": ("Land use", "soil quality index (dimensionless)"),
                   "material resources: metals/minerals": ("Mineral resource use", "kg Sb-eq")}

plt.rcParams.update({"font.size": 12, "axes.spines.top": False, "axes.spines.right": False,
                     "font.family": "sans-serif"})


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=300); fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)


def ordered(res, case_id):
    """[(type, label, Result)] in TYPE_ORDER; drops the bio-based baseline of the cases without a meaningful one."""
    by_type = {type_of(inp, l): (l, r) for l, r in res.items()}
    return [(t, *by_type[t]) for t in TYPE_ORDER
            if t in by_type and not (t == "conventional bio-based" and case_id in NO_BIOBASED)]


def fmt(v):
    a = abs(v)
    if a >= 100:
        return f"{v:,.0f}"
    if a >= 0.01 or a == 0:
        return f"{v:.3g}"
    return f"{v:.2e}".replace("e-0", "e-")


def bar_panel(ax, rows, cat, title, unit):
    """Burdens (solid, up), benefits (light, down), net impact (dot + value) for one impact category."""
    for x, (t, label, r) in enumerate(rows):
        i = r.categories.index(cat)
        c = TYPE_COLORS[t]
        ax.bar(x, r.burdens[i], width=0.7, color=c, zorder=2)
        ax.bar(x, r.benefits[i], width=0.7, color=c, alpha=0.4, zorder=2)
        ax.scatter(x, r.net[i], s=45, color="black", edgecolor="white", linewidth=0.9, zorder=4)
        top = max(r.burdens[i], 0)
        ax.annotate(fmt(r.net[i]), (x, top), xytext=(0, 4), textcoords="offset points",
                    ha="center", va="bottom", fontsize=10.5, color="#222222")
    ax.axhline(0, color="black", linewidth=0.8, zorder=3)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([TYPE_TICK[t] for t, _, _ in rows], fontsize=10.5)
    ax.ticklabel_format(axis="y", style="sci", scilimits=(-2, 5), useMathText=True)
    ax.tick_params(axis="x", length=0)
    ax.set_axisbelow(True); ax.grid(axis="y", color="#E3E3E3", linewidth=0.8)
    lo, hi = ax.get_ylim(); ax.set_ylim(lo, hi + (hi - lo) * 0.08)      # room for the value labels
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.set_ylabel(unit, fontsize=11)


def legend(fig, types):
    handles = [Patch(color=TYPE_COLORS[t], label=TYPE_SHORT[t]) for t in types]
    handles += [Patch(color="#777777", alpha=0.4, label="benefits (below zero)"),
                Line2D([0], [0], marker="o", color="none", markerfacecolor="black", markeredgecolor="white",
                       markersize=8, label="net impact (value shown)")]
    fig.legend(handles=handles, frameon=False, loc="lower center", ncol=len(handles), fontsize=11)


def fu_text(case_id):
    row = inp.products[inp.products.case_name == case_id].iloc[0]
    return (f"{row.spec_label} {inp.specs[spec_variable(inp, case_id)]:g} {row.spec_unit.replace('m2', 'm²')}, "
            f"{inp.reference_service_life_for(case_id):g} yr")


def baseline_names(rows):
    return "; ".join(f"{TYPE_SHORT[t].split()[0].lower()}: {label}" for t, label, _ in rows if t.startswith("conv"))


# --- inputs -------------------------------------------------------------------------------------------------
inp = load_inputs(newest_snapshot())
scn = inp.scenarios[inp.scenarios["in_results"].astype(str).str.upper() == "TRUE"]
(id_a, label_a), (id_b, label_b) = list(zip(scn["scenario_id"], scn["label"]))[:2]
models = {id_a: Model(inp, Background(BACKGROUND, id_a)), id_b: Model(inp, Background(BACKGROUND, id_b))}
res = {sid: {c: run_products(models[sid], c) for c in CASE_ORDER} for sid in (id_a, id_b)}

# --- 1. climate change, all cases, today ----------------------------------------------------------------------
fig, axes = plt.subplots(1, len(CASE_ORDER), figsize=SLIDE)
for ax, case_id in zip(axes, CASE_ORDER):
    rows = ordered(res[id_a][case_id], case_id)
    bar_panel(ax, rows, "climate change", CASE_TITLES[case_id], "kg CO$_2$-eq" if ax is axes[0] else "")
    ax.text(0.5, 1.0, fu_text(case_id), transform=ax.transAxes, ha="center", va="bottom", fontsize=9.5, color="#555555")
    ax.set_title(CASE_TITLES[case_id], fontsize=13, fontweight="bold", pad=24)
fig.suptitle(f"Climate change per functional unit ({label_a}'s background)", fontsize=15, x=0.01, ha="left")
legend(fig, TYPE_ORDER)
fig.tight_layout(rect=(0, 0.07, 1, 0.97))
save(fig, "gwp_all_cases_today")

# --- 2. timber, three categories, today -----------------------------------------------------------------------
rows = ordered(res[id_a]["raw_timber"], "raw_timber")
fig, axes = plt.subplots(1, len(CATEGORY_TITLES), figsize=SLIDE)
for ax, (cat, (title, unit)) in zip(axes, CATEGORY_TITLES.items()):
    bar_panel(ax, rows, cat, title, unit)
fig.suptitle(f"Reclaimed timber beam ({fu_text('raw_timber')}), {label_a}'s background",
             fontsize=15, x=0.01, ha="left")
fig.text(0.01, 0.075, "Baselines: " + baseline_names(rows), fontsize=10, color="#555555")
legend(fig, [t for t, _, _ in rows])
fig.tight_layout(rect=(0, 0.1, 1, 0.97))
save(fig, "timber_three_categories")

# --- 3. yes/no tables: comparisons (columns) x backgrounds (rows) ----------------------------------------------
QUESTIONS = {"raw": "Is the scaled-up version better\nthan the prototype?",
             "conventional bio-based": "Is the scaled-up version better\nthan the conventional\nbio-based product?",
             "conventional fossil-based": "Is the scaled-up version better\nthan the conventional\nfossil-based product?"}
ROW_TITLES = {label_a: "Today", label_b: label_b}
tables = {}
for _, other_type in COMPARISONS:
    for sid, lab in ((id_a, label_a), (id_b, label_b)):
        t = better_table(inp, res[sid], other_type, CASE_ORDER)
        if other_type == "conventional bio-based":
            for c in NO_BIOBASED:
                t[c.replace("raw_", "")] = "n/a"
        tables[(other_type, lab)] = t

first = next(iter(tables.values()))
n_rows, n_cols = first.shape
label_ws = [2.6, 0.15, 0.15]                       # category names only on the first column
fig, axes = plt.subplots(2, 3, figsize=(13.33, 7.0), gridspec_kw={"width_ratios": [w + n_cols for w in label_ws]})
for ri, lab in enumerate((label_a, label_b)):
    for ci, (_, other_type) in enumerate(COMPARISONS):
        ax, df = axes[ri][ci], tables[(other_type, lab)]
        label_w = label_ws[ci]
        ax.set_xlim(-label_w, n_cols); ax.set_ylim(n_rows, -0.9); ax.axis("off")
        if ri == 0:
            ax.set_title(QUESTIONS[other_type], fontsize=12.5, fontweight="bold", pad=8, va="bottom")
        for j, col in enumerate(df.columns):
            ax.text(j + 0.5, -0.45, col, ha="center", va="center", fontsize=10.5, fontweight="bold")
        for i, (cat, row) in enumerate(df.iterrows()):
            if ci == 0:
                ax.text(-0.1, i + 0.5, cat, ha="right", va="center", fontsize=10)
            for j, v in enumerate(row):
                fill, ink = YESNO_STYLE[v]
                ax.add_patch(plt.Rectangle((j + 0.04, i + 0.04), 0.92, 0.92, facecolor=fill, edgecolor="white"))
                ax.text(j + 0.5, i + 0.5, v, ha="center", va="center", fontsize=10.5, color=ink, fontweight="bold")
    fig.text(0.008, 0.73 - ri * 0.45, ROW_TITLES[lab], rotation=90, ha="left", va="center", fontsize=14, fontweight="bold")
fig.text(0.5, 0.005, "yes = lower net impact (typical values). "
         "biopol: 3D-printed wall, knit: knitted membrane, timber: reclaimed timber beam, cfw: filament-wound beam. "
         "n/a: no meaningful bio-based baseline.", ha="center", fontsize=9, color="#555555")
fig.tight_layout(rect=(0.025, 0.03, 1, 1), h_pad=1.5, w_pad=0.5)
save(fig, "yes_no_questions")

# --- 4. sensitivity: most influential parameter group, alone and with interactions, today and 2050 --------------
N, seed = int(inp.setup["sobol_base_samples"]), int(inp.setup["mc_seed"])
GROUP_NOTES = {"design": "what the product is made of", "manufacturing": "machines, loading, yield",
               "circularity": "lifetime, repair, end of life", "location": "which country's electricity"}
INDICES = {"S1": ("On its own", "first-order Sobol' index: the group's effect alone, without interactions"),
           "ST": ("Including interactions", "total-order Sobol' index: the group's effect alone plus its interactions with other groups")}
sob = {lab: {c: sobol(models[sid], c, N, seed, by="group") for c in CASE_ORDER} for sid, lab in ((id_a, label_a), (id_b, label_b))}
tops = {(idx, lab): top_group_table(inp, sob[lab], CASE_ORDER, index=idx) for idx in INDICES for lab in (label_a, label_b)}
n_rows, n_cols = tops[("ST", label_a)].shape
# one canvas in table units (cell = 1 x 1, y downwards): category labels, today's table, gap, 2050's table
label_w, gap, head = 3.5, 0.5, 3.3                   # head: section heading, note, background, case names
x0 = {label_a: label_w, label_b: label_w + n_cols + gap}
sec_h = head + n_rows + 0.9
fig = plt.figure(figsize=(13.33, 7.3))
ax = fig.add_axes([0.01, 0.075, 0.98, 0.8])
ax.set_xlim(0, label_w + 2 * n_cols + gap); ax.set_ylim(2 * sec_h - 0.9, 0); ax.axis("off")
for si, (idx, (heading, note)) in enumerate(INDICES.items()):
    y0 = si * sec_h
    ax.text(0, y0, heading, ha="left", va="top", fontsize=13.5, fontweight="bold")
    ax.text(0, y0 + 0.95, note, ha="left", va="top", fontsize=10, color="#555555")
    for lab in (label_a, label_b):
        df = tops[(idx, lab)]
        ax.text(x0[lab] + n_cols / 2, y0 + 2.15, ROW_TITLES[lab], ha="center", va="center", fontsize=12, fontweight="bold",
                color="#333333")
        for j, col in enumerate(df.columns):
            ax.text(x0[lab] + j + 0.5, y0 + 2.9, col, ha="center", va="center", fontsize=10.5, fontweight="bold")
        for i, (cat, row) in enumerate(df.iterrows()):
            y = y0 + head + i
            if lab == label_a:
                ax.text(label_w - 0.1, y + 0.5, cat, ha="right", va="center", fontsize=10)
            for j, v in enumerate(row):
                g = str(v).rstrip("*")
                ax.add_patch(plt.Rectangle((x0[lab] + j + 0.03, y + 0.05), 0.94, 0.9, facecolor=GROUP_COLORS.get(g, "#AAAAAA"),
                                           alpha=0.9, edgecolor="white"))
                ax.text(x0[lab] + j + 0.5, y + 0.5, v, ha="center", va="center", fontsize=10 if len(v) < 12 else 8.3,
                        color="white", fontweight="bold")
fig.text(0.01, 0.975, "What makes the biggest difference in the LCA results?", fontsize=15, va="top")
fig.text(0.01, 0.93, "Parameter group with the largest influence on each RAW prototype's net impact", fontsize=10.5,
         color="#555555", va="top")
fig.legend(handles=[Patch(color=GROUP_COLORS[g], alpha=0.9, label=f"{g}: {n}") for g, n in GROUP_NOTES.items()],
           frameon=False, loc="lower center", ncol=4, fontsize=10, bbox_to_anchor=(0.5, 0.025))
fig.text(0.5, 0.008, "* close call: the 95 % interval of the top group overlaps that of the runner-up",
         ha="center", fontsize=9, color="#555555")
save(fig, "sensitivity_top_group")
print("written to", OUT)
