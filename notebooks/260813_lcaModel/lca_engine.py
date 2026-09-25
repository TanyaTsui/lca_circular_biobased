"""
LCA engine for the RAW product-level comparison (used by 03_productComparison.ipynb).

The unit-burden / EoL / benefit logic is lifted from 02_model.ipynb (same formulas, same
conventions) and parameterised on a `DataStore` instead of notebook globals. Nothing here
calls Brightway - it only reads the CSVs written by 01_dataPrep / 01b_dataPrep_prospective /
01c_dataPrep_productLCI.

Layers:
    DataStore        loads unit_burdens / eol_constants / benefits_constants / product_lci
                     / baseline_eol for one scenario
    evaluate_formula safe evaluator for the product-LCI formulas (spec -> amount)
    run_raw_case     full lifecycle of a RAW case (BOM + chains + repair + EoL) for a product mass
    run_baseline     cradle-to-gate + simple EoL for a baseline product (activities x unit burden)
    compare          runs a RAW case and its baselines for one spec value
"""
from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ── Constants (unchanged from 02_model.ipynb) ─────────────────────────────────
QUALITY_RATIO_PRIMARY = 1.0   # Qp
CONV_EFF_HEAT = 0.6
CONV_EFF_ELEC = 0.25
MOLAR_RATIO = 44 / 12         # kg CO2 per kg C
GWP = "climate change"

EF_NORMALISATION = {
    'climate change': 8.10e+03, 'climate change: biogenic': 8.10e+03,
    'climate change: fossil': 8.10e+03, 'climate change: land use and land use change': 8.10e+03,
    'ecotoxicity: freshwater': 4.27e+04, 'ecotoxicity: freshwater, inorganics': 4.27e+04,
    'ecotoxicity: freshwater, organics': 4.27e+04, 'energy resources: non-renewable': 6.50e+04,
    'eutrophication: freshwater': 1.61e+00, 'eutrophication: marine': 1.95e+01,
    'eutrophication: terrestrial': 1.77e+02, 'human toxicity: carcinogenic': 1.72e-05,
    'human toxicity: carcinogenic, inorganics': 1.72e-05, 'human toxicity: carcinogenic, organics': 1.72e-05,
    'human toxicity: non-carcinogenic': 2.30e-04, 'human toxicity: non-carcinogenic, inorganics': 2.30e-04,
    'human toxicity: non-carcinogenic, organics': 2.30e-04, 'ionising radiation: human health': 4.22e+03,
    'land use': 8.19e+05, 'material resources: metals/minerals': 6.36e-02, 'ozone depletion': 5.36e-02,
    'particulate matter formation': 5.95e-04, 'photochemical oxidant formation: human health': 4.06e+01,
    'water use': 1.15e+04, 'acidification': 5.56e+01,
}

# The 16 top-level EF v3.1 categories (subcategories excluded) - used for comparison charts
EF_TOP_LEVEL = [
    'climate change', 'ozone depletion', 'ionising radiation: human health',
    'photochemical oxidant formation: human health', 'particulate matter formation',
    'human toxicity: non-carcinogenic', 'human toxicity: carcinogenic', 'acidification',
    'eutrophication: freshwater', 'eutrophication: marine', 'eutrophication: terrestrial',
    'ecotoxicity: freshwater', 'land use', 'water use',
    'material resources: metals/minerals', 'energy resources: non-renewable',
]

# GWP_bio lookup table - Guest et al. (2012), Table 1, 100-yr TH
ROTATION_PERIODS = [1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
STORAGE_PERIODS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
GWPBIO_TABLE = {
     1:   [ 0.00, -0.07, -0.15, -0.23, -0.32, -0.40, -0.50, -0.60, -0.71, -0.84, -0.99],
    10:   [ 0.04, -0.04, -0.12, -0.20, -0.28, -0.37, -0.46, -0.57, -0.68, -0.80, -0.96],
    20:   [ 0.08,  0.00, -0.08, -0.16, -0.24, -0.33, -0.42, -0.53, -0.64, -0.76, -0.92],
    30:   [ 0.12,  0.04, -0.04, -0.12, -0.20, -0.29, -0.38, -0.48, -0.60, -0.72, -0.88],
    40:   [ 0.16,  0.09,  0.01, -0.08, -0.16, -0.25, -0.34, -0.44, -0.55, -0.68, -0.84],
    50:   [ 0.20,  0.13,  0.05, -0.03, -0.12, -0.21, -0.30, -0.40, -0.51, -0.64, -0.80],
    60:   [ 0.25,  0.17,  0.09,  0.01, -0.07, -0.16, -0.26, -0.36, -0.47, -0.59, -0.75],
    70:   [ 0.29,  0.22,  0.14,  0.06, -0.03, -0.12, -0.21, -0.31, -0.42, -0.55, -0.71],
    80:   [ 0.34,  0.26,  0.18,  0.10,  0.02, -0.07, -0.17, -0.27, -0.38, -0.50, -0.66],
    90:   [ 0.38,  0.31,  0.23,  0.15,  0.06, -0.03, -0.12, -0.22, -0.33, -0.46, -0.62],
   100:   [ 0.44,  0.37,  0.29,  0.21,  0.12,  0.032,-0.06, -0.16, -0.27, -0.40, -0.56],
}
BERN_A = [0.217, 0.259, 0.338, 0.186]
BERN_TAU = [None, 172.9, 18.51, 1.186]


def lookup_gwpbio(rotation_yr, storage_yr):
    """GWP_bio factor, linearly interpolated between 10-yr storage columns."""
    nearest_rotation = min(GWPBIO_TABLE, key=lambda r: abs(r - rotation_yr))
    row = GWPBIO_TABLE[nearest_rotation]
    storage_yr = max(0, min(storage_yr, STORAGE_PERIODS[-1]))
    if storage_yr % 10 == 0:
        return row[STORAGE_PERIODS.index(int(storage_yr))]
    lo = int(storage_yr // 10) * 10
    hi = lo + 10
    frac = (storage_yr - lo) / 10
    return row[STORAGE_PERIODS.index(lo)] * (1 - frac) + row[STORAGE_PERIODS.index(hi)] * frac


def agwp_integral(t):
    a0, a1, a2, a3 = BERN_A
    _, tau1, tau2, tau3 = BERN_TAU
    return (a0 * t + a1 * tau1 * (1 - np.exp(-t / tau1)) + a2 * tau2 * (1 - np.exp(-t / tau2))
            + a3 * tau3 * (1 - np.exp(-t / tau3)))


def dynamic_cf(tau_storage, T=100):
    """Dynamic characterisation factor (Levasseur et al., 2010) for a CO2 pulse delayed tau_storage yr."""
    return agwp_integral(T - tau_storage) / agwp_integral(T)


# ── Safe formula evaluator ────────────────────────────────────────────────────
_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def evaluate_formula(expr: str, variables: Dict[str, float]) -> float:
    """Evaluate a product-LCI formula such as '(span / 20) * span' with only numbers,
    the given variables, + - * / ** and parentheses. Anything else raises ValueError."""
    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"Unknown variable '{node.id}' in formula '{expr}' (have {sorted(variables)})")
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](_ev(node.operand))
        raise ValueError(f"Disallowed syntax in formula '{expr}': {ast.dump(node)[:80]}")
    return _ev(ast.parse(expr.strip(), mode="eval"))


def formula_rhs(raw_formula: str) -> str:
    """Drop the 'm3 = ' / 'kg = ' left-hand side used in the sheet."""
    return raw_formula.split("=", 1)[1].strip() if "=" in raw_formula else raw_formula.strip()


def formula_variables(rhs: str) -> List[str]:
    return sorted(set(re.findall(r"[A-Za-z_]\w*", rhs)))


# ── Inputs ────────────────────────────────────────────────────────────────────
@dataclass
class BOMItem:
    material_name: str
    percentage: float        # share of total input mass at this stage (BOM sums to 100)
    material_source: str     # "virgin" / "co-product" / "recycled" / "wild-harvested"


@dataclass
class ProcessStep:
    step_name: str
    kg_machine: float
    power_kW: float
    rate_kg_per_hr: float
    machine_lifetime_hrs: float
    electricity_location: str
    retained_pct: float
    machine_source: str = "virgin"


@dataclass
class RepairSpec:
    enabled: bool = True
    material_pct_of_product: float = 10.0
    expected_lifetime_yr: float = 20.0
    extension_per_repair_yr: float = 10.0
    n_repairs: int = 0


@dataclass
class EolShares:
    composted: float = 0
    recycled_open: float = 0
    recycled_closed: float = 0
    incinerated: float = 0
    landfilled: float = 0
    disposal_location: str = "NL"

    def check(self, label="EoL"):
        total = self.composted + self.recycled_open + self.recycled_closed + self.incinerated + self.landfilled
        if abs(total - 100) > 0.01:
            raise ValueError(f"{label} shares sum to {total}, not 100")


@dataclass
class RawCase:
    """A RAW product: BOM + production chain (+ optional repair) + EoL. Sized by product mass."""
    case_id: str                       # e.g. "raw_timber" - matches case_name in product_lci.csv
    name: str
    production_bom: List[BOMItem]
    production_chain: List[ProcessStep]
    eol: EolShares
    repair: RepairSpec = field(default_factory=RepairSpec)
    repair_bom: List[BOMItem] = field(default_factory=list)
    repair_chain: List[ProcessStep] = field(default_factory=list)
    notes: str = ""


@dataclass
class Result:
    """Per-category vectors (indexed by impact_category) for one case at one spec value."""
    label: str
    materials: pd.Series
    production: pd.Series
    repair: pd.Series
    eol_burden: pd.Series
    sequestration: pd.Series
    circularity: pd.Series
    breakdown_gwp: Dict[str, float] = field(default_factory=dict)
    info: Dict[str, float] = field(default_factory=dict)

    @property
    def burdens(self):
        return self.materials.add(self.production, fill_value=0).add(self.repair, fill_value=0) \
            .add(self.eol_burden, fill_value=0)

    @property
    def benefits(self):
        return self.sequestration.add(self.circularity, fill_value=0)

    @property
    def net(self):
        return self.burdens.add(self.benefits, fill_value=0)


# ── Data store ────────────────────────────────────────────────────────────────
class DataStore:
    def __init__(self, data_dir, scenario="baseline"):
        self.data_dir = Path(data_dir)
        self.scenario = scenario
        df = pd.read_csv(self.data_dir / "unit_burdens.csv")
        if "scenario" in df.columns:
            available = df["scenario"].unique().tolist()
            if scenario not in available:
                raise ValueError(f"Scenario '{scenario}' not in unit_burdens.csv (have {available})")
            df = df[df["scenario"] == scenario].drop(columns="scenario")
        manual = self.data_dir / "manual_burdens.csv"
        if manual.exists():
            m = pd.read_csv(manual)
            if "scenario" in m.columns:
                m = m[m["scenario"].isin([scenario, "all"])].drop(columns="scenario")
            df = pd.concat([df, m], ignore_index=True)
        self.burdens = df
        self.categories = df["impact_category"].unique().tolist()
        self.units = df.dropna(subset=["impact_category_unit"]).drop_duplicates("impact_category") \
            .set_index("impact_category")["impact_category_unit"].to_dict()
        self.eol_constants = pd.read_csv(self.data_dir / "eol_constants.csv").set_index("material_name")
        self.benefit_params = pd.read_csv(self.data_dir / "benefits_constants.csv").set_index("material_name")
        self.product_lci = pd.read_csv(self.data_dir / "product_lci.csv") \
            if (self.data_dir / "product_lci.csv").exists() else None
        self.baseline_eol = pd.read_csv(self.data_dir / "baseline_eol.csv") \
            if (self.data_dir / "baseline_eol.csv").exists() else None
        mp = self.data_dir / "machine_params.csv"
        self.machine_params = pd.read_csv(mp) if mp.exists() else None
        # {raw_case_id: [baseline case_name, ...]} - baselines added on top of the sheet's comparison_raw_* flags
        self.extra_baselines: Dict[str, List[str]] = {}
        # {raw_case_id: [RawCase, ...]} - variants of a RAW case (e.g. scaled up), run at the same product mass
        self.raw_variants: Dict[str, List[RawCase]] = {}

    # -- lookups (same semantics as 02_model.ipynb) ---------------------------
    def unit_burden(self, name, location=None, material_source=None):
        rows = self.burdens[self.burdens["material_name"] == name]
        if location is not None:
            rows = rows[rows["location"] == location]
        if material_source is not None:
            rows = rows[rows["material_source"] == material_source]
        if rows.empty:
            raise ValueError(f"No burden data for '{name}'"
                             + (f" in location '{location}'" if location else "")
                             + (f" with source '{material_source}'" if material_source else "")
                             + f" (scenario '{self.scenario}')")
        if rows["impact_category"].duplicated().any():
            raise ValueError(f"'{name}' has duplicate impact_category rows after filtering - "
                             f"add a location/material_source filter.")
        return rows.set_index("impact_category")["score"]

    def unit_burden_by_source(self, material_name, material_source):
        rows = self.burdens[(self.burdens["material_name"] == material_name)
                            & (self.burdens["material_source"] == material_source)]
        if rows.empty:
            raise ValueError(f"No burden data for '{material_name}' sourced as '{material_source}' "
                             f"(scenario '{self.scenario}')")
        return rows.set_index("impact_category")["score"]

    def eol_const(self, material_name):
        if material_name not in self.eol_constants.index:
            raise ValueError(f"No EoL constants for '{material_name}'")
        r = self.eol_constants.loc[material_name]
        return r["allocation_factor"], r["quality_ratio"], r["lower_heating_value_MJperKgDry"]

    def benefit_param(self, material_name):
        if material_name not in self.benefit_params.index:
            raise ValueError(f"No benefit params for '{material_name}'")
        r = self.benefit_params.loc[material_name]
        return r["carbon_content_kgC_per_kgWet"], r["rotation_period_yr"]

    def material_unit_burden(self, material_name, material_source):
        """CFF acquisition formula: recycled = A*E_rec + (1-A)*E_virgin*(Qs/Qp); otherwise direct."""
        if material_source == "recycled":
            A, q, _ = self.eol_const(material_name)
            return (A * self.unit_burden_by_source(material_name, "recycled")
                    + (1 - A) * self.unit_burden_by_source(material_name, "virgin") * (q / QUALITY_RATIO_PRIMARY))
        return self.unit_burden_by_source(material_name, material_source)

    def zeros(self):
        return pd.Series(0.0, index=self.categories)

    def missing_burdens(self, case: RawCase) -> List[str]:
        """List (material, source) pairs of a RAW case with no burden data - a pre-flight check."""
        missing = []
        for bom in (case.production_bom, case.repair_bom):
            for it in bom:
                try:
                    self.material_unit_burden(it.material_name, it.material_source)
                except ValueError as e:
                    missing.append(str(e))
        for chain in (case.production_chain, case.repair_chain):
            for st in chain:
                for args in (("machine wear", None, st.machine_source), ("energy use", st.electricity_location, None)):
                    try:
                        self.unit_burden(args[0], location=args[1], material_source=args[2])
                    except ValueError as e:
                        missing.append(str(e))
        return sorted(set(missing))


# Fossil / mineral materials that can appear in a RAW BOM: no biogenic carbon, so no storage credit
NO_CARBON_STORAGE = {"Fiber glue (epoxy resin)", "Wood glue", "Mechanical fastener (screws, nails, brackets)",
                     "Cement", "Lime"}


def is_growth_eligible(material_source):
    return material_source == "virgin"


# ── RAW case lifecycle ────────────────────────────────────────────────────────
def _check_bom(bom, label):
    total = sum(i.percentage for i in bom)
    if abs(total - 100) > 0.01:
        raise ValueError(f"{label} BOM percentages sum to {total}, not 100")


def _solve_chain(ds: DataStore, chain, target_output_kg):
    """Backward-solve a process chain from the target output (02_model.ipynb logic)."""
    n = len(chain)
    required = [None] * n
    nxt = target_output_kg
    for i in range(n - 1, -1, -1):
        required[i] = nxt / (chain[i].retained_pct / 100)
        nxt = required[i]
    total = ds.zeros()
    steps = []
    for i, st in enumerate(chain):
        hrs = required[i] / st.rate_kg_per_hr
        wear_kg = st.kg_machine * (hrs / st.machine_lifetime_hrs)
        kwh = st.power_kW * hrs
        b = (ds.unit_burden("machine wear", material_source=st.machine_source) * wear_kg
             + ds.unit_burden("energy use", location=st.electricity_location) * kwh)
        total = total.add(b, fill_value=0.0)
        steps.append(dict(step_name=st.step_name, required_input_kg=required[i], process_time_hrs=hrs,
                          machine_wear_kg=wear_kg, energy_use_kwh=kwh, gwp=b[GWP]))
    return total, pd.DataFrame(steps)


def _material_burdens(ds, bom, total_input_kg):
    total = ds.zeros()
    per_item = {}
    for it in bom:
        kg = total_input_kg * it.percentage / 100
        ub = ds.material_unit_burden(it.material_name, it.material_source)
        total = total.add(ub * kg, fill_value=0.0)
        per_item[it.material_name] = per_item.get(it.material_name, 0.0) + ub[GWP] * kg
    return total, per_item


def _sequestration(ds, bom, total_kg, storage_yr):
    """(growth credit, delayed-emissions credit, per-item dict) for one BOM at one storage period."""
    growth = delayed = 0.0
    per_item = {}
    for it in bom:
        if it.material_name in NO_CARBON_STORAGE:
            continue
        kg = total_kg * it.percentage / 100
        c, rot = ds.benefit_param(it.material_name)
        if is_growth_eligible(it.material_source):
            v = c * kg * MOLAR_RATIO * lookup_gwpbio(rot, storage_yr)
            growth += v
        else:
            v = c * kg * MOLAR_RATIO * (dynamic_cf(storage_yr) - 1)
            delayed += v
        per_item[it.material_name] = per_item.get(it.material_name, 0.0) + v
    return growth, delayed, per_item


def eol_treatment(ds: DataStore, kg, eol: EolShares, A, q, LHV):
    """EoL burdens + circularity credits for `kg` of waste (02_model.ipynb cells 24 and 41).
    Returns (burden_series, credit_series, per_route_gwp dict)."""
    ub = ds.unit_burden
    compost = abs((1 - A) * eol.composted / 100 * ub("waste composting") * kg)
    rec_open = abs((1 - A) * eol.recycled_open / 100 * ub("waste recycling") * kg)
    rec_closed = abs((1 - A) * eol.recycled_closed / 100 * ub("waste recycling") * kg)
    incin = abs(eol.incinerated / 100 * ub("waste incineration") * kg)
    landfill = abs(eol.landfilled / 100 * ub("waste landfilling") * kg)
    burden = ds.zeros()
    for s in (compost, rec_open, rec_closed, incin, landfill):
        burden = burden.add(s, fill_value=0.0)

    c_compost = -(1 - A) * eol.composted / 100 * ub("avoided burden - composting") * q * kg
    c_open = -(1 - A) * eol.recycled_open / 100 * ub("avoided buden - open loop recycling") * q * kg
    c_incin = -(eol.incinerated / 100) * LHV * kg * (
        CONV_EFF_HEAT * ub("avoided burden - incineration, heat")
        + CONV_EFF_ELEC * ub("avoided burden - incineration, electricity", location=eol.disposal_location))
    credit = c_compost.add(c_open, fill_value=0.0).add(c_incin, fill_value=0.0)
    routes = {
        "Compost (EoL)": compost[GWP], "Recycle open (EoL)": rec_open[GWP],
        "Recycle closed (EoL)": rec_closed[GWP], "Incinerate (EoL)": incin[GWP],
        "Landfill (EoL)": landfill[GWP],
        "Compost credit (EoL)": c_compost[GWP], "Recycle open credit (EoL)": c_open[GWP],
        "Incinerate credit (EoL)": c_incin[GWP],
    }
    return burden, credit, routes


def run_raw_case(ds: DataStore, case: RawCase, product_kg: float, label: Optional[str] = None) -> Result:
    """Full lifecycle of a RAW case for `product_kg` of finished product."""
    _check_bom(case.production_bom, f"{case.case_id} production")
    case.eol.check(case.case_id)
    rp = case.repair
    n_rep = rp.n_repairs if rp.enabled else 0
    repair_kg = rp.material_pct_of_product / 100 * product_kg if n_rep else 0.0

    prod_proc, df_prod = _solve_chain(ds, case.production_chain, product_kg)
    input_kg = df_prod["required_input_kg"].iloc[0]
    mat, mat_items = _material_burdens(ds, case.production_bom, input_kg)

    repair_total = ds.zeros()
    rep_input_kg = 0.0
    rep_mat_items, rep_proc_gwp = {}, 0.0
    if n_rep:
        _check_bom(case.repair_bom, f"{case.case_id} repair")
        rep_proc, df_rep = _solve_chain(ds, case.repair_chain, repair_kg)
        rep_input_kg = df_rep["required_input_kg"].iloc[0]
        rep_mat, rep_mat_items = _material_burdens(ds, case.repair_bom, rep_input_kg)
        repair_total = (rep_proc + rep_mat) * n_rep
        rep_proc_gwp = rep_proc[GWP] * n_rep

    # storage periods (02_model.ipynb cell 31)
    prod_storage = rp.expected_lifetime_yr + rp.extension_per_repair_yr * n_rep
    rep_storage = [(n_rep - i + 1) * rp.extension_per_repair_yr for i in range(1, n_rep + 1)]

    growth, delayed, seq_items = _sequestration(ds, case.production_bom, input_kg, prod_storage)
    for s in rep_storage:
        g, d, items = _sequestration(ds, case.repair_bom, rep_input_kg, s)
        growth += g
        delayed += d
        for k, v in items.items():
            seq_items[k] = seq_items.get(k, 0.0) + v
    seq = ds.zeros()
    seq[GWP] = growth + delayed

    total_disposed = product_kg + repair_kg * n_rep
    A, q, LHV = ds.eol_const("RAW product")
    eol_b, eol_c, routes = eol_treatment(ds, total_disposed, case.eol, A, q, LHV)

    breakdown = {}
    for k, v in mat_items.items():
        breakdown[f"{k} (material)"] = v + rep_mat_items.get(k, 0.0) * n_rep
    for k, v in rep_mat_items.items():
        if k not in mat_items:
            breakdown[f"{k} (material)"] = v * n_rep
    for _, r in df_prod.iterrows():
        breakdown[f"{r.step_name} (production)"] = r.gwp
    if n_rep:
        breakdown["Repair processes"] = rep_proc_gwp
    breakdown.update({k: v for k, v in routes.items() if v})
    for k, v in seq_items.items():
        breakdown[f"{k} (carbon storage)"] = v

    return Result(
        label=label or case.name, materials=mat, production=prod_proc, repair=repair_total,
        eol_burden=eol_b, sequestration=seq, circularity=eol_c, breakdown_gwp=breakdown,
        info=dict(product_kg=product_kg, material_input_kg=input_kg, n_repairs=n_rep,
                  total_disposed_kg=total_disposed, storage_yr=prod_storage),
    )


# ── Baseline products ─────────────────────────────────────────────────────────
def lci_rows(ds: DataStore, case_name: str) -> pd.DataFrame:
    rows = ds.product_lci[ds.product_lci["case_name"] == case_name]
    if rows.empty:
        raise ValueError(f"'{case_name}' not in product_lci.csv")
    return rows


def spec_variable(ds: DataStore, case_name: str) -> str:
    return lci_rows(ds, case_name)["spec_var"].iloc[0]


def activity_amounts(ds: DataStore, case_name: str, spec_value: float) -> pd.DataFrame:
    """Evaluate every activity formula of a product case at the given spec value."""
    rows = lci_rows(ds, case_name).copy()
    var = rows["spec_var"].iloc[0]
    rows["amount"] = [evaluate_formula(f, {var: spec_value}) for f in rows["formula"]]
    return rows[["activity_name", "amount", "activity_unit", "formula"]].reset_index(drop=True)


DEFAULT_TREATMENT = {
    "composted": "waste composting", "recycled_open": "waste recycling", "recycled_closed": "waste recycling",
    "incinerated": "waste incineration", "landfilled": "waste landfilling",
}


def run_baseline(ds: DataStore, case_name: str, spec_value: float, label: Optional[str] = None,
                 disposal_location: str = "NL") -> Result:
    """Cradle-to-gate (unit burden x amount per activity) + simple EoL from baseline_eol.csv.

    baseline_eol.csv (one row per activity x route): activity_name, kg_per_unit, route (one of
    composted / recycled_open / recycled_closed / incinerated / landfilled), share_pct,
    treatment_burden_name (blank = default RAW waste burden for the route, 'none' = no burden),
    lhv_MJ_per_kg (incineration energy credit), carbon_material + storage_yr (biogenic storage).
    EoL follows the RAW conventions of eol_treatment(): (1-A) on composting/recycling, energy credit
    on incineration (LHV x [heat + electricity]); no credit for open-loop recycling of baselines."""
    acts = activity_amounts(ds, case_name, spec_value)
    A, _, _ = ds.eol_const("RAW product")
    mat, eol_b, circ, seq = ds.zeros(), ds.zeros(), ds.zeros(), ds.zeros()
    breakdown, info = {}, {}
    for _, a in acts.iterrows():
        b = ds.unit_burden(a.activity_name) * a.amount
        mat = mat.add(b, fill_value=0.0)
        breakdown[f"{a.activity_name} (material)"] = b[GWP]
        info[f"{a.activity_name} [{a.activity_unit}]"] = a.amount
        if ds.baseline_eol is None:
            continue
        rows = ds.baseline_eol[ds.baseline_eol["activity_name"] == a.activity_name]
        if rows.empty:
            continue
        if abs(rows["share_pct"].sum() - 100) > 0.01:
            raise ValueError(f"baseline_eol shares for '{a.activity_name}' sum to {rows['share_pct'].sum()}")
        for _, e in rows.iterrows():
            kg = a.amount * e.kg_per_unit * e.share_pct / 100
            name = e.treatment_burden_name if isinstance(e.treatment_burden_name, str) else DEFAULT_TREATMENT[e.route]
            if name != "none":
                cff = (1 - A) if e.route in ("composted", "recycled_open", "recycled_closed") else 1.0
                t = (ds.unit_burden(name) * kg * cff).abs()
                eol_b = eol_b.add(t, fill_value=0.0)
                breakdown[f"{a.activity_name}: {e.route} (EoL)"] = t[GWP]
            if e.route == "incinerated" and pd.notna(e.get("lhv_MJ_per_kg")):
                c = -(kg * e.lhv_MJ_per_kg) * (
                    CONV_EFF_HEAT * ds.unit_burden("avoided burden - incineration, heat")
                    + CONV_EFF_ELEC * ds.unit_burden("avoided burden - incineration, electricity",
                                                     location=disposal_location))
                circ = circ.add(c, fill_value=0.0)
                breakdown[f"{a.activity_name}: incineration credit (EoL)"] = c[GWP]
        cm = rows["carbon_material"].dropna()
        if len(cm):
            storage = float(rows["storage_yr"].dropna().iloc[0])
            c_frac, rot = ds.benefit_param(cm.iloc[0])
            # virgin biobased baseline: growth credit, same rule as RAW virgin materials
            v = c_frac * a.amount * rows["kg_per_unit"].iloc[0] * MOLAR_RATIO * lookup_gwpbio(rot, storage)
            seq[GWP] += v
            breakdown[f"{a.activity_name} (carbon storage)"] = v

    return Result(label=label or case_name, materials=mat, production=ds.zeros(), repair=ds.zeros(),
                  eol_burden=eol_b, sequestration=seq, circularity=circ, breakdown_gwp=breakdown, info=info)


# ── Comparison ────────────────────────────────────────────────────────────────
def baselines_for(ds: DataStore, raw_case_id: str) -> List[str]:
    """Baseline case_names for a RAW case: the comparison_raw_* flags plus ds.extra_baselines, ordered bio-based then fossil-based."""
    col = f"comparison_{raw_case_id}"
    if col not in ds.product_lci.columns:
        raise ValueError(f"No column '{col}' in product_lci.csv")
    flagged = ds.product_lci[ds.product_lci[col].astype(str).str.upper() == "TRUE"]
    names = list(dict.fromkeys(flagged["case_name"]))
    for extra in ds.extra_baselines.get(raw_case_id, []):
        lci_rows(ds, extra)                      # fail early on a misspelled case name
        if extra not in names:
            names.append(extra)
    # consistent order in every chart/table: bio-based conventional first, then fossil-based
    rank = {"conventional bio-based": 0, "conventional fossil-based": 1}
    case_type = ds.product_lci.drop_duplicates("case_name").set_index("case_name")["case_type"]
    return sorted(names, key=lambda n: rank.get(case_type.get(n), 2))   # stable: keeps sheet order within a type


def compare(ds: DataStore, raw_cases: Dict[str, RawCase], raw_case_id: str, spec_value: float):
    """Run a RAW case and its flagged baselines for one spec value. Returns {label: Result}.
    A baseline whose burden data is missing (e.g. the CFW beam before its manual numbers exist)
    is skipped with a printed notice instead of aborting the comparison."""
    case = raw_cases[raw_case_id]
    raw_kg = float(activity_amounts(ds, raw_case_id, spec_value)["amount"].iloc[0])
    results = {case.name: run_raw_case(ds, case, raw_kg, label=case.name)}
    results[case.name].info["spec_value"] = spec_value
    for variant in ds.raw_variants.get(raw_case_id, []):
        results[variant.name] = run_raw_case(ds, variant, raw_kg, label=variant.name)
    for b in baselines_for(ds, raw_case_id):
        try:
            results[b] = run_baseline(ds, b, spec_value, label=b)
        except ValueError as e:
            print(f"NOTICE: baseline '{b}' skipped - {e}")
    return results
