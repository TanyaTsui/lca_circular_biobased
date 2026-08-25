"""
Regenerates data.js from the three processed CSVs (unit_burdens, eol_constants,
benefits_constants) in ../../../data/processed/. Run this whenever those CSVs change.

Usage:
    python build_data.py
"""
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"
OUT_PATH = Path(__file__).resolve().parent / "data.js"

# Points at the dummy scenario dataset (baseline / image_SSP2-M_2050 / image_SSP2-L_2050)
# built alongside 02_model.ipynb's USE_DUMMY_DATA toggle, since there's no real premise
# output yet. Flip to "unit_burdens.csv" once 01b_dataPrep_prospective.ipynb has been run
# for real.
SOURCE_UNIT_BURDENS = "unit_burdens_dummy.csv"

# Same EU normalisation factors as 02_model.ipynb's EF_NORMALISATION cell — not derived
# from the CSVs, and not currently used by calc.js/app.js, but kept for parity with the
# notebook and in case a normalised view gets added later.
EF_NORMALISATION = {
    "climate change": 8.10e03,
    "climate change: biogenic": 8.10e03,
    "climate change: fossil": 8.10e03,
    "climate change: land use and land use change": 8.10e03,
    "ecotoxicity: freshwater": 4.27e04,
    "ecotoxicity: freshwater, inorganics": 4.27e04,
    "ecotoxicity: freshwater, organics": 4.27e04,
    "energy resources: non-renewable": 6.50e04,
    "eutrophication: freshwater": 1.61e00,
    "eutrophication: marine": 1.95e01,
    "eutrophication: terrestrial": 1.77e02,
    "human toxicity: carcinogenic": 1.72e-05,
    "human toxicity: carcinogenic, inorganics": 1.72e-05,
    "human toxicity: carcinogenic, organics": 1.72e-05,
    "human toxicity: non-carcinogenic": 2.30e-04,
    "human toxicity: non-carcinogenic, inorganics": 2.30e-04,
    "human toxicity: non-carcinogenic, organics": 2.30e-04,
    "ionising radiation: human health": 4.22e03,
    "land use": 8.19e05,
    "material resources: metals/minerals": 6.36e-02,
    "ozone depletion": 5.36e-02,
    "particulate matter formation": 5.95e-04,
    "photochemical oxidant formation: human health": 4.06e01,
    "water use": 1.15e04,
    "acidification": 5.56e01,
}


def build_categories(df_burdens):
    """Alphabetical, with 'climate change' pulled to the front (it's the tool's default)."""
    cats = sorted(df_burdens["impact_category"].unique().tolist())
    if "climate change" in cats:
        cats.remove("climate change")
        cats.insert(0, "climate change")
    return cats


def build_unit_burdens(df_burdens):
    has_scenario = "scenario" in df_burdens.columns
    rows = []
    for _, r in df_burdens.iterrows():
        row = {
            "m": r["material_name"],
            "loc": r["location"] if pd.notna(r["location"]) else None,
            "src": r["material_source"] if pd.notna(r["material_source"]) else None,
            "cat": r["impact_category"],
            "unit": r["impact_category_unit"],
            "score": r["score"],
        }
        if has_scenario:
            row["scn"] = r["scenario"]
        rows.append(row)
    return rows


def build_scenarios(df_burdens):
    if "scenario" not in df_burdens.columns:
        return ["baseline"]
    scenarios = df_burdens["scenario"].unique().tolist()
    scenarios.sort(key=lambda s: (s != "baseline", s))  # "baseline" first, rest alphabetical
    return scenarios


def build_eol_constants(df_eol):
    return {
        r["material_name"]: {
            "A": r["allocation_factor"],
            "Qs": r["quality_ratio"],
            "LHV": r["lower_heating_value_MJperKgDry"],
        }
        for _, r in df_eol.iterrows()
    }


def build_benefit_params(df_benefits):
    out = {}
    for _, r in df_benefits.iterrows():
        rot = r["rotation_period_yr"]
        out[r["material_name"]] = {
            "C": r["carbon_content_kgC_per_kgWet"],
            "rot": rot if pd.notna(rot) else None,
        }
    return out


# Process/EoL-route rows in unit_burdens.csv — referenced directly by name inside
# calc.js/02_model.ipynb (get_unit_burden("machine wear"), ("energy use"), etc.), never
# selectable as a BOM material even though some of them do carry a material_source
# (e.g. "machine wear": virgin/recycled).
PROCESS_MATERIALS = {
    "energy use", "machine wear", "Road transport",
    "waste composting", "waste incineration", "waste landfilling", "waste recycling",
    "avoided burden - composting", "avoided buden - open loop recycling",
    "avoided burden - incineration, heat", "avoided burden - incineration, electricity",
}


def build_bom_materials(df_burdens):
    """Materials selectable in the BOM editor: real materials with a material_source,
    excluding PROCESS_MATERIALS."""
    has_source = df_burdens[
        df_burdens["material_source"].notna()
        & ~df_burdens["material_name"].isin(PROCESS_MATERIALS)
    ]
    out = {}
    for name, group in has_source.groupby("material_name"):
        out[name] = sorted(group["material_source"].unique().tolist())
    return out


def build_locations(df_burdens):
    """Country codes selectable for electricity location — derived from 'energy use'
    specifically, not every `location` value in the file (some rows carry a region/global
    aggregate code like RER/GLO/RoW that isn't a selectable electricity market)."""
    return sorted(df_burdens.loc[df_burdens["material_name"] == "energy use", "location"].dropna().unique().tolist())


def main():
    df_burdens = pd.read_csv(DATA_DIR / SOURCE_UNIT_BURDENS)
    df_eol = pd.read_csv(DATA_DIR / "eol_constants.csv")
    df_benefits = pd.read_csv(DATA_DIR / "benefits_constants.csv")

    raw_data = {
        "unitBurdens": build_unit_burdens(df_burdens),
        "eolConstants": build_eol_constants(df_eol),
        "benefitParams": build_benefit_params(df_benefits),
        "categories": build_categories(df_burdens),
        "efNormalisation": EF_NORMALISATION,
        "bomMaterials": build_bom_materials(df_burdens),
        "locations": build_locations(df_burdens),
        "scenarios": build_scenarios(df_burdens),
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by build_data.py from unit_burdens / eol_constants / benefits_constants CSVs\n")
        f.write("// Run `python build_data.py` after changing SOURCE_UNIT_BURDENS or the underlying CSVs.\n")
        f.write("const RAW_DATA = ")
        json.dump(raw_data, f, allow_nan=False)
        f.write(";\n")

    n_materials = df_burdens["material_name"].nunique()
    n_categories = len(raw_data["categories"])
    print(f"Wrote {OUT_PATH}")
    print(f"  {len(raw_data['unitBurdens'])} unit burden rows "
          f"({n_materials} materials/processes x {n_categories} categories x {len(raw_data['scenarios'])} scenario(s))")
    print(f"  scenarios: {raw_data['scenarios']}")
    print(f"  {len(raw_data['bomMaterials'])} BOM-selectable materials, {len(raw_data['locations'])} locations")


if __name__ == "__main__":
    main()
