// ============================================================================
// calc.js — JS port of 02_model.ipynb
// Every function here mirrors a function in the notebook 1:1 so the tool can
// be checked against it. Reference case (see notebook) validated to match:
//   Material 1.4554 / Production 8.9899 / Repair 0.7869 / TOTAL 11.2322
//   EoL burden 0.0850 / seq_growth -1.0535 / seq_avoided -0.5177
// ============================================================================

const CATEGORIES = RAW_DATA.categories;
const QUALITY_RATIO_PRIMARY = 1.0;
const MOLAR_RATIO = 44 / 12;
const CONV_EFF_HEAT = 0.6;
const CONV_EFF_ELEC = 0.25;

function zeroSeries() {
  const s = {};
  for (const c of CATEGORIES) s[c] = 0.0;
  return s;
}
function addSeries(a, b, sign = 1) {
  const out = Object.assign({}, a);
  for (const k in b) out[k] = (out[k] || 0) + sign * b[k];
  return out;
}
function scaleSeries(a, s) {
  const out = {};
  for (const k in a) out[k] = a[k] * s;
  return out;
}

// ---- unit burden lookups --------------------------------------------------
function rowsFor(name, loc, src) {
  return RAW_DATA.unitBurdens.filter(r =>
    r.m === name &&
    (loc === undefined || loc === null || r.loc === loc) &&
    (src === undefined || src === null || r.src === src)
  );
}
function getUnitBurden(name, opts = {}) {
  const rows = rowsFor(name, opts.location, opts.materialSource);
  const s = zeroSeries();
  for (const r of rows) s[r.cat] = r.score;
  return s;
}
function getUnitBurdenBySource(materialName, materialSource) {
  return getUnitBurden(materialName, { materialSource });
}
function isGrowthEligible(materialSource) {
  return materialSource === "virgin";
}
function getEolConstants(materialName) {
  const c = RAW_DATA.eolConstants[materialName];
  if (!c) throw new Error(`No EoL constants for '${materialName}'`);
  return c; // {A, Qs, LHV}
}
function getBenefitParams(materialName) {
  return RAW_DATA.benefitParams[materialName] || null; // {C, rot} or null
}
function getMaterialUnitBurden(materialName, materialSource) {
  if (materialSource === "recycled") {
    const { A, Qs } = getEolConstants(materialName);
    const eRecycled = getUnitBurdenBySource(materialName, "recycled");
    const eVirgin = getUnitBurdenBySource(materialName, "virgin");
    return addSeries(
      scaleSeries(eRecycled, A),
      scaleSeries(eVirgin, (1 - A) * (Qs / QUALITY_RATIO_PRIMARY))
    );
  }
  return getUnitBurdenBySource(materialName, materialSource);
}

// ---- material & process burdens -------------------------------------------
function computeMaterialBurdens(bom, totalInputKg) {
  let total = zeroSeries();
  for (const item of bom) {
    const kg = (totalInputKg * item.pct) / 100;
    const ub = getMaterialUnitBurden(item.material, item.source);
    total = addSeries(total, scaleSeries(ub, kg));
  }
  return total;
}

function computeProcessBurdens(chain, targetOutputKg) {
  const n = chain.length;
  const requiredInputKg = new Array(n);
  let nextRequired = targetOutputKg;
  for (let i = n - 1; i >= 0; i--) {
    requiredInputKg[i] = nextRequired / (chain[i].retainedPct / 100);
    nextRequired = requiredInputKg[i];
  }
  let total = zeroSeries();
  const steps = [];
  for (let i = 0; i < n; i++) {
    const step = chain[i];
    const processTimeHrs = requiredInputKg[i] / step.rateKgHr;
    const machineWearKg = step.kgMachine * (processTimeHrs / step.lifetimeHrs);
    const energyUseKwh = step.powerKW * processTimeHrs;
    const machineBurden = scaleSeries(
      getUnitBurden("machine wear", { materialSource: step.machineSource }),
      machineWearKg
    );
    const electricityBurden = scaleSeries(
      getUnitBurden("energy use", { location: step.elecLoc }),
      energyUseKwh
    );
    total = addSeries(addSeries(total, machineBurden), electricityBurden);
    steps.push({
      name: step.name,
      requiredInputKg: requiredInputKg[i],
      processTimeHrs, machineWearKg, energyUseKwh,
    });
  }
  return { total, steps, firstRequiredInputKg: requiredInputKg[0] };
}

// ---- end of life ------------------------------------------------------------
function absSeries(s) {
  const o = {};
  for (const k in s) o[k] = Math.abs(s[k]);
  return o;
}
function computeEolBurdens(eol, totalDisposedKg, Aeol) {
  const cat = (name) => getUnitBurden(name);
  const compost = absSeries(scaleSeries(cat("waste composting"), (1 - Aeol) * (eol.composted / 100) * totalDisposedKg));
  const recOpen = absSeries(scaleSeries(cat("waste recycling"), (1 - Aeol) * (eol.recycledOpen / 100) * totalDisposedKg));
  const recClosed = absSeries(scaleSeries(cat("waste recycling"), (1 - Aeol) * (eol.recycledClosed / 100) * totalDisposedKg));
  const incin = absSeries(scaleSeries(cat("waste incineration"), (eol.incinerated / 100) * totalDisposedKg));
  const landfill = absSeries(scaleSeries(cat("waste landfilling"), (eol.landfilled / 100) * totalDisposedKg));
  let total = zeroSeries();
  for (const s of [compost, recOpen, recClosed, incin, landfill]) total = addSeries(total, s);
  return { total, breakdown: { compost, recOpen, recClosed, incin, landfill } };
}

function computeEolBenefits(eol, totalDisposedKg, Aeol, Qs, LHV, disposalLoc) {
  const compostCredit = scaleSeries(
    getUnitBurden("avoided burden - composting"),
    -(1 - Aeol) * (eol.composted / 100) * Qs * totalDisposedKg
  );
  const recycleOpenCredit = scaleSeries(
    getUnitBurden("avoided buden - open loop recycling"),
    -(1 - Aeol) * (eol.recycledOpen / 100) * Qs * totalDisposedKg
  );
  const heat = getUnitBurden("avoided burden - incineration, heat");
  const elec = getUnitBurden("avoided burden - incineration, electricity", { location: disposalLoc });
  const incinerateFactor = -(eol.incinerated / 100) * LHV * totalDisposedKg;
  const incinerateCredit = scaleSeries(
    addSeries(scaleSeries(heat, CONV_EFF_HEAT), scaleSeries(elec, CONV_EFF_ELEC)),
    incinerateFactor
  );
  let total = zeroSeries();
  for (const s of [compostCredit, recycleOpenCredit, incinerateCredit]) total = addSeries(total, s);
  return { total, breakdown: { compostCredit, recycleOpenCredit, incinerateCredit } };
}

// ---- carbon sequestration ----------------------------------------------------
const ROTATION_PERIODS = [1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
const STORAGE_PERIODS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
const GWPBIO_TABLE = {
  1: [0.00, -0.07, -0.15, -0.23, -0.32, -0.40, -0.50, -0.60, -0.71, -0.84, -0.99],
  10: [0.04, -0.04, -0.12, -0.20, -0.28, -0.37, -0.46, -0.57, -0.68, -0.80, -0.96],
  20: [0.08, 0.00, -0.08, -0.16, -0.24, -0.33, -0.42, -0.53, -0.64, -0.76, -0.92],
  30: [0.12, 0.04, -0.04, -0.12, -0.20, -0.29, -0.38, -0.48, -0.60, -0.72, -0.88],
  40: [0.16, 0.09, 0.01, -0.08, -0.16, -0.25, -0.34, -0.44, -0.55, -0.68, -0.84],
  50: [0.20, 0.13, 0.05, -0.03, -0.12, -0.21, -0.30, -0.40, -0.51, -0.64, -0.80],
  60: [0.25, 0.17, 0.09, 0.01, -0.07, -0.16, -0.26, -0.36, -0.47, -0.59, -0.75],
  70: [0.29, 0.22, 0.14, 0.06, -0.03, -0.12, -0.21, -0.31, -0.42, -0.55, -0.71],
  80: [0.34, 0.26, 0.18, 0.10, 0.02, -0.07, -0.17, -0.27, -0.38, -0.50, -0.66],
  90: [0.38, 0.31, 0.23, 0.15, 0.06, -0.03, -0.12, -0.22, -0.33, -0.46, -0.62],
  100: [0.44, 0.37, 0.29, 0.21, 0.12, 0.032, -0.06, -0.16, -0.27, -0.40, -0.56],
};
function lookupGwpBio(rotationYr, storageYr) {
  let nearest = ROTATION_PERIODS[0], best = Infinity;
  for (const r of ROTATION_PERIODS) { const d = Math.abs(r - rotationYr); if (d < best) { best = d; nearest = r; } }
  const row = GWPBIO_TABLE[nearest];
  storageYr = Math.max(0, Math.min(storageYr, STORAGE_PERIODS[STORAGE_PERIODS.length - 1]));
  if (storageYr % 10 === 0) return row[STORAGE_PERIODS.indexOf(storageYr)];
  const lo = Math.floor(storageYr / 10) * 10, hi = lo + 10, frac = (storageYr - lo) / 10;
  return row[STORAGE_PERIODS.indexOf(lo)] * (1 - frac) + row[STORAGE_PERIODS.indexOf(hi)] * frac;
}
const BERN_A = [0.217, 0.259, 0.338, 0.186];
const BERN_TAU = [null, 172.9, 18.51, 1.186];
function agwpIntegral(t) {
  const [a0, a1, a2, a3] = BERN_A;
  const [, tau1, tau2, tau3] = BERN_TAU;
  return a0 * t
    + a1 * tau1 * (1 - Math.exp(-t / tau1))
    + a2 * tau2 * (1 - Math.exp(-t / tau2))
    + a3 * tau3 * (1 - Math.exp(-t / tau3));
}
function dynamicCf(tauStorage, T = 100) {
  return agwpIntegral(T - tauStorage) / agwpIntegral(T);
}
function computeSequestrationCredit(bom, totalKg, storageYr) {
  let total = 0.0;
  for (const item of bom) {
    if (!isGrowthEligible(item.source)) continue;
    const bp = getBenefitParams(item.material);
    if (!bp || bp.rot === null || bp.rot === undefined) continue;
    const kg = (totalKg * item.pct) / 100;
    const gwp = lookupGwpBio(bp.rot, storageYr);
    total += bp.C * kg * MOLAR_RATIO * gwp;
  }
  return total;
}
function computeDelayedEmissionsCredit(bom, totalKg, storageYr) {
  let total = 0.0;
  for (const item of bom) {
    if (isGrowthEligible(item.source)) continue;
    const bp = getBenefitParams(item.material);
    if (!bp) continue;
    const kg = (totalKg * item.pct) / 100;
    const dcf = dynamicCf(storageYr);
    total += bp.C * kg * MOLAR_RATIO * (dcf - 1);
  }
  return total;
}

// ============================================================================
// runModel(scenario) — full pipeline, returns everything the UI needs
// ============================================================================
function runModel(scenario) {
  const productKg = scenario.productKg;

  const prod = computeProcessBurdens(scenario.productionChain, productKg);
  const totalMaterialInputKg = prod.firstRequiredInputKg;
  const materialBurdens = computeMaterialBurdens(scenario.productionBom, totalMaterialInputKg);

  let repairBurdens = zeroSeries();
  let repairMaterialInputKg = 0;
  let repairSteps = [];
  let productionStorageYr = scenario.repair.expectedLifetimeYr;
  let repairStorageYr = [];
  let repairMaterialKg = 0;
  const nRepairs = scenario.repair.enabled ? scenario.repair.numRepairs : 0;

  if (scenario.repair.enabled) {
    repairMaterialKg = (scenario.repair.repairMaterialPctOfProduct / 100) * productKg;
    const rep = computeProcessBurdens(scenario.repairChain, repairMaterialKg);
    repairMaterialInputKg = rep.firstRequiredInputKg;
    repairSteps = rep.steps;
    const repairMaterialBurdensPerEvent = computeMaterialBurdens(scenario.repairBom, repairMaterialInputKg);
    repairBurdens = scaleSeries(addSeries(rep.total, repairMaterialBurdensPerEvent), nRepairs);

    productionStorageYr = scenario.repair.expectedLifetimeYr + scenario.repair.extensionPerRepairYr * nRepairs;
    for (let i = 1; i <= nRepairs; i++) {
      repairStorageYr.push((nRepairs - i + 1) * scenario.repair.extensionPerRepairYr);
    }
  }

  const totalDisposedKg = productKg + repairMaterialKg * nRepairs;
  const { A: Aeol, Qs: QsEol, LHV } = getEolConstants("RAW product");
  const eolBurdens = computeEolBurdens(scenario.eol, totalDisposedKg, Aeol);
  const eolBenefits = computeEolBenefits(scenario.eol, totalDisposedKg, Aeol, QsEol, LHV, scenario.eol.disposalElecLoc);

  const prodSeq = computeSequestrationCredit(scenario.productionBom, totalMaterialInputKg, productionStorageYr);
  const prodDelay = computeDelayedEmissionsCredit(scenario.productionBom, totalMaterialInputKg, productionStorageYr);
  let repSeq = 0, repDelay = 0;
  if (scenario.repair.enabled) {
    for (const sy of repairStorageYr) {
      repSeq += computeSequestrationCredit(scenario.repairBom, repairMaterialInputKg, sy);
      repDelay += computeDelayedEmissionsCredit(scenario.repairBom, repairMaterialInputKg, sy);
    }
  }
  const seqGrowth = prodSeq + repSeq;
  const seqAvoided = prodDelay + repDelay;
  const seqTotal = zeroSeries();
  seqTotal["climate change"] = seqGrowth + seqAvoided;

  const totalBurdens = addSeries(addSeries(addSeries(materialBurdens, prod.total), repairBurdens), eolBurdens.total);
  const net = addSeries(addSeries(totalBurdens, seqTotal), eolBenefits.total);

  return {
    scenario,
    totalMaterialInputKg, repairMaterialInputKg, totalDisposedKg,
    productionSteps: prod.steps, repairSteps,
    materialBurdens, productionBurdens: prod.total, repairBurdens,
    eolBurdens: eolBurdens.total, eolBurdensBreakdown: eolBurdens.breakdown,
    seqGrowth, seqAvoided, seqTotal,
    eolBenefits: eolBenefits.total, eolBenefitsBreakdown: eolBenefits.breakdown,
    totalBurdens, net,
  };
}
