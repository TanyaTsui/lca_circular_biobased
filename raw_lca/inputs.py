"""Everything the model reads from a sheet snapshot, gathered in one object."""
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from .params import ParameterSet
from .sheet import Issue, load_tables, validate


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


@dataclass
class Inputs:
    tables: Dict[str, pd.DataFrame]
    params: ParameterSet
    products: pd.DataFrame
    product_size_constants: pd.DataFrame
    fu_comparisons: pd.DataFrame
    constants: Dict[str, object]
    setup: Dict[str, object]
    specs: Dict[str, float]           # spec variable -> value (span, length, coverage)
    sweeps: Dict[str, np.ndarray]     # spec variable -> values of the spec sweep
    location_choices: List[str]
    scenarios: pd.DataFrame
    categories: pd.DataFrame
    eol_constants: pd.DataFrame       # indexed by material_name
    eol_routes: pd.DataFrame          # indexed by route
    baseline_eol_setup: pd.DataFrame
    gwpbio: pd.DataFrame              # rotation_period_yr x storage columns
    bern: pd.DataFrame
    snapshot: Path

    def reference_service_life_for(self, raw_case_id: str) -> float:
        """The reference period the RAW case and its baselines are compared over (fu_comparison tab)."""
        row = self.fu_comparisons.loc[self.fu_comparisons.raw_case == raw_case_id].iloc[0]
        return float(row["service_life"])

    def raw_cases(self) -> Dict[str, str]:
        """{raw case id: display name}"""
        raw = self.products[self.products.case_type == "raw"].drop_duplicates("case_name")
        return dict(zip(raw.case_name, raw.display_name))

    def baselines_for(self, raw_case_id: str) -> List[str]:
        """Baseline cases of a RAW case (fu_comparison tab), bio-based before fossil-based."""
        row = self.fu_comparisons.loc[self.fu_comparisons.raw_case == raw_case_id].iloc[0]
        names = [row["baseline_biobased"], row["baseline_fossil"]]
        return [str(n).strip() for n in names if not pd.isna(n) and str(n).strip()]


def load_inputs(snapshot_dir, raise_on_error: bool = True) -> Inputs:
    tables = load_tables(snapshot_dir)
    issues: List[Issue] = validate(tables)
    errors = [i for i in issues if i.level == "error"]
    if errors and raise_on_error:
        raise ValueError("Sheet validation failed:\n" + "\n".join(str(i) for i in errors))
    setup = {r.parameter: _num(r.value) for r in tables["study_setup"].itertuples()}
    specs = {k[len("spec_"):]: float(v) for k, v in setup.items() if k.startswith("spec_")}
    sweeps = {}
    for k, v in setup.items():
        if k.startswith("sweep_"):
            lo, hi, n = str(v).split(":")
            sweeps[k[len("sweep_"):]] = np.linspace(float(lo), float(hi), int(n))
    eolc = tables["EoL_constants"].copy()
    eolc = eolc.dropna(subset=["material_name"]).set_index("material_name")
    for c in ("allocation_factor", "quality_ratio", "lower_heating_value_MJperKgDry",
              "conversionEfficiency_heat", "conversionEfficiency_electricity"):
        eolc[c] = pd.to_numeric(eolc[c], errors="coerce")
    products = tables["products"]
    return Inputs(
        tables=tables, params=ParameterSet.from_tables(tables), products=products,
        product_size_constants=tables["product_size_constants"], fu_comparisons=tables["fu_comparison"],
        constants={r.constant: _num(r.value) for r in tables["constants"].itertuples()},
        setup=setup, specs=specs, sweeps=sweeps, location_choices=[c for c in str(setup["location_choices"]).split(";") if c],
        scenarios=tables["scenarios"], categories=tables["impact_categories"], eol_constants=eolc,
        eol_routes=tables["eol_routes"].fillna("").set_index("route"), baseline_eol_setup=tables["baseline_eol_setup"],
        gwpbio=tables["gwpbio_table"], bern=tables["dcf_bern"], snapshot=Path(snapshot_dir))
