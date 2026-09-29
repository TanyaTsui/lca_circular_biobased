"""
Resolved products: the numbers the model needs for one RAW case or one baseline product, built from the
sheet's parameter table (`ParameterSet`) for a given set of parameter values (typical values or a sample).
No numbers live in this file. Scaled-up variants use the `scaled_up` column of the production chain rows.
"""
import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Tuple

import pandas as pd

ROUTES = ("composted", "recycled_open", "recycled_closed", "incinerated", "landfilled")
EOL_TYPES = ("recycling", "composting", "incineration", "landfill")    # eol_type of a waste treatment activity
PER_KG = "amount per kg product"                                        # parameter of every baseline LCI row
SIZE_STAGE = "product size"                                             # constants of the product size formula


@dataclass
class BOMItem:
    material_name: str
    percentage: float        # share of the input mass of the stage (a stage's items add up to 100)
    material_source: str     # virgin / co-product / recycled / wild-harvested


@dataclass
class ProcessStep:
    step_name: str
    kg_machine: float
    power_kW: float
    rate_kg_per_hr: float
    machine_lifetime_hrs: float
    electricity_location: str
    retained_pct: float      # process yield
    machine_source: str = "virgin"   # virgin / recycled


@dataclass
class RepairSpec:
    material_pct_of_product: float = 0.0
    expected_lifetime_yr: float = 0.0
    extension_per_repair_yr: float = 0.0
    n_repairs: int = 0


@dataclass
class EolShares:
    composted: float = 0.0
    recycled_open: float = 0.0
    recycled_closed: float = 0.0
    incinerated: float = 0.0
    landfilled: float = 0.0
    disposal_location: str = "NL"


@dataclass
class RawCase:
    case_id: str
    name: str
    production_bom: List[BOMItem]
    production_chain: List[ProcessStep]
    eol: EolShares
    repair: RepairSpec
    repair_bom: List[BOMItem] = field(default_factory=list)
    repair_chain: List[ProcessStep] = field(default_factory=list)

    @property
    def service_life_yr(self) -> float:
        r = self.repair
        return r.expected_lifetime_yr + r.extension_per_repair_yr * r.n_repairs


@dataclass
class BaselineEol:
    treatment: str           # waste treatment activity (unit_burdens_dataSources)
    material: str            # material that is treated (EoL_constants)
    kg_per_kg: float         # kg of the material going to this treatment, per kg of product


@dataclass
class BaselineCase:
    case_name: str
    service_life_yr: float
    location: str
    inputs: List[Tuple[str, float]]    # (activity, amount per kg of product)
    eol: List[BaselineEol]


# ── resolving from the parameter table ────────────────────────────────────────────────
def _normalise(shares: Dict[str, float]) -> Dict[str, float]:
    total = sum(shares.values())
    return {k: (100.0 * v / total if total > 0 else 0.0) for k, v in shares.items()}


def product_params(ps, case: str, values: dict) -> Dict[str, float]:
    """Named constants of the case's product size formula (its 'product size' rows), at the given parameter values."""
    rows = ps.rows(case)
    return {r.parameter: float(values[r.id]) for r in rows[rows.stage == SIZE_STAGE].itertuples()}


def repairs_needed(expected_lifetime_yr: float, extension_per_repair_yr: float, service_life_yr: float) -> int:
    """Smallest number of repairs that makes the product last the functional unit's service life."""
    if expected_lifetime_yr >= service_life_yr or extension_per_repair_yr <= 0:
        return 0
    return math.ceil((service_life_yr - expected_lifetime_yr) / extension_per_repair_yr - 1e-9)


def resolve_raw_case(ps, case_id: str, name: str, values: dict, service_life_yr: float) -> RawCase:
    """`service_life_yr`: the service life of the case's functional unit, which sets the number of repairs."""
    lk = ps.lookup(case_id)
    rows = ps.rows(case_id)
    val = lambda stage, item, param, qual="": values[lk[(stage, item, qual, param)]]
    location = str(val("general", "product", "location"))     # one location for every step and disposal

    def bom(stage):
        r = rows[(rows.stage == stage) & (rows.parameter == "share of input mass")]
        shares = {(x.item, x.qualifier): float(values[x.id]) for x in r.itertuples()}
        shares = _normalise(shares)
        return [BOMItem(i, s, q) for (i, q), s in shares.items()]

    def chain(stage):
        r = rows[(rows.stage == stage) & (rows.parameter == "machine weight")]
        steps = list(dict.fromkeys(r.item))                      # order of the rows on the sheet
        return [ProcessStep(s, float(val(stage, s, "machine weight")), float(val(stage, s, "power")),
                            float(val(stage, s, "output rate")), float(val(stage, s, "machine lifetime")),
                            location, float(val(stage, s, "process yield")),
                            str(val(stage, s, "machine source"))) for s in steps]

    shares = _normalise({route: float(val("end-of-life", "waste", "share of waste", route)) for route in ROUTES})
    eol = EolShares(**shares, disposal_location=location)
    expected = float(val("use", "product", "expected lifetime"))
    extension = float(val("use", "product", "lifetime extension per repair"))
    repair = RepairSpec(material_pct_of_product=float(val("repair", "repair material", "share of product mass per repair")),
                        expected_lifetime_yr=expected, extension_per_repair_yr=extension,
                        n_repairs=repairs_needed(expected, extension, service_life_yr))
    return RawCase(case_id=case_id, name=name, production_bom=bom("production"), production_chain=chain("production"),
                   eol=eol, repair=repair, repair_bom=bom("repair"), repair_chain=chain("repair"))


def resolve_baseline(ps, case_name: str, values: dict) -> BaselineCase:
    rows = ps.rows(case_name)
    lk = ps.lookup(case_name)
    prod = rows[(rows.stage == "production") & (rows.parameter == PER_KG)]
    eol = rows[(rows.stage == "end-of-life") & (rows.parameter == PER_KG)]
    amounts = [float(values[r.id]) for r in eol.itertuples()]
    total = sum(amounts)
    scale = sum(float(t) for t in eol["typical_value"]) / total if total > 0 else 0.0   # keep the typical waste mass
    return BaselineCase(case_name=case_name,
                        service_life_yr=float(values[lk[("use", "product", "", "service life")]]),
                        location=str(values[lk[("general", "product", "", "location")]]),
                        inputs=[(r.item, float(values[r.id])) for r in prod.itertuples()],
                        eol=[BaselineEol(r.item, r.qualifier, a * scale) for r, a in zip(eol.itertuples(), amounts)])


# ── scaled-up variant (sheet-driven) ────────────────────────────────────────────────────
CHAIN_FIELD_BY_PARAM = {           # sheet `parameter` label -> ProcessStep field
    "machine weight": "kg_machine",
    "machine lifetime": "machine_lifetime_hrs",
    "output rate": "rate_kg_per_hr",
    "power": "power_kW",
}


def scale_up_case(case: RawCase, ps, case_id: str) -> RawCase:
    """Copy of `case` whose PRODUCTION steps that carry a `scaled_up` value (on every one of their machine
    weight / power / output rate / machine lifetime rows) use those values instead of the prototype ones.
    A step with no `scaled_up` values is left unchanged. Everything but the production chain is unchanged."""
    rows = ps.rows(case_id)
    prod = rows[(rows.stage == "production") & (rows.parameter.isin(CHAIN_FIELD_BY_PARAM))]
    overrides: Dict[str, Dict[str, float]] = {}
    for r in prod.itertuples():
        if pd.notna(r.scaled_up):
            overrides.setdefault(r.item, {})[CHAIN_FIELD_BY_PARAM[r.parameter]] = float(r.scaled_up)
    chain = [replace(st, **overrides[st.step_name]) if st.step_name in overrides else st
             for st in case.production_chain]
    return replace(case, name=f"{case.name} - scaled up", production_chain=chain)
