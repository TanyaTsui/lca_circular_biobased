"""
Resolved products: the numbers the model needs for one RAW case or one baseline product, built from the
sheet's parameter table (`ParameterSet`) for a given set of parameter values (typical values or a sample).
No numbers live in this file. Scaled-up variants use the `scaled_up` column of the production chain rows.
"""
from dataclasses import dataclass, field, replace
from typing import Dict, List

import pandas as pd

ROUTES = ("composted", "recycled_open", "recycled_closed", "incinerated", "landfilled")


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
class BaselineCase:
    case_name: str
    service_life_yr: float
    disposal_location: str
    eol_shares: Dict[str, Dict[str, float]]   # activity -> route -> share (%, adds up to 100)


# ── resolving from the parameter table ────────────────────────────────────────────────
def _normalise(shares: Dict[str, float]) -> Dict[str, float]:
    total = sum(shares.values())
    return {k: (100.0 * v / total if total > 0 else 0.0) for k, v in shares.items()}


def product_params(product_size_constants, case: str) -> Dict[str, float]:
    """Named constants of the product size formula for one case (fixed - not sampled)."""
    rows = product_size_constants[product_size_constants.case == case]
    return {r.parameter: float(r.value) for r in rows.itertuples()}


def resolve_raw_case(ps, case_id: str, name: str, values: dict) -> RawCase:
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
    repair = RepairSpec(material_pct_of_product=float(val("repair", "repair material", "share of product mass per repair")),
                        expected_lifetime_yr=float(val("use", "product", "expected lifetime")),
                        extension_per_repair_yr=float(val("use", "product", "lifetime extension per repair")),
                        n_repairs=int(round(float(val("use", "product", "number of repair events")))))
    return RawCase(case_id=case_id, name=name, production_bom=bom("production"), production_chain=chain("production"),
                   eol=eol, repair=repair, repair_bom=bom("repair"), repair_chain=chain("repair"))


def resolve_baseline(ps, case_name: str, values: dict) -> BaselineCase:
    rows = ps.rows(case_name)
    lk = ps.lookup(case_name)
    eol = rows[(rows.stage == "end-of-life") & (rows.parameter == "share of waste")]
    shares: Dict[str, Dict[str, float]] = {}
    for r in eol.itertuples():
        shares.setdefault(r.item, {})[r.qualifier] = float(values[r.id])
    return BaselineCase(case_name=case_name,
                        service_life_yr=float(values[lk[("use", "product", "", "service life")]]),
                        disposal_location=str(values[lk[("end-of-life", "waste", "", "disposal grid location")]]),
                        eol_shares={a: _normalise(s) for a, s in shares.items()})


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
