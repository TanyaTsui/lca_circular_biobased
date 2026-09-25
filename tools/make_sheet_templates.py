"""
One-off migration: generate the tabs of the redesigned Google Sheet as import-ready CSV files.

Values are taken from what the repo currently holds (raw_* tabs, product_LCIs formulas, baseline EoL
assumptions, constants that used to live in code). Everything the LCA team had to guess is marked
status = "placeholder" so it is visible on the sheet. Run from the repo root:
    python tools/make_sheet_templates.py
Output: data/sheet_templates/<tab>.csv  (import each as a tab; see data/sheet_templates/README.md)
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data" / "sheet_snapshot" / "2026-09-25"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "data" / "sheet_templates"
OUT.mkdir(parents=True, exist_ok=True)

PARAM_COLS = ["case", "group", "stage", "item", "qualifier", "parameter", "description", "unit",
              "typical", "min", "max", "distribution", "choices", "source", "status", "comments"]

DESCRIPTIONS = {
    "machine weight": "Weight of the machine used in this step (used to account for machine wear)",
    "power": "Electric power the machine draws while running",
    "output rate": "Mass of material the machine processes per hour",
    "machine lifetime": "Operating hours before the machine is worn out",
    "process yield": "Share of the material entering this step that leaves it as usable output (the rest is waste)",
    "machine source": "Whether the machine is new (virgin) or reused/recycled (recycled)",
    "electricity location": "Country whose electricity mix is used in this step",
    "share of input mass": "Share of the input mass made of this material (the materials of one stage add up to 100 %)",
    "expected lifetime": "Years the product lasts before any repair",
    "lifetime extension per repair": "Years added to the product's life by one repair",
    "number of repair events": "Number of repairs over the product's life (0 = no repair)",
    "share of product mass per repair": "Mass of material added per repair, as a share of the product mass",
    "share of waste": "Share of the product's end-of-life mass that goes to this route (the routes add up to 100 %)",
    "disposal grid location": "Country whose electricity mix is displaced by energy recovered at end of life",
    "service life": "Years the product lasts in use",
}
ROUTE_LABEL = {"composted": "composted", "recycled_open": "recycled (open loop)", "recycled_closed": "recycled (closed loop)",
               "incinerated": "incinerated with energy recovery", "landfilled": "landfilled"}


def ranges(typical, kind):
    """Placeholder min/max (visible on the sheet, to be replaced by partner/literature ranges)."""
    if kind == "count":
        return max(int(typical) - 1, 0), int(typical) + 1
    if typical == 0:
        return 0, 0
    lo, hi = typical * 0.8, typical * 1.2
    if kind == "share":
        hi = min(hi, 100.0)
    return round(lo, 6), round(hi, 6)


def prow(case, group, stage, item, parameter, unit, typical, qualifier="", description=None, kind="numeric",
         choices="", source="", comments="", description_extra=""):
    row = dict(case=case, group=group, stage=stage, item=item, qualifier=qualifier, parameter=parameter,
               description=(description or DESCRIPTIONS.get(parameter, "")) + description_extra, unit=unit,
               typical=typical, choices=choices, source=source, status="placeholder", comments=comments)
    if kind == "categorical":
        row.update({"min": "", "max": "", "distribution": "choice"})
    else:
        lo, hi = ranges(float(typical), kind)
        row.update({"min": lo, "max": hi, "distribution": "triangular" if lo < hi else "fixed"})
    return row


# ── product formulas: named parameters instead of constants buried in formulas ──────────
# case -> {parameter: (value, unit, description)}
PRODUCT_PARAMS = {
    "raw_timber": {"depth_ratio": (20, "-", "Beam span divided by beam depth"),
                   "width_ratio": (3, "-", "Beam depth divided by beam width"),
                   "density": (480, "kg/m3", "Density of the finished timber beam")},
    "raw_cfw": {"fibre_length_per_span": (550, "m/m", "Metres of fibre wound per metre of beam span"),
                "fibre_mass_per_length": (0.006, "kg/m", "Mass of one metre of fibre (incl. resin)")},
    "raw_biopol": {"wall_height": (3, "m", "Height of the wall"),
                   "thickness_ratio": (10, "-", "Wall height divided by wall thickness"),
                   "density": (350, "kg/m3", "Density of the finished biopolymer wall")},
    "raw_knit": {"areal_density": (0.4, "kg/m2", "Mass of membrane per m2 of coverage")},
    "glulam beam": {"depth_ratio": (20, "-", "Beam span divided by beam depth"),
                    "width_ratio": (3, "-", "Beam depth divided by beam width")},
    "reinforced concrete beam": {"depth_ratio": (12, "-", "Beam span divided by beam depth"),
                                 "width_over_depth": (0.5, "-", "Beam width divided by beam depth"),
                                 "concrete_density": (2400, "kg/m3", "Density of reinforced concrete"),
                                 "steel_share": (0.06, "-", "Share of the beam mass that is reinforcing steel"),
                                 "formwork_thickness": (0.018, "m", "Thickness of the plywood formwork"),
                                 "formwork_density": (600, "kg/m3", "Density of the plywood formwork"),
                                 "formwork_reuse": (10, "-", "Times the formwork is reused")},
    "adobe brick for interior wall": {"wall_height": (3, "m", "Height of the wall"),
                                      "thickness_ratio": (10, "-", "Wall height divided by wall thickness"),
                                      "density": (1700, "kg/m3", "Density of the adobe wall (mortar is the same material)")},
    "clay brick for interior wall": {"wall_height": (3, "m", "Height of the wall"),
                                     "thickness": (0.115, "m", "Wall thickness (standard brick)"),
                                     "brick_share": (0.84, "-", "Share of the wall volume that is brick (rest is mortar)"),
                                     "density": (1900, "kg/m3", "Density of brick and mortar")},
    "synthetic polymer architectural membrane": {"areal_density": (0.3, "kg/m2", "Mass of polyester fibre per m2 of coverage")},
    '"traditional" coreless filament winded beam': {"fibre_length_per_span": (550, "m/m", "Metres of fibre per metre of beam span")},
}
FORMULAS = {   # (case_name, activity) -> formula in named parameters (RHS only)
    ("glulam beam", "glulam timber"): "(span / depth_ratio) * ((span / depth_ratio) / width_ratio) * span",
    ("reinforced concrete beam", "concrete"): "span * (span / depth_ratio) * (width_over_depth * (span / depth_ratio)) * concrete_density * (1 - steel_share)",
    ("reinforced concrete beam", "steel"): "span * (span / depth_ratio) * (width_over_depth * (span / depth_ratio)) * concrete_density * steel_share",
    ("reinforced concrete beam", "formwork"): "span * (2 * (span / depth_ratio) + width_over_depth * (span / depth_ratio)) * formwork_thickness * formwork_density / formwork_reuse",
    ('"traditional" coreless filament winded beam', "CFW beam"): "span * fibre_length_per_span",
    ("adobe brick for interior wall", "adobe brick"): "length * wall_height * (wall_height / thickness_ratio) * density",
    ("clay brick for interior wall", "clay brick"): "length * wall_height * thickness * brick_share * density",
    ("clay brick for interior wall", "lime mortar"): "length * wall_height * thickness * (1 - brick_share) * density",
    ("synthetic polymer architectural membrane", "polyester fiber"): "coverage * areal_density",
    ("synthetic polymer architectural membrane", "weaving"): "coverage * areal_density",
    ("raw_timber", "raw_timber production"): "span * (span / depth_ratio) * ((span / depth_ratio) / width_ratio) * density",
    ("raw_cfw", "raw_cfw production"): "span * fibre_length_per_span * fibre_mass_per_length",
    ("raw_biopol", "raw_biopol production"): "length * wall_height * (wall_height / thickness_ratio) * density",
    ("raw_knit", "raw_knit production"): "coverage * areal_density",
}
BASELINE_LIFE = {   # PLACEHOLDERS - no source yet
    "glulam beam": 60, "reinforced concrete beam": 75, "adobe brick for interior wall": 50,
    "clay brick for interior wall": 75, "synthetic polymer architectural membrane": 20,
    '"traditional" coreless filament winded beam': 50,
}


def raw_case_tab(cid, cases, bom, chain, par):
    name = cases.loc[cases.raw_case == cid, "display_name"].iloc[0]
    p = par[par.raw_case == cid].set_index("parameter")["value"].to_dict()
    rows = []
    # design
    for k, (v, u, d) in PRODUCT_PARAMS[cid].items():
        rows.append(prow(cid, "design", "product", "product size formula", k, u, v, description=d,
                         source="product_LCIs formula (previous version of the sheet)"))
    for stage in ("production", "repair"):
        for r in bom[(bom.raw_case == cid) & (bom.stage == stage)].itertuples():
            rows.append(prow(cid, "design", stage, r.material_name, "share of input mass", "%", r.percentage,
                             qualifier=r.material_source, kind="share",
                             description=f"Share of the {stage} input mass made of this material ({r.material_source}); the shares of one stage add up to 100 %"))
    # manufacturing
    steps = chain[chain.raw_case == cid]
    for stage in ("production", "repair"):
        for r in steps[steps.stage == stage].sort_values("step_order").itertuples():
            for pn, u, v in (("machine weight", "kg", r.machine_weight_kg), ("power", "kW", r.power_kW),
                             ("output rate", "kg/hr", r.output_efficiency_kg_per_hr),
                             ("machine lifetime", "hrs", r.machine_lifetime_hrs), ("process yield", "%", r.retained_pct)):
                rows.append(prow(cid, "manufacturing", stage, r.step_name, pn, u, v,
                                 kind="share" if pn == "process yield" else "numeric",
                                 source="HTML tool preset (placeholder)" if pn != "machine lifetime" else "HTML tool preset (placeholder)"))
            rows.append(prow(cid, "manufacturing", stage, r.step_name, "machine source", "-", r.machine_source,
                             kind="categorical", choices="virgin;recycled"))
    # circularity
    rows.append(prow(cid, "circularity", "use", "product", "expected lifetime", "yrs", float(p["expected_lifetime"])))
    rows.append(prow(cid, "circularity", "use", "product", "lifetime extension per repair", "yrs", float(p["lifetime_extension_per_repair"])))
    rows.append(prow(cid, "circularity", "use", "product", "number of repair events", "#", int(float(p["number_of_repair_events"])), kind="count"))
    rows.append(prow(cid, "circularity", "repair", "repair material", "share of product mass per repair", "%",
                     float(p["repair_material_pct_of_product"]), kind="share"))
    for route, key in (("composted", "eol_share_composted"), ("recycled_open", "eol_share_recycled_open_loop"),
                       ("recycled_closed", "eol_share_recycled_closed_loop"), ("incinerated", "eol_share_incinerated"),
                       ("landfilled", "eol_share_landfilled")):
        rows.append(prow(cid, "circularity", "end-of-life", "waste", "share of waste", "%", float(p[key]), qualifier=route,
                         kind="share", description_extra=f": {ROUTE_LABEL[route]}"))
    # location
    for stage in ("production", "repair"):
        for r in steps[steps.stage == stage].sort_values("step_order").itertuples():
            rows.append(prow(cid, "location", stage, r.step_name, "electricity location", "country code", r.electricity_location, kind="categorical"))
    rows.append(prow(cid, "location", "end-of-life", "waste", "disposal grid location", "country code", p["disposal_electricity_location"], kind="categorical"))
    df = pd.DataFrame(rows, columns=PARAM_COLS)
    return name, df


def main():
    cases, bom, chain = (pd.read_csv(PROC / f"{n}.csv") for n in ("raw_cases", "raw_bom", "raw_chain"))
    par = pd.read_csv(PROC / "raw_parameters.csv", dtype={"value": str})

    # 1) partner tabs
    for cid in cases.raw_case:
        name, df = raw_case_tab(cid, cases, bom, chain, par)
        df.to_csv(OUT / f"case_{cid.replace('raw_', '')}.csv", index=False)

    # 2) baselines tab
    eol = pd.read_csv(ROOT / "data" / "data_sources" / "baseline_eol_assumptions.csv", comment="#")
    lci_old = pd.read_csv(PROC / "product_lci.csv")
    rows = []
    for case_name in lci_old.loc[lci_old.case_type != "raw", "case_name"].unique():
        for k, (v, u, d) in PRODUCT_PARAMS[case_name].items():
            rows.append(prow(case_name, "design", "product", "product size formula", k, u, v, description=d,
                             source="product_LCIs formula (previous version of the sheet)"))
    for case_name in lci_old.loc[lci_old.case_type != "raw", "case_name"].unique():
        rows.append(prow(case_name, "circularity", "use", "product", "service life", "yrs", BASELINE_LIFE[case_name],
                         source="PLACEHOLDER - no source yet, to be set from literature"))
        acts = lci_old.loc[lci_old.case_name == case_name, "activity_name"].unique()
        for act in acts:
            for r in eol[eol.activity_name == act].itertuples():
                rows.append(prow(case_name, "circularity", "end-of-life", act, "share of waste", "%", float(r.share_pct),
                                 qualifier=r.route, kind="share", description_extra=f": {ROUTE_LABEL[r.route]}",
                                 source="LCA-team assumption (previous baseline_eol_assumptions.csv)"))
        rows.append(prow(case_name, "location", "end-of-life", "waste", "disposal grid location", "country code", "NL", kind="categorical"))
    pd.DataFrame(rows, columns=PARAM_COLS).to_csv(OUT / "baselines.csv", index=False)

    # 3) baseline_eol_setup (mapping data, not parameters)
    setup = eol[["activity_name", "kg_per_unit", "route", "treatment_burden_name", "lhv_MJ_per_kg", "carbon_material"]].copy()
    setup["comments"] = ""
    setup.to_csv(OUT / "baseline_eol_setup.csv", index=False)

    # 4) products (named parameters in formulas)
    display = dict(zip(cases.raw_case, cases.display_name))
    prod = []
    for r in lci_old.itertuples():
        formula = FORMULAS[(r.case_name, r.activity_name)]
        prod.append({"comparison_raw_timber": r.comparison_raw_timber, "comparison_raw_cfw": (True if r.case_name == "glulam beam" else r.comparison_raw_cfw),
                     "comparison_raw_biopol": r.comparison_raw_biopol, "comparison_raw_knit": r.comparison_raw_knit,
                     "element_type": r.element_type, "case_type": r.case_type, "case_name": r.case_name,
                     "display_name": display.get(r.case_name, r.case_name), "spec_variable": r.spec_var, "spec_label": r.spec_label, "spec_unit": r.spec_unit,
                     "activity_name": r.activity_name, "activity_unit": r.activity_unit, "formula": formula,
                     "amount_at_spec_1_check": r.sheet_amount_at_fu1, "comments": r.comments})
    pd.DataFrame(prod).to_csv(OUT / "products.csv", index=False)

    # 5) study_setup, scenarios, impact categories, constants, eol_routes, literature tables
    pd.DataFrame([
        ("reference_service_life", 50, "yrs", "Every product is compared over this period: results are scaled by reference life / product life"),
        ("spec_span", 6, "m", "Beam span used for the beam cases (raw_timber, raw_cfw and their baselines)"),
        ("spec_length", 4, "m", "Wall length used for the wall case (raw_biopol and its baselines)"),
        ("spec_coverage", 100, "m2", "Membrane coverage used for the membrane case (raw_knit and its baseline)"),
        ("sweep_span", "3:12:10", "min:max:steps (m)", "Range of beam spans for the spec sweep"),
        ("sweep_length", "2:12:11", "min:max:steps (m)", "Range of wall lengths for the spec sweep"),
        ("sweep_coverage", "10:500:10", "min:max:steps (m2)", "Range of membrane coverages for the spec sweep"),
        ("location_choices", "NL;DE;FR;ES;IT;PL;SE", "country codes", "Countries between which the location parameters vary in the sensitivity/uncertainty analysis (placeholder list)"),
        ("mc_iterations", 2000, "#", "Monte Carlo iterations for the parameter uncertainty analysis"),
        ("interval_percentiles", "5;95", "percent", "Lower and upper percentile of the uncertainty intervals drawn in the charts"),
        ("ecoinvent_version", "3.12", "-", "ecoinvent release used for the background"),
        ("ecoinvent_system_model", "cutoff", "-", "ecoinvent system model"),
        ("impact_method", "EF v3.1", "-", "LCIA method family (Brightway method names ecoinvent-<version> / <family> / ...)"),
        ("mc_seed", 42, "-", "Random seed (makes results reproducible)"),
        ("background_mc_iterations", 500, "#", "Brightway Monte Carlo iterations sampled for the background (ecoinvent) uncertainty"),
        ("sobol_base_samples", 512, "#", "Base sample size N of the Sobol sensitivity analysis"),
    ], columns=["parameter", "value", "unit", "description"]).to_csv(OUT / "study_setup.csv", index=False)

    pd.DataFrame([
        ("baseline", "today", "", "", "", "Ecoinvent 3.12 cut-off as is"),
        ("image_SSP2-M_2050", "2050 (SSP2-M)", "image", "SSP2-M", 2050, "premise scenario, medium ambition"),
        ("image_SSP2-L_2050", "2050", "image", "SSP2-L", 2050, "premise scenario used for the 2050 results"),
    ], columns=["scenario_id", "label", "premise_model", "premise_pathway", "premise_year", "comments"]).to_csv(OUT / "scenarios.csv", index=False)
    scen = pd.read_csv(OUT / "scenarios.csv")
    scen["in_results"] = [True, False, True]
    scen.to_csv(OUT / "scenarios.csv", index=False)

    ub = pd.read_csv(PROC / "unit_burdens.csv")
    cats = ub.drop_duplicates("impact_category")[["impact_category", "impact_category_unit"]]
    plotted = ["climate change", "ozone depletion", "particulate matter formation", "acidification",
               "eutrophication: freshwater", "land use", "water use", "material resources: metals/minerals"]
    labels = {"eutrophication: freshwater": "freshwater eutrophication", "material resources: metals/minerals": "mineral resources"}
    order = plotted + [c for c in cats.impact_category if c not in plotted]
    pd.DataFrame([(c, cats.set_index("impact_category").loc[c, "impact_category_unit"], labels.get(c, c), c in plotted)
                  for c in order], columns=["category", "unit", "label", "plot_in_bar_charts"]).to_csv(OUT / "impact_categories.csv", index=False)

    pd.DataFrame([
        ("time_horizon_yr", 100, "yrs", "Time horizon of the GWP_bio and dynamic characterisation factors", "Guest et al. 2012; Levasseur et al. 2010"),
        ("transport_distance_km", 50, "km", "Road-transport distance for collected (co-product, recycled, wild-harvested) materials", "assumption"),
        ("quality_ratio_primary", 1.0, "-", "Quality of primary (virgin) material in the circular footprint formula (Qp)", "assumption, no data"),
        ("co2_c_molar_ratio", round(44 / 12, 6), "kg CO2 / kg C", "Molar mass ratio CO2 to C (44 / 12)", "physical constant"),
        ("mj_per_kwh", 3.6, "MJ/kWh", "Unit conversion for the incineration electricity credit", "physical constant"),
        ("machine_wear_activity", "machine wear", "-", "Activity (in unit_burdens_dataSources) that gives the burden of one kg of machine wear", ""),
        ("electricity_activity", "energy use", "-", "Activity (in unit_burdens_dataSources) that gives the burden of one kWh of electricity, per country", ""),
        ("raw_product_eol_row", "RAW product", "-", "Row of the EoL_constants tab that gives the allocation factor, quality ratio, LHV and conversion efficiencies used for RAW products", ""),
    ], columns=["constant", "value", "unit", "description", "source"]).to_csv(OUT / "constants.csv", index=False)

    pd.DataFrame([
        ("composted", "waste composting", True, "avoided burden - composting", "", ""),
        ("recycled_open", "waste recycling", True, "avoided burden - open loop recycling", "", ""),
        ("recycled_closed", "waste recycling", True, "", "", ""),
        ("incinerated", "waste incineration", False, "", "avoided burden - incineration, heat", "avoided burden - incineration, electricity"),
        ("landfilled", "waste landfilling", False, "", "", ""),
    ], columns=["route", "treatment_activity", "cff_factor_applies", "material_credit_activity",
                "energy_credit_heat_activity", "energy_credit_electricity_activity"]).to_csv(OUT / "eol_routes.csv", index=False)

    gw = {1: [0.00, -0.07, -0.15, -0.23, -0.32, -0.40, -0.50, -0.60, -0.71, -0.84, -0.99],
          10: [0.04, -0.04, -0.12, -0.20, -0.28, -0.37, -0.46, -0.57, -0.68, -0.80, -0.96],
          20: [0.08, 0.00, -0.08, -0.16, -0.24, -0.33, -0.42, -0.53, -0.64, -0.76, -0.92],
          30: [0.12, 0.04, -0.04, -0.12, -0.20, -0.29, -0.38, -0.48, -0.60, -0.72, -0.88],
          40: [0.16, 0.09, 0.01, -0.08, -0.16, -0.25, -0.34, -0.44, -0.55, -0.68, -0.84],
          50: [0.20, 0.13, 0.05, -0.03, -0.12, -0.21, -0.30, -0.40, -0.51, -0.64, -0.80],
          60: [0.25, 0.17, 0.09, 0.01, -0.07, -0.16, -0.26, -0.36, -0.47, -0.59, -0.75],
          70: [0.29, 0.22, 0.14, 0.06, -0.03, -0.12, -0.21, -0.31, -0.42, -0.55, -0.71],
          80: [0.34, 0.26, 0.18, 0.10, 0.02, -0.07, -0.17, -0.27, -0.38, -0.50, -0.66],
          90: [0.38, 0.31, 0.23, 0.15, 0.06, -0.03, -0.12, -0.22, -0.33, -0.46, -0.62],
          100: [0.44, 0.37, 0.29, 0.21, 0.12, 0.032, -0.06, -0.16, -0.27, -0.40, -0.56]}
    g = pd.DataFrame(gw).T
    g.columns = [f"storage_{s}yr" for s in range(0, 101, 10)]
    g.insert(0, "rotation_period_yr", g.index)
    g["source"] = "Guest et al. (2012), Table 1, 100-yr time horizon"
    g.to_csv(OUT / "gwpbio_table.csv", index=False)
    pd.DataFrame([("a0", 0.217, ""), ("a1", 0.259, 172.9), ("a2", 0.338, 18.51), ("a3", 0.186, 1.186)],
                 columns=["term", "coefficient_a", "time_constant_tau_yr"]).assign(
        source="Bern carbon cycle model, Forster et al. 2007 via Levasseur et al. 2010 eq. 3").to_csv(OUT / "dcf_bern.csv", index=False)

    # 6) changed existing tabs
    ubs = pd.read_csv(SNAP / "unit_burdens_dataSources.csv")
    ubs["alternative_data_source"] = ubs["alternative_data_source"].replace({"road transport 50 km": "road transport"})
    ubs["comments"] = ubs["comments"].where(ubs["alternative_data_source"] != "road transport", "distance: transport_distance_km on the constants tab")
    ubs["activity_name"] = ubs["activity_name"].replace({"avoided buden - open loop recycling": "avoided burden - open loop recycling"})
    supp = pd.read_csv(ROOT / "data" / "data_sources" / "supplementary_sources.csv")
    supp["comments"] = supp["comments"].str.replace(r"\s*\(?[Ss]upplement to( the)? [Ss]heet\)?", "", regex=True)
    supp["comments"] = supp["comments"].str.replace(r"\. Supplement to the Google Sheet - move into the sheet when confirmed", "", regex=True)
    pd.concat([ubs, pd.DataFrame([{"activity_name": "End-of-life datasets for baseline products"}]), supp], ignore_index=True).to_csv(OUT / "unit_burdens_dataSources.csv", index=False)

    ben = pd.read_csv(SNAP / "benefits_constants_dataSources.csv")
    fossil = ["Fiber glue (epoxy resin)", "Wood glue", "Mechanical fastener (screws, nats, brackets)".replace("nats", "nails"), "Cement", "Lime"]
    add = [{"material_name": m, "unit": "1 kg ", "carbonContent_dryWeight_kg": 0, "carbonContent_source": "fossil/mineral material: no biogenic carbon",
            "rotationPeriod_yr": "n/a", "rotationPeriod_source": "n/a"} for m in fossil]
    add.append({"material_name": "Pea protein binder", "unit": "1 kg ", "carbonContent_dryWeight_kg": 0.2651685,
                "carbonContent_source": "derived: 0.45 kgC per kg pea (IPCC Tier 1 / Lal 2004) x 0.5893 kg peas per kg binder (biopol_lca LCI: peas -> isolate -> binder)",
                "rotationPeriod_yr": 1, "rotationPeriod_source": "Annual crop, same as peas"})
    add.append({"material_name": "glulam timber", "unit": "1 m3", "ecoinventDataset_name": "market for glued laminated timber, PUR-glue",
                "geographicalCoverage": "CH", "referenceProduct": "glued laminated timber, PUR-glue", "carbonContent_dryWeight_kg": "to extract w/ bw",
                "carbonContent_source": "ecoinvent", "rotationPeriod_yr": 65, "rotationPeriod_source": "Softwood CORRIM figure, same as Soft wood"})
    pd.concat([ben, pd.DataFrame(add)], ignore_index=True).to_csv(OUT / "benefits_constants_dataSources.csv", index=False)

    # unchanged tabs, copied so the folder is a complete sheet
    for tab in ("EoL_constants", "processes_typicalValues", "lcaModel_logic"):
        (OUT / f"{tab}.csv").write_text((SNAP / f"{tab}.csv").read_text())
    print(sorted(p.name for p in OUT.glob("*.csv")))


if __name__ == "__main__":
    main()
