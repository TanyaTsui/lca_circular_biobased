"""
Builds the background data (data/background/) from the sheet with Brightway + ecoinvent (+ premise).
Needs an ecoinvent licence and the Brightway project; readers who only want to reproduce the results can use the
committed output of this step. Brightway is imported inside the functions so the rest of the package does not need it.

Inputs (sheet tabs): unit_burdens_dataSources (activities -> ecoinvent datasets), benefits_constants_dataSources
(carbon content and rotation period), scenarios (premise scenarios), constants (transport distance),
study_setup (ecoinvent version, impact method), impact_categories (units).
Outputs: unit_burdens.csv, materials_carbon.csv, optional unit_burden_samples_<scenario>.npz.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

EU_LOOKUP = "lookup: all european countries"
ROAD_TRANSPORT = "road transport"


def normalise_unit(raw) -> str:
    """'1 kg ' -> 'kg', '1 ton km' -> 'ton km'."""
    return re.sub(r"^1\s*", "", str(raw)).strip()


def read_sources(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = tables["unit_burdens_dataSources"].copy()
    df = df[df["unit"].notna()].copy()                    # section header rows have no unit
    for c in ("activity_name", "unit", "material_source", "ecoinventDataset_name", "geographicalCoverage",
              "referenceProduct", "alternative_data_source"):
        df[c] = df[c].where(df[c].notna(), None)
        df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)
        df[c] = df[c].map(lambda v: None if v in ("n/a", "") else v)
    df["material_unit"] = df["unit"].map(normalise_unit)
    return df.reset_index(drop=True)


def scenario_db_name(model: str, pathway: str, year) -> str:
    return f"premise-{model}-{str(pathway).lower()}-{int(year)}"


class Extractor:
    """Unit burdens of activities in one Brightway database, for all impact categories."""

    def __init__(self, bd, bc, db_name: str, baseline_db_name: str, methods: list, tkm_per_kg: float,
                 background_dir: Path, europe: Optional[List[str]] = None):
        self.bd, self.bc = bd, bc
        self.db, self.baseline = bd.Database(db_name), bd.Database(baseline_db_name)
        self.methods, self.tkm_per_kg, self.dir = methods, tkm_per_kg, Path(background_dir)
        self.europe = europe or []
        self._index: Dict[str, dict] = {}
        self._lca = None
        self._cache: Dict[tuple, Optional[dict]] = {}

    # ── lookup ───────────────────────────────────────────────────────────────────────────
    def _idx(self, db):
        if db.name not in self._index:
            self._index[db.name] = {(a["name"], a["location"], a.get("reference product")): a for a in db}
        return self._index[db.name]

    def find(self, name, location, ref_product=None, db=None):
        idx = self._idx(db or self.db)
        if ref_product is not None:
            return idx[(name, location, ref_product)]
        hits = [a for (n, l, _), a in idx.items() if n == name and l == location]
        if not hits:
            raise KeyError((name, location))
        return hits[0]

    def kg_factor(self, act, name, location, ref_product) -> Optional[float]:
        """kg per reference unit: 1 for kg datasets, else the 'wet mass' property (premise datasets can lose it, then the
        same dataset of the baseline database is used - the conversion does not depend on the scenario)."""
        for a in (act, None):
            if a is None:
                try:
                    a = self.find(name, location, ref_product, db=self.baseline)
                except KeyError:
                    return None
            if (a.get("unit") or "").lower() == "kilogram":
                return 1.0
            for exc in a.production():
                wet = exc.get("properties", {}).get("wet mass", {}).get("amount")
                if wet:
                    return wet
        return None

    # ── scoring ──────────────────────────────────────────────────────────────────────────
    def _scores(self, act) -> Dict[str, float]:
        if self._lca is None:
            self._lca = self.bc.LCA({act.id: 1}, self.methods[0])
            self._lca.lci()
        else:
            self._lca.redo_lci({act.id: 1})
        out = {}
        for m in self.methods:
            self._lca.switch_method(m)
            self._lca.lcia()
            out[m[2]] = float(self._lca.score)
        return out

    def scores(self, name, location, ref_product, unit) -> Optional[Dict[str, float]]:
        key = (name, location, ref_product, unit)
        if key not in self._cache:
            try:
                act = self.find(name, location, ref_product)
            except KeyError:
                self._cache[key] = None
                return None
            factor = self.kg_factor(act, name, location, ref_product) if unit == "kg" else None
            if unit == "kg" and factor is None:
                print(f"  WARNING '{name}' | {location}: no kg conversion available - skipped")
                self._cache[key] = None
                return None
            s = self._scores(act)
            self._cache[key] = {k: v / factor for k, v in s.items()} if factor else s
        return self._cache[key]

    # ── one row of unit_burdens_dataSources ────────────────────────────────────────────────
    def rows_for(self, row, transport: dict, units: Dict[str, str], lca_database: str, method_label: str):
        base = dict(material_name=row["activity_name"], material_unit=row["material_unit"],
                    material_source=row["material_source"], lca_database=lca_database, lca_method=method_label)

        def rows(location, scores, database=lca_database):
            return [dict(base, location=location, impact_category=c, impact_category_unit=units.get(c, ""),
                         score=v, lca_database=database) for c, v in scores.items()]

        alt = row["alternative_data_source"]
        if row["ecoinventDataset_name"]:
            locs = self.europe if row["geographicalCoverage"].lower() == EU_LOOKUP else [row["geographicalCoverage"]]
            out, errors = [], []
            for loc in locs:
                s = self.scores(row["ecoinventDataset_name"], loc, row["referenceProduct"], row["material_unit"])
                if s is None:
                    errors.append(f"{row['activity_name']} | {loc}")
                    continue
                out += rows(loc, s)
            return out, errors
        if alt == ROAD_TRANSPORT:
            s = {c: v * self.tkm_per_kg for c, v in transport.items()}
            return rows(row["geographicalCoverage"], s), []
        if alt:
            ext = self.dir / f"external_{alt}.csv"
            if not ext.exists():
                return [], [f"{row['activity_name']}: {ext.name} not found (alternative data source '{alt}')"]
            df = pd.read_csv(ext)
            return rows(row["geographicalCoverage"], dict(zip(df["impact_category"], df["score"])), database=alt), []
        return [], [f"{row['activity_name']}: no ecoinvent dataset and no alternative data source"]


def european_locations(bd, db_name: str) -> List[str]:
    """Countries of the electricity markets aggregated by ecoinvent's European market groups."""
    db = bd.Database(db_name)
    locs = set()
    for grp_loc in ("RER", "Europe without Switzerland"):
        grp = next(a for a in db if a["name"] == "market group for electricity, low voltage" and a["location"] == grp_loc)
        locs |= {e.input["location"] for e in grp.technosphere() if e.input.get("name") == "market for electricity, low voltage"}
    return sorted(locs)


def extract_scenario(bd, bc, sources: pd.DataFrame, scenario_id: str, db_name: str, baseline_db: str, methods: list,
                     units: Dict[str, str], tkm_per_kg: float, background_dir, method_label: str, europe: List[str],
                     progress_csv: Optional[Path] = None) -> pd.DataFrame:
    ex = Extractor(bd, bc, db_name, baseline_db, methods, tkm_per_kg, background_dir, europe)
    # road transport reference: 1 tkm scores, scaled by tkm_per_kg for the collection distance
    trow = sources[sources["activity_name"] == "Road transport"].iloc[0]
    t_act = ex.find(trow["ecoinventDataset_name"], trow["geographicalCoverage"], trow["referenceProduct"])
    transport = ex._scores(t_act)
    all_rows, errors = [], []
    for i, row in sources.iterrows():
        print(f"[{scenario_id}] {i + 1}/{len(sources)} {row['activity_name']} ({row['material_source'] or '-'})")
        r, e = ex.rows_for(row, transport, units, db_name, method_label)
        all_rows += r
        errors += e
        if progress_csv is not None:
            pd.DataFrame(all_rows).assign(scenario=scenario_id).to_csv(progress_csv, index=False)
    if errors:
        print(f"[{scenario_id}] {len(errors)} unresolved: {errors}")
    return pd.DataFrame(all_rows).assign(scenario=scenario_id)


def carbon_content(bd, benefits: pd.DataFrame, baseline_db: str) -> pd.DataFrame:
    """Carbon content per kg wet material and rotation period, from the sheet tab benefits_constants_dataSources:
    a number on the sheet is used as is; 'to extract w/ bw' = carbon content, non-fossil x dry mass / wet mass of
    the ecoinvent dataset."""
    db = bd.Database(baseline_db)
    idx = {(a["name"], a["location"], a.get("reference product")): a for a in db}
    rows = []
    for r in benefits[benefits["unit"].notna()].itertuples():
        cc = r.carbonContent_dryWeight_kg
        if isinstance(cc, str) and cc.strip().lower().startswith("to extract"):
            act = idx[(r.ecoinventDataset_name.strip(), str(r.geographicalCoverage).strip(), r.referenceProduct.strip())]
            props = next(iter(act.production())).get("properties", {})
            cc = props["carbon content, non-fossil"]["amount"] * props["dry mass"]["amount"] / props["wet mass"]["amount"]
        rot = pd.to_numeric(r.rotationPeriod_yr, errors="coerce")
        rows.append(dict(material_name=r.material_name, carbon_content_kgC_per_kgWet=float(cc),
                         rotation_period_yr=None if pd.isna(rot) else float(rot)))
    return pd.DataFrame(rows)


def resolve_targets(ex: Extractor, sources: pd.DataFrame, transport_act, mc_locations: List[str]) -> dict:
    """{(activity name, location, source): (activity id, multiplier)} - or (None, constant scores) for external data -
    for every unit burden the model can use, mirroring Extractor.rows_for. Electricity-like rows that look up all
    European countries are restricted to `mc_locations`."""
    out = {}
    for _, row in sources.iterrows():
        alt, src = row["alternative_data_source"], row["material_source"] or ""
        if row["ecoinventDataset_name"]:
            locs = ([l for l in ex.europe if l in mc_locations] if row["geographicalCoverage"].lower() == EU_LOOKUP
                    else [row["geographicalCoverage"]])
            for loc in locs:
                act = ex.find(row["ecoinventDataset_name"], loc, row["referenceProduct"])
                f = ex.kg_factor(act, row["ecoinventDataset_name"], loc, row["referenceProduct"]) if row["material_unit"] == "kg" else None
                out[(row["activity_name"], loc, src)] = (act.id, 1.0 / f if f else 1.0)
        elif alt == ROAD_TRANSPORT:
            out[(row["activity_name"], row["geographicalCoverage"] or "", src)] = (transport_act.id, ex.tkm_per_kg)
    return out


def sample_background(bd, bc, sources: pd.DataFrame, db_name: str, baseline_db: str, methods: list, tkm_per_kg: float,
                      background_dir, europe: List[str], mc_locations: List[str], n_iter: int, seed: int) -> Dict[str, np.ndarray]:
    """Monte Carlo samples of the unit burdens: per iteration the technosphere and biosphere matrices are sampled
    from ecoinvent's uncertainty data, factorised once, and every needed activity is solved for that same draw
    (so shared background processes are correlated between materials). Characterisation factors are not sampled.
    Returns {"name|location|source": (n_iter, n_categories)} in the order of `methods`."""
    from scipy.sparse.linalg import spsolve

    ex = Extractor(bd, bc, db_name, baseline_db, methods, tkm_per_kg, background_dir, europe)
    trow = sources[sources["activity_name"] == "Road transport"].iloc[0]
    t_act = ex.find(trow["ecoinventDataset_name"], trow["geographicalCoverage"], trow["referenceProduct"])
    targets = resolve_targets(ex, sources, t_act, mc_locations)
    keys = list(targets)
    ids = sorted({targets[k][0] for k in keys})

    lca = bc.LCA({ids[0]: 1}, methods[0], use_distributions=True, seed_override=seed)
    lca.load_lci_data()                                  # matrices only: no linear system is solved by next(lca)
    cf = []
    for m in methods:                                    # characterisation factors (means), aligned with the biosphere rows
        lca.switch_method(m)
        cf.append(lca.characterization_matrix.diagonal())
    CF = np.array(cf)                                    # (n_categories, n_biosphere)
    n_tech = lca.technosphere_matrix.shape[0]
    D = np.zeros((n_tech, len(ids)))                     # one unit-demand column per activity
    for j, i in enumerate(ids):
        D[lca.dicts.activity[i], j] = 1.0
    pos = {i: j for j, i in enumerate(ids)}
    out = {"|".join(k): np.zeros((n_iter, len(methods))) for k in keys}
    for it in range(n_iter):
        next(lca)                                        # new sample of the technosphere and biosphere matrices
        X = spsolve(lca.technosphere_matrix, D)  # CSR: ~10x faster than CSC here; one factorisation, all activities solved on the same draw
        scores = CF @ (lca.biosphere_matrix @ X)         # (n_categories, n_activities)
        for k in keys:
            aid, mult = targets[k]
            out["|".join(k)][it] = scores[:, pos[aid]] * mult
        if (it + 1) % 10 == 0:
            print(f"  {db_name}: {it + 1}/{n_iter} iterations", flush=True)
    return out
