"""
Lifecycle model: burdens and benefits of a RAW case or a baseline product, per impact category.

Formulas follow the earlier notebook model 02_model.ipynb (git tag v0.1-product-comparison): circular footprint formula for recycled input and end-of-life, backward-solved
process chains, GWP_bio and dynamic-CF carbon storage credits). Every number comes from the sheet (via `Inputs`),
the background data, or a case resolved from the parameter table - none is defined here.

Results are per product spec and scaled to the reference service life: each product's burdens and benefits are
multiplied by reference_service_life / product_service_life.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .background import Background
from .cases import BaselineCase, BOMItem, ProcessStep, RawCase
from .inputs import Inputs

GWP = "climate change"


@dataclass
class Result:
    """Vectors over the impact categories of `categories`."""
    label: str
    categories: List[str]
    materials: np.ndarray
    production: np.ndarray
    repair: np.ndarray
    eol_burden: np.ndarray
    sequestration: np.ndarray
    circularity: np.ndarray
    info: Dict[str, float] = field(default_factory=dict)

    @property
    def burdens(self) -> np.ndarray:
        return self.materials + self.production + self.repair + self.eol_burden

    @property
    def benefits(self) -> np.ndarray:
        return self.sequestration + self.circularity

    @property
    def net(self) -> np.ndarray:
        return self.burdens + self.benefits


class Model:
    def __init__(self, inputs: Inputs, background: Background, constant_overrides: Optional[dict] = None):
        self.inp, self.bg = inputs, background
        c = dict(inputs.constants)
        c.update(constant_overrides or {})            # e.g. mj_per_kwh = 1 reproduces the units of 02_model.ipynb
        self.c = c
        self.n = len(background.categories)
        self.gwp = background.gwp_index
        self.rsl = inputs.reference_service_life
        row = inputs.eol_constants.loc[c["raw_product_eol_row"]]
        self.A, self.q, self.lhv = float(row["allocation_factor"]), float(row["quality_ratio"]), float(row["lower_heating_value_MJperKgDry"])
        self.eff_heat, self.eff_elec = float(row["conversionEfficiency_heat"]), float(row["conversionEfficiency_electricity"])
        g = inputs.gwpbio.set_index("rotation_period_yr")
        cols = [k for k in g.columns if k.startswith("storage_")]
        self._gw_storage = [int(k.split("_")[1].rstrip("yr")) for k in cols]
        self._gw = {int(r): g.loc[r, cols].astype(float).tolist() for r in g.index}
        b = inputs.bern.set_index("term")
        self._bern_a = [float(b.loc[t, "coefficient_a"]) for t in ("a0", "a1", "a2", "a3")]
        self._bern_tau = [None] + [float(b.loc[t, "time_constant_tau_yr"]) for t in ("a1", "a2", "a3")]
        self._setup = {(r.activity_name, r.route): r for r in inputs.baseline_eol_setup.itertuples()}
        self.zero = np.zeros(self.n)

    # ── carbon storage ───────────────────────────────────────────────────────────────────
    def gwpbio(self, rotation_yr: float, storage_yr: float) -> float:
        """GWP_bio factor (Guest et al. 2012), interpolated between the storage columns of the sheet table."""
        rot = min(self._gw, key=lambda r: abs(r - rotation_yr))
        row, grid = self._gw[rot], self._gw_storage
        storage_yr = max(grid[0], min(storage_yr, grid[-1]))
        return float(np.interp(storage_yr, grid, row))

    def _agwp(self, t: float) -> float:
        a, tau = self._bern_a, self._bern_tau
        return a[0] * t + sum(a[i] * tau[i] * (1 - np.exp(-t / tau[i])) for i in (1, 2, 3))

    def dynamic_cf(self, storage_yr: float) -> float:
        """Dynamic characterisation factor (Levasseur et al. 2010) of carbon delayed by storage_yr years."""
        T = float(self.c["time_horizon_yr"])
        return self._agwp(T - storage_yr) / self._agwp(T)

    def _storage_credit(self, material: str, source: str, kg: float, storage_yr: float) -> float:
        cc, rot = self.bg.carbon(material)
        if cc == 0 or kg == 0:
            return 0.0
        molar = float(self.c["co2_c_molar_ratio"])
        if source == "virgin":                          # growth attributable to this product
            return cc * kg * molar * self.gwpbio(rot, storage_yr)
        return cc * kg * molar * (self.dynamic_cf(storage_yr) - 1)   # diverted / waste flows: delayed emissions

    # ── material and process burdens ──────────────────────────────────────────────────────
    def material_unit_burden(self, name: str, source: str, it=None) -> np.ndarray:
        """CFF acquisition formula: recycled = A*E_recycled + (1-A)*E_virgin*(Qs/Qp); otherwise direct."""
        if source == "recycled":
            e = self.inp.eol_constants.loc[name]
            A, q = float(e["allocation_factor"]), float(e["quality_ratio"])
            return (A * self.bg.get(name, source="recycled", iteration=it)
                    + (1 - A) * self.bg.get(name, source="virgin", iteration=it) * (q / float(self.c["quality_ratio_primary"])))
        return self.bg.get(name, source=source, iteration=it)

    def _materials(self, bom: List[BOMItem], input_kg: float, it) -> np.ndarray:
        tot = self.zero.copy()
        for x in bom:
            tot += self.material_unit_burden(x.material_name, x.material_source, it) * input_kg * x.percentage / 100
        return tot

    def _chain(self, chain: List[ProcessStep], target_kg: float, it):
        """Solve a chain backward from the target output; returns (burden, required input of the first step)."""
        need = [0.0] * len(chain)
        nxt = target_kg
        for i in range(len(chain) - 1, -1, -1):
            need[i] = nxt / (chain[i].retained_pct / 100)
            nxt = need[i]
        tot = self.zero.copy()
        for st, kg_in in zip(chain, need):
            hrs = kg_in / st.rate_kg_per_hr
            wear = st.kg_machine * hrs / st.machine_lifetime_hrs
            tot += (self.bg.get(self.c["machine_wear_activity"], source=st.machine_source, iteration=it) * wear
                    + self.bg.get(self.c["electricity_activity"], location=st.electricity_location, iteration=it) * st.power_kW * hrs)
        return tot, (need[0] if need else target_kg)

    # ── end of life ────────────────────────────────────────────────────────────────────────
    def _route_burden(self, route: str, kg: float, share: float, treatment: Optional[str], it) -> np.ndarray:
        r = self.inp.eol_routes.loc[route]
        name = treatment or r["treatment_activity"]
        if name == "none" or share == 0 or kg == 0:
            return self.zero
        cff = (1 - self.A) if r["cff_factor_applies"] in (True, "True", "TRUE") else 1.0
        return np.abs(self.bg.get(name, iteration=it) * kg * share / 100 * cff)

    def _energy_credit(self, kg: float, share: float, lhv: float, location: str, it) -> np.ndarray:
        r = self.inp.eol_routes.loc["incinerated"]
        heat = self.bg.get(r["energy_credit_heat_activity"], iteration=it)
        elec = self.bg.get(r["energy_credit_electricity_activity"], location=location, iteration=it)
        # heat is per MJ, electricity per kWh: convert the electricity share of the fuel energy from MJ to kWh
        return -(share / 100) * lhv * kg * (self.eff_heat * heat + self.eff_elec * elec / float(self.c["mj_per_kwh"]))

    def _material_credit(self, route: str, kg: float, share: float, it) -> np.ndarray:
        name = self.inp.eol_routes.loc[route, "material_credit_activity"]
        if not name or share == 0:
            return self.zero
        return -(1 - self.A) * share / 100 * self.bg.get(name, iteration=it) * self.q * kg

    # ── RAW case ───────────────────────────────────────────────────────────────────────────
    def run_raw(self, case: RawCase, product_kg: float, iteration=None, label: Optional[str] = None) -> Result:
        it = iteration
        rp = case.repair
        n_rep = rp.n_repairs
        repair_kg = rp.material_pct_of_product / 100 * product_kg if n_rep > 0 else 0.0
        life = case.service_life_yr

        proc, input_kg = self._chain(case.production_chain, product_kg, it)
        mat = self._materials(case.production_bom, input_kg, it)
        rep = self.zero.copy()
        seq_kg = [(x, input_kg * x.percentage / 100, life) for x in case.production_bom]
        if n_rep > 0:
            rp_proc, rep_input = self._chain(case.repair_chain, repair_kg, it)
            rep = (rp_proc + self._materials(case.repair_bom, rep_input, it)) * n_rep
            for i in range(1, n_rep + 1):                # event i is stored (n - i + 1) x extension years
                storage = (n_rep - i + 1) * rp.extension_per_repair_yr
                seq_kg += [(x, rep_input * x.percentage / 100, storage) for x in case.repair_bom]
        seq = self.zero.copy()
        seq[self.gwp] = sum(self._storage_credit(x.material_name, x.material_source, kg, st) for x, kg, st in seq_kg)

        kg_waste = product_kg + repair_kg * n_rep
        e = case.eol
        shares = {"composted": e.composted, "recycled_open": e.recycled_open, "recycled_closed": e.recycled_closed,
                  "incinerated": e.incinerated, "landfilled": e.landfilled}
        eol_b, circ = self.zero.copy(), self.zero.copy()
        for route, s in shares.items():
            eol_b = eol_b + self._route_burden(route, kg_waste, s, None, it)
            circ = circ + self._material_credit(route, kg_waste, s, it)
        circ = circ + self._energy_credit(kg_waste, e.incinerated, self.lhv, e.disposal_location, it)

        f = self.rsl / life if life > 0 else 1.0
        return Result(label or case.name, self.bg.categories, mat * f, proc * f, rep * f, eol_b * f, seq * f, circ * f,
                      info=dict(product_kg=product_kg, service_life_yr=life, scaling=f, material_input_kg=input_kg))

    # ── baseline product ────────────────────────────────────────────────────────────────────
    def run_baseline(self, case: BaselineCase, activities: List[tuple], iteration=None,
                     label: Optional[str] = None) -> Result:
        """activities: [(activity name, amount, unit)] from the products tab. Cradle-to-gate burden of each
        activity plus end of life from the shares on the sheet (mapping in baseline_eol_setup)."""
        it = iteration
        mat, eol_b, circ, seq = self.zero.copy(), self.zero.copy(), self.zero.copy(), self.zero.copy()
        for name, amount, _unit in activities:
            mat = mat + self.bg.get(name, iteration=it) * amount
            shares = case.eol_shares.get(name)
            if not shares:
                continue
            carbon_material = None
            for route, share in shares.items():
                st = self._setup[(name, route)]
                kg = amount * float(st.kg_per_unit)
                treatment = st.treatment_burden_name if isinstance(st.treatment_burden_name, str) else None
                eol_b = eol_b + self._route_burden(route, kg, share, treatment, it)
                if route == "incinerated" and share > 0 and st.lhv_MJ_per_kg == st.lhv_MJ_per_kg:
                    circ = circ + self._energy_credit(kg, share, float(st.lhv_MJ_per_kg), case.disposal_location, it)
                if isinstance(st.carbon_material, str):
                    carbon_material = (st.carbon_material, amount * float(st.kg_per_unit))
            if carbon_material:                          # biogenic storage: virgin bio-based baseline, stored for its service life
                seq[self.gwp] += self._storage_credit(carbon_material[0], "virgin", carbon_material[1], case.service_life_yr)
        f = self.rsl / case.service_life_yr if case.service_life_yr > 0 else 1.0
        return Result(label or case.case_name, self.bg.categories, mat * f, self.zero, self.zero, eol_b * f, seq * f, circ * f,
                      info=dict(service_life_yr=case.service_life_yr, scaling=f))
