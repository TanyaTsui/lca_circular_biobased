"""Runs a RAW case, its scaled-up variant and its baselines for one product spec and one set of parameter values."""
from typing import Dict, List, Optional, Tuple

from .cases import resolve_baseline, resolve_raw_case, product_params, scale_up_case
from .formulas import evaluate_formula
from .inputs import Inputs
from .model import Model, Result


def spec_variable(inp: Inputs, case: str) -> str:
    return inp.products.loc[inp.products.case_name == case, "spec_variable"].iloc[0]


def activity_amounts(inp: Inputs, case: str, spec_value: float, values: Optional[dict] = None) -> List[Tuple[str, float, str]]:
    """[(activity, amount, unit)] of a product case for a spec value (formulas of the `products` tab)."""
    values = values or inp.params.typical()
    rows = inp.products[inp.products.case_name == case]
    variables = product_params(inp.params, case, values)
    variables[rows.spec_variable.iloc[0]] = spec_value
    return [(r.activity_name, evaluate_formula(r.formula, variables), r.activity_unit) for r in rows.itertuples()]


def run_products(model: Model, raw_case_id: str, spec_value: Optional[float] = None, values: Optional[dict] = None,
                 iteration: Optional[int] = None, scaled_up: bool = True) -> Dict[str, Result]:
    """{label: Result} for the RAW case, its scaled-up variant and the baselines flagged for it on the sheet."""
    inp = model.inp
    values = values or inp.params.typical()
    if spec_value is None:
        spec_value = inp.specs[spec_variable(inp, raw_case_id)]
    display = inp.raw_cases()[raw_case_id]
    raw_kg = activity_amounts(inp, raw_case_id, spec_value, values)[0][1]
    raw = resolve_raw_case(inp.params, raw_case_id, display, values)
    results = {raw.name: model.run_raw(raw, raw_kg, iteration)}
    if scaled_up:
        up = scale_up_case(raw, inp.machine_params)
        results[up.name] = model.run_raw(up, raw_kg, iteration)
    for b in inp.baselines_for(raw_case_id):
        bc = resolve_baseline(inp.params, b, values)
        label = inp.products.loc[inp.products.case_name == b, "display_name"].iloc[0]
        results[label] = model.run_baseline(bc, activity_amounts(inp, b, spec_value, values), iteration, label)
    return results


def run_raw_only(model: Model, raw_case_id: str, spec_value: Optional[float] = None, values: Optional[dict] = None,
                 scaled_up: bool = False, iteration: Optional[int] = None) -> Result:
    """Only the RAW case (or its scaled-up variant): used by the sensitivity analysis."""
    inp = model.inp
    values = values or inp.params.typical()
    if spec_value is None:
        spec_value = inp.specs[spec_variable(inp, raw_case_id)]
    raw_kg = activity_amounts(inp, raw_case_id, spec_value, values)[0][1]
    raw = resolve_raw_case(inp.params, raw_case_id, inp.raw_cases()[raw_case_id], values)
    if scaled_up:
        raw = scale_up_case(raw, inp.machine_params)
    return model.run_raw(raw, raw_kg, iteration)
