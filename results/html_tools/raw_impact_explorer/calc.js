// ============================================================================
// calc.js — JS port of raw_lca/model.py (Model.run_raw) for one RAW case.
// Function names follow model.py so the two can be read side by side. Every
// number comes from RAW_DATA (data.js) or the case inputs (presets.js) — none
// is defined here. check_calc.js compares this file with the Python results
// baked into RAW_REFERENCE by build_data.py.
//
// Inputs are the editable objects of presets.js: every number is
// { v, min, max, dist, up?, comment, sheet }; the model uses `.v`.
// ============================================================================

const CATEGORIES = RAW_DATA.categories;
const N_CAT = CATEGORIES.length;
const GWP = CATEGORIES.indexOf("climate change");
const C = RAW_DATA.constants;
const ROUTES = ["composted", "recycled_open", "recycled_closed", "incinerated", "landfilled"];

// ---- vectors over the impact categories ------------------------------------
function zero() { return new Array(N_CAT).fill(0); }
function add(a, b, s = 1) { const o = a.slice(); for (let i = 0; i < N_CAT; i++) o[i] += s * b[i]; return o; }
function scale(a, s) { return a.map(x => x * s); }
function lerp(a, b, t) { return a + (b - a) * t; }

// ---- background: Background.get, blended today -> 2050 ---------------------
// `bgT` in [0, 1]: 0 = today's background, 1 = the 2050 scenario; in between the unit
// burdens are linearly interpolated (an exploration device, not a modelled trajectory).
const _byName = {};
for (const key of Object.keys(RAW_DATA.burdens[RAW_DATA.scenarios.today])) {
  const [name, loc, src] = key.split("|");
  (_byName[name] = _byName[name] || []).push({ key, loc, src });
}
const _keyCache = new Map();
function burdenKey(name, location, source) {
  const ck = name + "|" + (location || "") + "|" + (source || "");
  if (_keyCache.has(ck)) return _keyCache.get(ck);
  const cands = (_byName[name] || []).filter(k => (!location || k.loc === location) && (!source || k.src === source));
  if (cands.length !== 1) {
    throw new Error(cands.length ? `'${name}' is ambiguous - give a location or source`
      : `No burden data for '${name}'${location ? " in " + location : ""}${source ? " as " + source : ""}`);
  }
  _keyCache.set(ck, cands[0].key);
  return cands[0].key;
}
const _blendCache = new Map();
function get(name, opts, bgT) {
  const key = burdenKey(name, opts && opts.location, opts && opts.source);
  const today = RAW_DATA.burdens[RAW_DATA.scenarios.today][key];
  if (!bgT) return today;
  const future = RAW_DATA.burdens[RAW_DATA.scenarios.future][key];
  if (bgT >= 1) return future;
  const ck = key + "@" + bgT;
  if (!_blendCache.has(ck)) {
    if (_blendCache.size > 5000) _blendCache.clear();
    _blendCache.set(ck, today.map((x, i) => lerp(x, future[i], bgT)));
  }
  return _blendCache.get(ck);
}
function carbon(material) {
  const c = RAW_DATA.carbon[material];
  return c ? c : { C: 0, rot: 0 };   // Python raises for a material without carbon data; the tool counts it as 0
}
function eolConstants(name) {
  const e = RAW_DATA.eolConstants[name];
  if (!e) throw new Error(`No EoL_constants row for '${name}'`);
  return e;
}

// ---- carbon storage ----------------------------------------------------------
function interp(x, xs, ys) {
  if (x <= xs[0]) return ys[0];
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]) return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
  }
  return ys[ys.length - 1];
}
function gwpbio(rotationYr, storageYr) {
  const g = RAW_DATA.gwpbio;
  let best = 0;
  for (let i = 1; i < g.rotations.length; i++) {
    if (Math.abs(g.rotations[i] - rotationYr) < Math.abs(g.rotations[best] - rotationYr)) best = i;
  }
  return interp(storageYr, g.storage, g.table[best]);
}
function agwp(t) {
  const { a, tau } = RAW_DATA.bern;
  let s = a[0] * t;
  for (let i = 1; i <= 3; i++) s += a[i] * tau[i] * (1 - Math.exp(-t / tau[i]));
  return s;
}
function dynamicCf(storageYr) {
  const T = Number(C.time_horizon_yr);
  return agwp(T - storageYr) / agwp(T);
}
function storageCredit(material, source, kg, storageYr) {
  const { C: cc, rot } = carbon(material);
  if (cc === 0 || kg === 0) return 0;
  const molar = Number(C.co2_c_molar_ratio);
  if (source === "virgin") return cc * kg * molar * gwpbio(rot, storageYr);   // growth attributable to this product
  return cc * kg * molar * (dynamicCf(storageYr) - 1);                       // diverted / waste flows: delayed emissions
}

// ---- material and process burdens ---------------------------------------------
function materialUnitBurden(name, source, bgT) {
  if (source === "recycled") {   // CFF: A*E_recycled + (1-A)*E_virgin*(Qs/Qp)
    const { A, Q } = eolConstants(name);
    return add(scale(get(name, { source: "recycled" }, bgT), A),
      get(name, { source: "virgin" }, bgT), (1 - A) * (Q / Number(C.quality_ratio_primary)));
  }
  return get(name, { source }, bgT);
}
function materials(bom, inputKg, bgT) {
  let tot = zero();
  const items = bom.map(x => {
    const kg = inputKg * x.pct / 100;
    const burden = scale(materialUnitBurden(x.material, x.source, bgT), kg);
    tot = add(tot, burden);
    return { material: x.material, source: x.source, kg, burden };
  });
  return { total: tot, items };
}
// Solve a chain backward from the target output; returns the burden and the required input of the first step.
function chain(steps, targetKg, location, bgT) {
  const need = new Array(steps.length);
  let nxt = targetKg;
  for (let i = steps.length - 1; i >= 0; i--) { need[i] = nxt / (steps[i].yieldPct / 100); nxt = need[i]; }
  let tot = zero();
  const out = steps.map((st, i) => {
    const hrs = need[i] / st.rateKgHr;
    const wear = st.kgMachine * hrs / st.lifetimeHrs;
    const kwh = st.powerKW * hrs;
    const burden = add(scale(get(C.machine_wear_activity, { source: st.machineSource }, bgT), wear),
      get(C.electricity_activity, { location }, bgT), kwh);
    tot = add(tot, burden);
    return { name: st.name, inputKg: need[i], hours: hrs, wearKg: wear, kwh, burden };
  });
  return { total: tot, steps: out, inputKg: steps.length ? need[0] : targetKg };
}

// ---- end of life -------------------------------------------------------------------
function routeBurden(route, kg, share, A, bgT) {
  const r = RAW_DATA.eolRoutes[route];
  if (!r.treatment || r.treatment === "none" || share === 0 || kg === 0) return zero();
  const cff = r.cff ? (1 - A) : 1;
  return get(r.treatment, {}, bgT).map(x => Math.abs(x * kg * share / 100 * cff));
}
function energyCredit(kg, share, lhv, location, effHeat, effElec, bgT) {
  const r = RAW_DATA.eolRoutes.incinerated;
  const heat = get(r.heat, {}, bgT), elec = get(r.elec, { location }, bgT);
  const f = -(share / 100) * lhv * kg;
  // heat is per MJ, electricity per kWh: convert the electricity share of the fuel energy from MJ to kWh
  return heat.map((h, i) => f * (effHeat * h + effElec * elec[i] / Number(C.mj_per_kwh)));
}
function materialCredit(route, kg, share, A, Q, bgT) {
  const name = RAW_DATA.eolRoutes[route].credit;
  if (!name || share === 0) return zero();
  return scale(get(name, {}, bgT), -(1 - A) * share / 100 * Q * kg);
}

// ---- plain model inputs from the editable inputs ------------------------------------
function normalise(values) {
  const total = values.reduce((s, x) => s + x, 0);
  return values.map(x => total > 0 ? 100 * x / total : 0);
}
// `scaleT` in [0, 1]: every input with a scaled-up value (`up`; null/blank = same as typical) moves from its
// typical (prototype) value to it. Production machine values are the sheet's `scaled_up` column — at 1 this is
// raw_lca.cases.scale_up_case; the other scaled-up values (product, materials, yields, circularity) are the tool's.
//
// A production step can be part of both versions or of one only (`usedIn`: both / prototype / scaledUp), and so can
// repair (`circularity.repairIn`). Something that exists in one version only has one set of values (its typical
// ones) and is absent in the other: a step without machine wear, electricity or losses (yield 100 %), no repairs.
// In between, it is faded in with weight t (scaled-up only) or out with 1 - t (prototype only), so both ends of
// the slider are exact.
function presence(usedIn, scaleT) {
  return usedIn === "prototype" ? 1 - scaleT : usedIn === "scaledUp" ? scaleT : 1;
}
function plainInputs(inp, specValue, scaleT = 0) {
  const val = p => Number(p.v);
  const scaled = p => (p.up === null || p.up === undefined || p.up === "" || !isFinite(p.up)) ? val(p) : lerp(val(p), Number(p.up), scaleT);
  const bom = list => {
    const shares = normalise(list.map(x => scaled(x.share)));
    return list.map((x, i) => ({ material: x.material, source: x.source, pct: shares[i] }));
  };
  const steps = list => list.map(s => {
    const used = (s.usedIn && s.usedIn.v) || "both";
    if (used === "both") {
      return { name: s.name, kgMachine: scaled(s.kgMachine), powerKW: scaled(s.powerKW), rateKgHr: scaled(s.rateKgHr),
        lifetimeHrs: scaled(s.lifetimeHrs), yieldPct: scaled(s.yieldPct), machineSource: s.machineSource.v };
    }
    const f = presence(used, scaleT);
    if (f <= 0) return null;
    return { name: s.name, kgMachine: f * val(s.kgMachine), powerKW: f * val(s.powerKW), rateKgHr: val(s.rateKgHr),
      lifetimeHrs: val(s.lifetimeHrs), yieldPct: lerp(100, val(s.yieldPct), f), machineSource: s.machineSource.v };
  }).filter(Boolean);
  const c = inp.circularity;
  const repairIn = (c.repairIn && c.repairIn.v) || "both";
  const rep = p => repairIn === "both" ? scaled(p) : val(p);           // one-version repair: one set of values
  const nRepairs = !c.enabled ? 0 : Math.max(0, Math.round(rep(c.numRepairs) * presence(repairIn, scaleT)));
  const eolShares = normalise(ROUTES.map(r => scaled(inp.eol[r])));
  const p = inp.product;
  return {
    specValue,
    productKg: specValue * scaled(p.density) * (1 - scaled(p.savings) / 100),
    location: inp.location.v,
    productionBom: bom(inp.productionBom),
    productionChain: steps(inp.productionChain),
    repair: {
      enabled: !!c.enabled,
      materialPct: rep(c.materialPct),
      expectedLifetime: scaled(c.expectedLifetime),
      extension: rep(c.extension),
      nRepairs,
    },
    repairBom: bom(inp.repairBom),
    repairChain: steps(inp.repairChain),
    eol: Object.fromEntries(ROUTES.map((r, i) => [r, eolShares[i]])),
  };
}

// ============================================================================
// runRaw — Model.run_raw. `m` = plainInputs(...), `rsl` = reference service life.
// ============================================================================
function runRaw(m, rsl, bgT = 0) {
  const rp = m.repair;
  const n = rp.nRepairs;
  const productKg = m.productKg;
  const repairKg = n > 0 ? rp.materialPct / 100 * productKg : 0;
  const life = rp.expectedLifetime + rp.extension * n;

  const proc = chain(m.productionChain, productKg, m.location, bgT);
  const inputKg = proc.inputKg;
  const mat = materials(m.productionBom, inputKg, bgT);
  let rep = zero(), repChain = null, repMat = null;
  const seqKg = m.productionBom.map(x => [x, inputKg * x.pct / 100, life]);
  if (n > 0) {
    repChain = chain(m.repairChain, repairKg, m.location, bgT);
    repMat = materials(m.repairBom, repChain.inputKg, bgT);
    rep = scale(add(repChain.total, repMat.total), n);
    for (let i = 1; i <= n; i++) {   // event i is stored (n - i + 1) x extension years
      const storage = (n - i + 1) * rp.extension;
      for (const x of m.repairBom) seqKg.push([x, repChain.inputKg * x.pct / 100, storage]);
    }
  }
  let growth = 0, delayed = 0;
  for (const [x, kg, st] of seqKg) {
    const s = storageCredit(x.material, x.source, kg, st);
    if (x.source === "virgin") growth += s; else delayed += s;
  }
  const seq = zero();
  seq[GWP] = growth + delayed;

  const kgWaste = productKg + repairKg * n;
  const raw = eolConstants(C.raw_product_eol_row);
  let eolB = zero(), circ = zero();
  const eolRoutes = {}, credits = {};
  for (const route of ROUTES) {
    const b = routeBurden(route, kgWaste, m.eol[route], raw.A, bgT);
    const c = materialCredit(route, kgWaste, m.eol[route], raw.A, raw.Q, bgT);
    eolRoutes[route] = b; credits[route] = c;
    eolB = add(eolB, b); circ = add(circ, c);
  }
  const energy = energyCredit(kgWaste, m.eol.incinerated, raw.LHV, m.location, raw.effHeat, raw.effElec, bgT);
  credits.energy = energy;
  circ = add(circ, energy);

  const f = life > 0 ? rsl / life : 1;
  const materialsV = scale(mat.total, f), productionV = scale(proc.total, f), repairV = scale(rep, f);
  const eolV = scale(eolB, f), seqV = scale(seq, f), circV = scale(circ, f);
  const burdens = add(add(add(materialsV, productionV), repairV), eolV);
  const benefits = add(seqV, circV);
  const sc = list => list.map(o => Object.assign({}, o, { burden: scale(o.burden, f) }));
  return {
    materials: materialsV, production: productionV, repair: repairV, eolBurden: eolV,
    sequestration: seqV, circularity: circV, burdens, benefits, net: add(burdens, benefits),
    info: { productKg, serviceLife: life, scaling: f, materialInputKg: inputKg, nRepairs: n, kgWaste },
    detail: {
      materialItems: sc(mat.items), productionSteps: sc(proc.steps),
      repairMaterialItems: repMat ? sc(repMat.items).map(o => Object.assign(o, { burden: scale(o.burden, n) })) : [],
      repairSteps: repChain ? sc(repChain.steps).map(o => Object.assign(o, { burden: scale(o.burden, n) })) : [],
      eolRoutes: Object.fromEntries(Object.entries(eolRoutes).map(([k, v]) => [k, scale(v, f)])),
      credits: Object.fromEntries(Object.entries(credits).map(([k, v]) => [k, scale(v, f)])),
      growth: growth * f, delayed: delayed * f,
    },
  };
}

// Convenience: the editable case inputs -> result at a scale-up and background position.
// `meta` = { specValue, rsl } (functional unit of the case: spec value and reference service life).
function runCase(inputs, meta, scaleT = 0, bgT = 0) {
  return runRaw(plainInputs(inputs, meta.specValue, scaleT), meta.rsl, bgT);
}

// ============================================================================
// Monte Carlo over the min/max of the inputs (parameter uncertainty only, background
// at its mean value — the baselines' whiskers in RAW_BASELINES are computed the same way).
// Distributions as raw_lca.params.ParameterSet.sample: triangular(min, typical, max),
// uniform(min, max), fixed / choice = typical. Shares are re-normalised by plainInputs.
// ============================================================================
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function drawParam(p, rng) {
  const v = Number(p.v), lo = Math.min(Number(p.min), v), hi = Math.max(Number(p.max), v);
  if (!isFinite(lo) || !isFinite(hi) || !(lo < hi)) return v;
  const u = rng();
  if (p.dist === "uniform") return lo + u * (hi - lo);
  if (p.dist !== "triangular") return v;
  const fc = (v - lo) / (hi - lo);
  return u < fc ? lo + Math.sqrt(u * (hi - lo) * (v - lo)) : hi - Math.sqrt((1 - u) * (hi - lo) * (hi - v));
}
// whether a number varies in the Monte Carlo (a range, and a triangular or uniform distribution)
function varies(p) {
  const v = Number(p.v), lo = Math.min(Number(p.min), v), hi = Math.max(Number(p.max), v);
  return (p.dist === "triangular" || p.dist === "uniform") && isFinite(lo) && isFinite(hi) && lo < hi;
}
// One draw of the editable inputs: every numeric {v, min, max, dist} object gets a sampled `v`
// (scaled-up values move with the same relative deviation as the prototype value).
// `record(path, value)` is called for every number that varies (used by the sensitivity analysis).
function sampleInputs(inputs, rng, record) {
  const walk = (o, path) => {
    if (Array.isArray(o)) return o.map((x, i) => walk(x, path ? `${path}.${i}` : String(i)));
    if (o && typeof o === "object") {
      if ("v" in o && "dist" in o && typeof o.v === "number") {
        const v = drawParam(o, rng);
        if (record && varies(o)) record(path, v);
        const out = Object.assign({}, o, { v });
        if (o.up !== undefined && o.up !== null && o.v !== 0) out.up = o.up * v / o.v;
        return out;
      }
      const out = {};
      for (const k in o) out[k] = k === "sheet" ? o[k] : walk(o[k], path ? `${path}.${k}` : k);
      return out;
    }
    return o;
  };
  return walk(inputs, "");
}
function percentile(sorted, q) {
  const pos = (sorted.length - 1) * q / 100, lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}
// variants: [{key, scaleT, bgT}] -> {key: {lo: [...], mid: [...], hi: [...]}} of the net impact (draws are paired),
// plus `draws`: the sampled value of every varying number and the net results of every draw, for sensitivity().
function runMonteCarlo(inputs, meta, variants, n = 500, seed = RAW_DATA.mcSeed) {
  const rng = mulberry32(seed);
  const nets = Object.fromEntries(variants.map(v => [v.key, []]));
  const x = {};                                   // path -> sampled values, one per draw
  for (let d = 0; d < n; d++) {
    const s = sampleInputs(inputs, rng, (path, v) => { (x[path] = x[path] || []).push(v); });
    for (const v of variants) nets[v.key].push(runCase(s, meta, v.scaleT, v.bgT).net);
  }
  const out = {};
  for (const v of variants) {
    const lo = zero(), mid = zero(), hi = zero();
    for (let i = 0; i < N_CAT; i++) {
      const col = nets[v.key].map(r => r[i]).filter(isFinite).sort((a, b) => a - b);
      if (!col.length) { lo[i] = mid[i] = hi[i] = NaN; continue; }
      lo[i] = percentile(col, 5); mid[i] = percentile(col, 50); hi[i] = percentile(col, 95);
    }
    out[v.key] = { lo, mid, hi };
  }
  out.draws = { x, nets };
  return out;
}

// ---- global sensitivity: rank correlations of the Monte Carlo draws --------------------
// For every varying number, the Spearman rank correlation rho between its sampled values and the net impact
// (variant `key`, category index ci). rho^2, normalised over all numbers, approximates each number's share of the
// output variance (exact for a monotonic, additive model; a screening measure otherwise). With n draws, |rho| below
// about 2 / sqrt(n) can't be told apart from zero.
function ranks(values) {
  const idx = values.map((v, i) => i).sort((a, b) => values[a] - values[b]);
  const r = new Array(values.length);
  for (let k = 0; k < idx.length;) {                 // ties get their average rank
    let m = k;
    while (m + 1 < idx.length && values[idx[m + 1]] === values[idx[k]]) m++;
    for (let q = k; q <= m; q++) r[idx[q]] = (k + m) / 2;
    k = m + 1;
  }
  return r;
}
function pearson(a, b) {
  const n = a.length, ma = a.reduce((s, x) => s + x, 0) / n, mb = b.reduce((s, x) => s + x, 0) / n;
  let sab = 0, saa = 0, sbb = 0;
  for (let i = 0; i < n; i++) { const da = a[i] - ma, db = b[i] - mb; sab += da * db; saa += da * da; sbb += db * db; }
  return saa > 0 && sbb > 0 ? sab / Math.sqrt(saa * sbb) : 0;
}
function sensitivity(draws, key, ci) {
  const y = draws.nets[key].map(r => r[ci]);
  if (!y.length || y.some(v => !isFinite(v))) return [];
  const ry = ranks(y);
  const rows = Object.entries(draws.x).map(([path, xs]) => ({ path, rho: pearson(ranks(xs), ry) }));
  const total = rows.reduce((s, r) => s + r.rho * r.rho, 0);
  for (const r of rows) r.share = total > 0 ? r.rho * r.rho / total : 0;
  return rows.sort((a, b) => b.share - a.share);
}
