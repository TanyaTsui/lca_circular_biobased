// ============================================================================
// app.js — UI state, rendering, diff/compare engine, recording
// ============================================================================

// ---------- helpers ----------------------------------------------------------
function deepClone(o) { return JSON.parse(JSON.stringify(o)); }
function lerp(a, b, t) { return a + (b - a) * t; }
function uid(prefix) { return prefix + Math.random().toString(36).slice(2, 9); }
function fmt(n, digits = 3) {
  if (n === undefined || n === null || isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs !== 0 && (abs < 0.001 || abs >= 100000)) return n.toExponential(2);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
function catUnit(cat) {
  const row = RAW_DATA.unitBurdens.find(r => r.cat === cat);
  return row ? row.unit : "";
}
function defaultSourceFor(material) {
  const opts = RAW_DATA.bomMaterials[material] || ["virgin"];
  return opts[0];
}

// ---------- default (starting) scenario — mirrors the notebook example ------
function defaultScenario() {
  return {
    productKg: 1.0,
    productionBom: [
      { material: "Pea protein binder", pct: 70, source: "virgin" },
      { material: "Sawdust", pct: 20, source: "co-product" },
      { material: "Seagrass", pct: 10, source: "wild-harvested" },
    ],
    productionChain: [
      { name: "Mixing", kgMachine: 80, powerKW: 1.5, rateKgHr: 15.0, lifetimeHrs: 15000, elecLoc: "NL", retainedPct: 98, machineSource: "virgin" },
      { name: "3D printing", kgMachine: 250, powerKW: 2.5, rateKgHr: 0.5, lifetimeHrs: 20000, elecLoc: "NL", retainedPct: 92, machineSource: "recycled" },
      { name: "Baking", kgMachine: 500, powerKW: 8.0, rateKgHr: 4.0, lifetimeHrs: 25000, elecLoc: "NL", retainedPct: 30, machineSource: "virgin" },
    ],
    repair: {
      enabled: true,
      repairMaterialPctOfProduct: 10,
      expectedLifetimeYr: 20,
      extensionPerRepairYr: 10,
      numRepairs: 3,
    },
    repairBom: [
      { material: "Pea protein binder", pct: 80, source: "virgin" },
      { material: "Seagrass", pct: 10, source: "wild-harvested" },
      { material: "Hemp fiber", pct: 10, source: "virgin" },
    ],
    repairChain: [
      { name: "Mixing", kgMachine: 80, powerKW: 1.5, rateKgHr: 15.0, lifetimeHrs: 15000, elecLoc: "NL", retainedPct: 98, machineSource: "virgin" },
      { name: "3D printing", kgMachine: 250, powerKW: 2.5, rateKgHr: 0.5, lifetimeHrs: 20000, elecLoc: "NL", retainedPct: 92, machineSource: "virgin" },
    ],
    eol: {
      composted: 30, recycledOpen: 20, recycledClosed: 30, incinerated: 10, landfilled: 10,
      disposalElecLoc: "NL",
    },
  };
}
function emptyStep(name) {
  return { name: name || "New step", kgMachine: 50, powerKW: 1.0, rateKgHr: 5.0, lifetimeHrs: 15000, elecLoc: "NL", retainedPct: 95, machineSource: "virgin" };
}
function emptyBomItem() {
  const m = Object.keys(RAW_DATA.bomMaterials)[0];
  return { material: m, pct: 0, source: defaultSourceFor(m) };
}

// ---------- global state ------------------------------------------------------
const state = {
  scenarios: { A: defaultScenario(), B: null },
  activeTab: "A",
  category: "climate change",
  compareDiffs: [],
  compareT: {}, // diffId -> 0..100
  sheetUrl: "",
};

// ============================================================================
// FORM RENDERING (left column)
// ============================================================================
function fieldNum(label, value, path, opts = {}) {
  const step = opts.step || "any";
  return `<div class="field${opts.wide ? ' field-wide' : ''}">
    <label>${label}${opts.unit ? ` <span style="opacity:.6">(${opts.unit})</span>` : ''}</label>
    <input type="number" step="${step}" value="${value}" data-path="${path}">
  </div>`;
}
function fieldSelect(label, value, path, options, opts = {}) {
  return `<div class="field${opts.wide ? ' field-wide' : ''}">
    <label>${label}</label>
    <select data-path="${path}">
      ${options.map(o => `<option value="${o}" ${o === value ? "selected" : ""}>${o}</option>`).join("")}
    </select>
  </div>`;
}
function fieldText(label, value, path, opts = {}) {
  return `<div class="field${opts.wide ? ' field-wide' : ''}">
    <label>${label}</label>
    <input type="text" value="${value}" data-path="${path}">
  </div>`;
}

function renderBomSection(scKey, bomKey, title, hint) {
  const scenario = state.scenarios[scKey];
  const bom = scenario[bomKey];
  const total = bom.reduce((s, i) => s + Number(i.pct || 0), 0);
  const badgeClass = Math.abs(total - 100) < 0.01 ? "bom-total-ok" : "bom-total-bad";
  const rows = bom.map((item, i) => {
    const opts = RAW_DATA.bomMaterials[item.material] || [item.source];
    return `<div class="item-card">
      <div class="item-card-head">
        <div class="item-title"><span class="item-index">${i + 1}</span>${item.material}</div>
        <button class="remove-btn" data-action="remove-bom" data-sc="${scKey}" data-bom="${bomKey}" data-idx="${i}">remove</button>
      </div>
      <div class="field-grid">
        ${fieldSelect("Material", item.material, `${scKey}.${bomKey}.${i}.material`, Object.keys(RAW_DATA.bomMaterials))}
        ${fieldSelect("Source", item.source, `${scKey}.${bomKey}.${i}.source`, opts)}
        ${fieldNum("% of input mass", item.pct, `${scKey}.${bomKey}.${i}.pct`, { unit: "%", step: "0.1" })}
      </div>
    </div>`;
  }).join("");
  return `<div class="section">
    <div class="section-head">
      <h3>${title}</h3>
      <span class="bom-total-badge ${badgeClass}" id="badge-${scKey}-${bomKey}">${total.toFixed(1)}%</span>
    </div>
    <p class="section-note">${hint}</p>
    <div class="card-list" id="list-${scKey}-${bomKey}">${rows}</div>
    <button class="add-row-btn" data-action="add-bom" data-sc="${scKey}" data-bom="${bomKey}">+ add material</button>
  </div>`;
}

function renderChainSection(scKey, chainKey, title, hint) {
  const scenario = state.scenarios[scKey];
  const chain = scenario[chainKey];
  const cards = chain.map((step, i) => {
    const card = `<div class="item-card">
      <div class="item-card-head">
        <div class="item-title"><span class="item-index">${i + 1}</span>
          <input type="text" value="${step.name}" data-path="${scKey}.${chainKey}.${i}.name"
            style="border:none;background:transparent;font-family:var(--font-display);font-weight:600;font-size:13px;color:var(--ink);padding:0;width:140px;">
        </div>
        <button class="remove-btn" data-action="remove-step" data-sc="${scKey}" data-chain="${chainKey}" data-idx="${i}">remove</button>
      </div>
      <div class="field-grid">
        ${fieldNum("Machine mass", step.kgMachine, `${scKey}.${chainKey}.${i}.kgMachine`, { unit: "kg" })}
        ${fieldSelect("Machine source", step.machineSource, `${scKey}.${chainKey}.${i}.machineSource`, ["virgin", "recycled"])}
        ${fieldNum("Machine lifetime", step.lifetimeHrs, `${scKey}.${chainKey}.${i}.lifetimeHrs`, { unit: "hrs" })}
        ${fieldNum("Power draw", step.powerKW, `${scKey}.${chainKey}.${i}.powerKW`, { unit: "kW" })}
        ${fieldSelect("Electricity location", step.elecLoc, `${scKey}.${chainKey}.${i}.elecLoc`, RAW_DATA.locations)}
        ${fieldNum("Throughput rate", step.rateKgHr, `${scKey}.${chainKey}.${i}.rateKgHr`, { unit: "kg/hr" })}
        ${fieldNum("Mass retained after step", step.retainedPct, `${scKey}.${chainKey}.${i}.retainedPct`, { unit: "%", step: "0.1" })}
      </div>
    </div>`;
    const connector = i < chain.length ? `<div class="flow-connector"><div class="line"></div><span class="arrow">&darr;</span>
      <span class="pct-pill" id="pill-${scKey}-${chainKey}-${i}">${step.retainedPct}% carries to next step</span></div>` : "";
    return card + (i < chain.length - 1 ? connector : "");
  }).join("");
  return `<div class="section">
    <div class="section-head"><h3>${title}</h3></div>
    <p class="section-note">${hint}</p>
    <div class="card-list" id="list-${scKey}-${chainKey}">${cards}</div>
    <button class="add-row-btn" data-action="add-step" data-sc="${scKey}" data-chain="${chainKey}">+ add process step</button>
  </div>`;
}

function renderRepairSection(scKey) {
  const scenario = state.scenarios[scKey];
  const r = scenario.repair;
  let inner = "";
  if (r.enabled) {
    inner = `
      <div class="field-grid" style="margin-bottom:16px;">
        ${fieldNum("Repair material (% of product mass, per event)", r.repairMaterialPctOfProduct, `${scKey}.repair.repairMaterialPctOfProduct`, { unit: "%" })}
        ${fieldNum("Expected lifetime without repair", r.expectedLifetimeYr, `${scKey}.repair.expectedLifetimeYr`, { unit: "yr" })}
        ${fieldNum("Lifetime extension per repair", r.extensionPerRepairYr, `${scKey}.repair.extensionPerRepairYr`, { unit: "yr" })}
        ${fieldNum("Number of repair events", r.numRepairs, `${scKey}.repair.numRepairs`, { unit: "" })}
      </div>
      ${renderBomSectionInner(scKey, "repairBom", "Repair bill of materials")}
      ${renderChainSectionInner(scKey, "repairChain", "Repair process chain")}
    `;
  }
  return `<div class="section">
    <div class="section-head">
      <h3>Repair</h3>
      <label class="toggle-row"><span class="switch"><input type="checkbox" ${r.enabled ? "checked" : ""} data-action="toggle-repair" data-sc="${scKey}"><span class="slider"></span></span>
      <span class="hint">${r.enabled ? "included" : "not included"}</span></label>
    </div>
    <p class="section-note">Repairs use their own (usually shorter) chain and their own bill of materials, and extend the product's service life.</p>
    ${inner}
  </div>`;
}
// stripped-down (non-<div class="section">) variants for nesting inside Repair
function renderBomSectionInner(scKey, bomKey, title) {
  const scenario = state.scenarios[scKey];
  const bom = scenario[bomKey];
  const total = bom.reduce((s, i) => s + Number(i.pct || 0), 0);
  const badgeClass = Math.abs(total - 100) < 0.01 ? "bom-total-ok" : "bom-total-bad";
  const rows = bom.map((item, i) => {
    const opts = RAW_DATA.bomMaterials[item.material] || [item.source];
    return `<div class="item-card">
      <div class="item-card-head">
        <div class="item-title"><span class="item-index">${i + 1}</span>${item.material}</div>
        <button class="remove-btn" data-action="remove-bom" data-sc="${scKey}" data-bom="${bomKey}" data-idx="${i}">remove</button>
      </div>
      <div class="field-grid">
        ${fieldSelect("Material", item.material, `${scKey}.${bomKey}.${i}.material`, Object.keys(RAW_DATA.bomMaterials))}
        ${fieldSelect("Source", item.source, `${scKey}.${bomKey}.${i}.source`, opts)}
        ${fieldNum("% of input mass", item.pct, `${scKey}.${bomKey}.${i}.pct`, { unit: "%", step: "0.1" })}
      </div>
    </div>`;
  }).join("");
  return `<div style="margin-bottom:16px;">
    <div class="section-head"><h4 style="font-size:12.5px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.05em;">${title}</h4>
      <span class="bom-total-badge ${badgeClass}" id="badge-${scKey}-${bomKey}">${total.toFixed(1)}%</span></div>
    <div class="card-list" id="list-${scKey}-${bomKey}">${rows}</div>
    <button class="add-row-btn" data-action="add-bom" data-sc="${scKey}" data-bom="${bomKey}">+ add material</button>
  </div>`;
}
function renderChainSectionInner(scKey, chainKey, title) {
  const scenario = state.scenarios[scKey];
  const chain = scenario[chainKey];
  const cards = chain.map((step, i) => {
    const card = `<div class="item-card">
      <div class="item-card-head">
        <div class="item-title"><span class="item-index">${i + 1}</span>
          <input type="text" value="${step.name}" data-path="${scKey}.${chainKey}.${i}.name"
            style="border:none;background:transparent;font-family:var(--font-display);font-weight:600;font-size:13px;color:var(--ink);padding:0;width:140px;">
        </div>
        <button class="remove-btn" data-action="remove-step" data-sc="${scKey}" data-chain="${chainKey}" data-idx="${i}">remove</button>
      </div>
      <div class="field-grid">
        ${fieldNum("Machine mass", step.kgMachine, `${scKey}.${chainKey}.${i}.kgMachine`, { unit: "kg" })}
        ${fieldSelect("Machine source", step.machineSource, `${scKey}.${chainKey}.${i}.machineSource`, ["virgin", "recycled"])}
        ${fieldNum("Machine lifetime", step.lifetimeHrs, `${scKey}.${chainKey}.${i}.lifetimeHrs`, { unit: "hrs" })}
        ${fieldNum("Power draw", step.powerKW, `${scKey}.${chainKey}.${i}.powerKW`, { unit: "kW" })}
        ${fieldSelect("Electricity location", step.elecLoc, `${scKey}.${chainKey}.${i}.elecLoc`, RAW_DATA.locations)}
        ${fieldNum("Throughput rate", step.rateKgHr, `${scKey}.${chainKey}.${i}.rateKgHr`, { unit: "kg/hr" })}
        ${fieldNum("Mass retained after step", step.retainedPct, `${scKey}.${chainKey}.${i}.retainedPct`, { unit: "%", step: "0.1" })}
      </div>
    </div>`;
    const connector = i < chain.length - 1 ? `<div class="flow-connector"><div class="line"></div><span class="arrow">&darr;</span>
      <span class="pct-pill" id="pill-${scKey}-${chainKey}-${i}">${step.retainedPct}% carries to next step</span></div>` : "";
    return card + connector;
  }).join("");
  return `<div style="margin-bottom:6px;">
    <h4 style="font-size:12.5px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">${title}</h4>
    <div class="card-list" id="list-${scKey}-${chainKey}">${cards}</div>
    <button class="add-row-btn" data-action="add-step" data-sc="${scKey}" data-chain="${chainKey}">+ add process step</button>
  </div>`;
}

function renderEolSection(scKey) {
  const scenario = state.scenarios[scKey];
  const e = scenario.eol;
  const total = e.composted + e.recycledOpen + e.recycledClosed + e.incinerated + e.landfilled;
  const badgeClass = Math.abs(total - 100) < 0.01 ? "bom-total-ok" : "bom-total-bad";
  return `<div class="section">
    <div class="section-head">
      <h3>End of life</h3>
      <span class="bom-total-badge ${badgeClass}" id="badge-${scKey}-eol">${total.toFixed(1)}%</span>
    </div>
    <p class="section-note">How the product (and any repair off-cuts) is disposed of at end of life. Shares should sum to 100%.</p>
    <div class="field-grid">
      ${fieldNum("Composted", e.composted, `${scKey}.eol.composted`, { unit: "%", step: "0.1" })}
      ${fieldNum("Recycled (open loop)", e.recycledOpen, `${scKey}.eol.recycledOpen`, { unit: "%", step: "0.1" })}
      ${fieldNum("Recycled (closed loop)", e.recycledClosed, `${scKey}.eol.recycledClosed`, { unit: "%", step: "0.1" })}
      ${fieldNum("Incinerated", e.incinerated, `${scKey}.eol.incinerated`, { unit: "%", step: "0.1" })}
      ${fieldNum("Landfilled", e.landfilled, `${scKey}.eol.landfilled`, { unit: "%", step: "0.1" })}
      ${fieldSelect("Disposal grid location", e.disposalElecLoc, `${scKey}.eol.disposalElecLoc`, RAW_DATA.locations, { wide: true })}
    </div>
  </div>`;
}

function renderScenarioEditor(scKey) {
  const scenario = state.scenarios[scKey];
  if (!scenario) {
    return `<div class="panel panel-pad">
      <div class="empty-state">
        <h3 style="color:var(--ink);">No future scenario yet</h3>
        <p style="margin-top:8px;font-size:12.5px;">Start from today's numbers, then change whatever you think you can optimise. The Compare tab will pick up exactly what's different.</p>
        <button class="btn btn-primary" id="btn-copy-a-to-b">Copy today's numbers &rarr;</button>
      </div>
    </div>`;
  }
  return `<div class="panel">
    <div class="section" style="border-bottom:1px solid var(--line-soft);">
      <div class="section-head"><h3>Product basis</h3></div>
      <div class="field-grid">
        ${fieldNum("Target output mass", scenario.productKg, `${scKey}.productKg`, { unit: "kg", step: "0.01" })}
      </div>
    </div>
    ${renderBomSection(scKey, "productionBom", "Bill of materials — production", "Composition of the input mass, as % of the total. Production and repair each have their own mix.")}
    ${renderChainSection(scKey, "productionChain", "Production process chain", "Ordered fabrication steps. The chain is solved backward from the target output mass, using each step's mass retention.")}
    ${renderRepairSection(scKey)}
    ${renderEolSection(scKey)}
  </div>`;
}

// ============================================================================
// COMPARE TAB — diff detection + independent sliders
// ============================================================================
function buildDiffs(A, B) {
  const diffs = [];

  function addSlider(label, group, a, b, unit, apply, order = 1) {
    if (Math.abs(a - b) < 1e-9) return;
    diffs.push({ id: uid("d"), type: "slider", label, group, a, b, unit, apply, order });
  }
  function addToggle(label, group, a, b, apply, order = 0) {
    if (a === b) return;
    diffs.push({ id: uid("d"), type: "toggle", label, group, a, b, apply, order });
  }

  addSlider("Target output mass", "Product", A.productKg, B.productKg, "kg", (c, t) => { c.productKg = lerp(A.productKg, B.productKg, t); });

  function diffBom(bomKey, groupLabel) {
    const bomA = A[bomKey], bomB = B[bomKey];
    const names = Array.from(new Set([...bomA.map(x => x.material), ...bomB.map(x => x.material)]));
    for (const name of names) {
      const ia = bomA.find(x => x.material === name);
      const ib = bomB.find(x => x.material === name);
      const pctA = ia ? ia.pct : 0, pctB = ib ? ib.pct : 0;
      const srcA = ia ? ia.source : (ib ? ib.source : "virgin");
      const srcB = ib ? ib.source : (ia ? ia.source : "virgin");
      if (Math.abs(pctA - pctB) > 1e-9) {
        addSlider(`${name} — % of input mass`, groupLabel, pctA, pctB, "%", (c, t) => {
          const pct = lerp(pctA, pctB, t);
          const src = t >= 0.5 ? srcB : srcA;
          let it = c[bomKey].find(x => x.material === name);
          if (!it) { it = { material: name, pct, source: src }; c[bomKey].push(it); }
          else { it.pct = pct; it.source = src; }
        });
      }
      if (ia && ib && ia.source !== ib.source) {
        addToggle(`${name} — material source`, groupLabel, ia.source, ib.source, (c, t) => {
          const it = c[bomKey].find(x => x.material === name);
          if (it) it.source = t >= 0.5 ? ib.source : ia.source;
        });
      }
    }
  }
  diffBom("productionBom", "Production mix");
  diffBom("repairBom", "Repair mix");

  function diffChain(chainKey, groupLabel) {
    const chA = A[chainKey], chB = B[chainKey];
    const names = [];
    for (const s of chA) if (!names.includes(s.name)) names.push(s.name);
    for (const s of chB) if (!names.includes(s.name)) names.push(s.name);
    for (const name of names) {
      const sa = chA.find(x => x.name === name);
      const sb = chB.find(x => x.name === name);
      if (sa && sb) {
        const numFields = [
          ["kgMachine", "machine mass", "kg"], ["powerKW", "power draw", "kW"],
          ["rateKgHr", "throughput", "kg/hr"], ["lifetimeHrs", "machine lifetime", "hrs"],
          ["retainedPct", "mass retained", "%"],
        ];
        for (const [f, label, unit] of numFields) {
          addSlider(`${name} — ${label}`, groupLabel, sa[f], sb[f], unit, (c, t) => {
            const st = c[chainKey].find(s => s.name === name);
            if (st) st[f] = lerp(sa[f], sb[f], t);
          });
        }
        addToggle(`${name} — machine source`, groupLabel, sa.machineSource, sb.machineSource, (c, t) => {
          const st = c[chainKey].find(s => s.name === name);
          if (st) st.machineSource = t >= 0.5 ? sb.machineSource : sa.machineSource;
        });
        addToggle(`${name} — electricity location`, groupLabel, sa.elecLoc, sb.elecLoc, (c, t) => {
          const st = c[chainKey].find(s => s.name === name);
          if (st) st.elecLoc = t >= 0.5 ? sb.elecLoc : sa.elecLoc;
        });
      } else {
        const existsA = !!sa, existsB = !!sb;
        addToggle(`${name} — step ${existsA ? "removed" : "added"} in Future scenario`, groupLabel, existsA, existsB, (c, t) => {
          const should = t >= 0.5 ? existsB : existsA;
          const idx = c[chainKey].findIndex(s => s.name === name);
          if (should && idx === -1) c[chainKey].push(deepClone(sb || sa));
          else if (!should && idx !== -1) c[chainKey].splice(idx, 1);
        }, 0);
      }
    }
  }
  diffChain("productionChain", "Production process");
  diffChain("repairChain", "Repair process");

  addToggle("Repairs included", "Repair", A.repair.enabled, B.repair.enabled, (c, t) => {
    c.repair.enabled = t >= 0.5 ? B.repair.enabled : A.repair.enabled;
  }, 0);
  addSlider("Repair material (% of product mass)", "Repair", A.repair.repairMaterialPctOfProduct, B.repair.repairMaterialPctOfProduct, "%", (c, t) => {
    c.repair.repairMaterialPctOfProduct = lerp(A.repair.repairMaterialPctOfProduct, B.repair.repairMaterialPctOfProduct, t);
  });
  addSlider("Expected lifetime", "Repair", A.repair.expectedLifetimeYr, B.repair.expectedLifetimeYr, "yr", (c, t) => {
    c.repair.expectedLifetimeYr = lerp(A.repair.expectedLifetimeYr, B.repair.expectedLifetimeYr, t);
  });
  addSlider("Lifetime extension per repair", "Repair", A.repair.extensionPerRepairYr, B.repair.extensionPerRepairYr, "yr", (c, t) => {
    c.repair.extensionPerRepairYr = lerp(A.repair.extensionPerRepairYr, B.repair.extensionPerRepairYr, t);
  });
  addSlider("Number of repair events", "Repair", A.repair.numRepairs, B.repair.numRepairs, "", (c, t) => {
    c.repair.numRepairs = Math.round(lerp(A.repair.numRepairs, B.repair.numRepairs, t));
  });

  const eolA = A.eol, eolB = B.eol;
  const eolKeys = ["composted", "recycledOpen", "recycledClosed", "incinerated", "landfilled"];
  if (eolKeys.some(k => eolA[k] !== eolB[k])) {
    diffs.push({
      id: uid("d"), type: "slider", label: "End-of-life disposal mix", group: "End of life",
      a: 0, b: 100, unit: "%", order: 1,
      apply: (c, t) => { for (const k of eolKeys) c.eol[k] = lerp(eolA[k], eolB[k], t); },
      isMix: true,
    });
  }
  addToggle("Disposal electricity location", "End of life", eolA.disposalElecLoc, eolB.disposalElecLoc, (c, t) => {
    c.eol.disposalElecLoc = t >= 0.5 ? eolB.disposalElecLoc : eolA.disposalElecLoc;
  });

  return diffs;
}

function previewScenario(A, diffs, tMap) {
  const clone = deepClone(A);
  const ordered = diffs.slice().sort((a, b) => a.order - b.order);
  for (const d of ordered) {
    const tPct = tMap[d.id] !== undefined ? tMap[d.id] : 0;
    d.apply(clone, tPct / 100);
  }
  return clone;
}

function renderCompare() {
  const A = state.scenarios.A, B = state.scenarios.B;
  if (!B) {
    return `<div class="panel"><div class="compare-empty">
      <h3 style="color:var(--ink);margin-bottom:8px;">Nothing to compare yet</h3>
      <p style="font-size:12.5px;">Build a Future scenario first — the Compare tab will detect exactly what you changed and let you slide between the two.</p>
    </div></div>`;
  }
  state.compareDiffs = buildDiffs(A, B);
  const diffs = state.compareDiffs;
  for (const d of diffs) if (state.compareT[d.id] === undefined) state.compareT[d.id] = 0;

  if (diffs.length === 0) {
    return `<div class="panel"><div class="compare-empty">
      <h3 style="color:var(--ink);margin-bottom:8px;">Today and Future are identical</h3>
      <p style="font-size:12.5px;">Change something in the Future scenario tab to see sliders here.</p>
    </div></div>`;
  }

  const groups = {};
  for (const d of diffs) { (groups[d.group] = groups[d.group] || []).push(d); }

  const groupHtml = Object.keys(groups).map(g => {
    const items = groups[g].map(d => {
      const t = state.compareT[d.id];
      if (d.type === "toggle") {
        const isB = t >= 50;
        return `<div class="diff-card">
          <div class="diff-card-top"><span class="name">${d.label}</span></div>
          <div class="diff-toggle">
            <button data-toggle="${d.id}" data-val="0" class="${!isB ? "active" : ""}">Today: ${d.a}</button>
            <button data-toggle="${d.id}" data-val="100" class="${isB ? "active" : ""}">Future: ${d.b}</button>
          </div>
        </div>`;
      }
      const aLabel = d.isMix ? "Today mix" : fmt(d.a) + " " + (d.unit || "");
      const bLabel = d.isMix ? "Future mix" : fmt(d.b) + " " + (d.unit || "");
      return `<div class="diff-card">
        <div class="diff-card-top"><span class="name">${d.label}</span><span class="delta mono" id="deltaval-${d.id}">${t}%</span></div>
        <div class="diff-vals"><span>${aLabel}</span><span>${bLabel}</span></div>
        <input type="range" min="0" max="100" step="1" value="${t}" class="diff-slider" data-slider="${d.id}">
      </div>`;
    }).join("");
    return `<div class="diff-group"><h4>${g}</h4>${items}</div>`;
  }).join("");

  // ranked drivers: hold everything at 0 except one diff at 100, measure delta in the active category
  const catKey = state.category;
  const baseline = runModel(previewScenario(A, diffs, Object.fromEntries(diffs.map(d => [d.id, 0]))));
  const baseNet = baseline.net[catKey];
  const driverRows = diffs.map(d => {
    const tMap = Object.fromEntries(diffs.map(x => [x.id, 0]));
    tMap[d.id] = 100;
    const res = runModel(previewScenario(A, diffs, tMap));
    const delta = res.net[catKey] - baseNet;
    return { label: d.label, delta };
  }).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 8);
  const maxAbs = Math.max(...driverRows.map(r => Math.abs(r.delta)), 1e-9);
  const driverHtml = driverRows.map(r => {
    const w = (Math.abs(r.delta) / maxAbs) * 100;
    const color = r.delta < 0 ? "var(--teal)" : "var(--rust-deep)";
    return `<div class="driver-row">
      <div>
        <div>${r.label}</div>
        <div class="bar-mini"><div class="fill" style="width:${w}%;left:${r.delta < 0 ? 100 - w : 0}%;background:${color};"></div></div>
      </div>
      <div class="mono" style="color:${color};">${r.delta > 0 ? "+" : ""}${fmt(r.delta)}</div>
    </div>`;
  }).join("");

  return `<div class="panel panel-pad">
    <div class="section-head" style="margin-bottom:14px;">
      <h3>What changed, and how much it matters</h3>
      <div style="display:flex;gap:6px;">
        <button class="btn btn-sm" id="btn-reset-compare">Reset to Today</button>
        <button class="btn btn-sm" id="btn-apply-compare">Preview full Future</button>
      </div>
    </div>
    <p class="section-note" style="margin-bottom:18px;">Each slider moves one parameter between Today's value and Future's value, independently — everything else stays put. Drag to see how sensitive the result is to that one change.</p>
    <div style="margin-bottom:22px;">
      <h4 style="font-size:12.5px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px;">Biggest single-lever drivers (${catKey})</h4>
      <div class="driver-list">${driverHtml}</div>
    </div>
    ${groupHtml}
  </div>`;
}

// ============================================================================
// RESULTS PANEL (right column)
// ============================================================================
function currentPreviewResult() {
  if (state.activeTab === "compare" && state.scenarios.B) {
    const scenario = previewScenario(state.scenarios.A, state.compareDiffs, state.compareT);
    return runModel(scenario);
  }
  const key = state.activeTab === "B" ? "B" : "A";
  const scenario = state.scenarios[key] || state.scenarios.A;
  return runModel(scenario);
}

function renderResultsColumn() {
  const result = currentPreviewResult();
  const cat = state.category;
  const netVal = result.net[cat];
  const burdenVal = result.totalBurdens[cat];
  const seqVal = result.seqTotal[cat];
  const circVal = result.eolBenefits[cat];
  const unit = catUnit(cat);

  const allVals = [burdenVal, seqVal, circVal, netVal];
  const maxAbs = Math.max(...allVals.map(v => Math.abs(v)), 1e-9);
  function barRow(label, val, color) {
    const pct = (Math.abs(val) / maxAbs) * 50; // half-track = one side
    const left = val >= 0 ? 50 : 50 - pct;
    const width = pct;
    return `<div class="bar-row">
      <div class="bar-label">${label}</div>
      <div class="bar-track"><div class="zero-line" style="left:50%;"></div>
        <div class="bar-fill" style="left:${left}%;width:${width}%;background:${color};"></div>
      </div>
      <div class="bar-val">${fmt(val)}</div>
    </div>`;
  }

  const seqNote = cat !== "climate change"
    ? `<div style="font-size:11px;color:var(--ink-soft);margin-top:8px;">Sequestration credit is only modelled for climate change — shown as 0 in other categories.</div>`
    : "";

  // itemised breakdown (climate-change-style breakdown, generalised to selected category)
  const items = [];
  items.push(["Material burden", result.materialBurdens[cat], "var(--rust-deep)"]);
  items.push(["Production burden", result.productionBurdens[cat], "var(--rust)"]);
  if (result.scenario.repair.enabled) items.push(["Repair burden", result.repairBurdens[cat], "var(--tan)"]);
  items.push(["End-of-life burden", result.eolBurdens[cat], "var(--purple)"]);
  if (cat === "climate change") {
    items.push(["Sequestration benefit", result.seqTotal[cat], "var(--teal)"]);
  }
  items.push(["Circularity benefit (EoL)", result.eolBenefits[cat], "var(--blue)"]);
  const breakdownHtml = items.filter(([, v]) => Math.abs(v) > 1e-9).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .map(([label, val, color]) => `<div class="breakdown-row">
        <div class="lbl"><span class="breakdown-dot" style="background:${color};"></span>${label}</div>
        <div class="val">${fmt(val)} ${unit}</div>
      </div>`).join("");

  const catOptions = CATEGORIES.map(c => `<option value="${c}" ${c === cat ? "selected" : ""}>${c}</option>`).join("");

  return `
    <div class="results-head">
      <h3 style="color:var(--ink);">Impact result</h3>
      <select class="cat-select" id="category-select">${catOptions}</select>
    </div>
    <div class="net-number ${netVal <= 0 ? "negative" : "positive"}">${fmt(netVal)}<span class="net-unit"> ${unit}</span></div>
    <div class="net-caption">Net impact — burdens minus sequestration &amp; circularity credit${seqNote}</div>
    <div class="bars">
      ${barRow("Burden", burdenVal, "var(--rust)")}
      ${barRow("Sequestration", seqVal, "var(--teal)")}
      ${barRow("Circularity", circVal, "var(--blue)")}
      ${barRow("Net", netVal, "var(--net)")}
    </div>
    <div class="legend">
      <div class="legend-item"><span class="legend-swatch" style="background:var(--rust-deep);"></span>Material</div>
      <div class="legend-item"><span class="legend-swatch" style="background:var(--rust);"></span>Production</div>
      <div class="legend-item"><span class="legend-swatch" style="background:var(--tan);"></span>Repair</div>
      <div class="legend-item"><span class="legend-swatch" style="background:var(--purple);"></span>End of life</div>
      <div class="legend-item"><span class="legend-swatch" style="background:var(--teal);"></span>Sequestration</div>
      <div class="legend-item"><span class="legend-swatch" style="background:var(--blue);"></span>Circularity</div>
    </div>
    <div class="breakdown-list">${breakdownHtml}</div>
  `;
}

// ============================================================================
// EVENT WIRING
// ============================================================================
function setByGenericPath(scKey, restPath, rawValue, isNumber) {
  const scenario = state.scenarios[scKey];
  const parts = restPath.split(".");
  let obj = scenario;
  for (let i = 0; i < parts.length - 1; i++) {
    const p = parts[i];
    obj = obj[isFinite(p) && parts[i - 1] !== undefined ? p : p];
    if (Array.isArray(obj) === false && !isNaN(Number(parts[i + 1]))) {
      // next part is numeric index into this object's array — nothing special needed, JS handles it
    }
  }
  const last = parts[parts.length - 1];
  obj[last] = isNumber ? Number(rawValue) : rawValue;
}
// simpler, robust path setter using array traversal with numeric-string detection
function setPath(root, path, value) {
  const parts = path.split(".");
  let obj = root;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = /^\d+$/.test(parts[i]) ? Number(parts[i]) : parts[i];
    obj = obj[key];
  }
  const lastKey = /^\d+$/.test(parts[parts.length - 1]) ? Number(parts[parts.length - 1]) : parts[parts.length - 1];
  obj[lastKey] = value;
}

function renderLeft() {
  const el = document.getElementById("left-col");
  if (state.activeTab === "compare") el.innerHTML = renderCompare();
  else el.innerHTML = renderScenarioEditor(state.activeTab);
}
function renderResults() {
  document.getElementById("results-col").innerHTML = renderResultsColumn();
  const sel = document.getElementById("category-select");
  if (sel) sel.addEventListener("change", (e) => { state.category = e.target.value; renderResults(); if (state.activeTab === "compare") renderLeft2Sliders(); });
}
function renderLeft2Sliders() {
  // re-render only the driver list + labels without losing slider drag state
  if (state.activeTab === "compare") renderLeft();
}
function renderAll() {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === state.activeTab));
  const bTab = document.querySelector('.tab[data-tab="B"]');
  renderLeft();
  renderResults();
  wireLeftEvents();
}

function updateBadgesAndPills(path, scKey) {
  // BOM total badge
  const bomMatch = path.match(/^([AB])\.(productionBom|repairBom)\.(\d+)\.pct$/);
  if (bomMatch) {
    const [, sc, bomKey] = bomMatch;
    const bom = state.scenarios[sc][bomKey];
    const total = bom.reduce((s, i) => s + Number(i.pct || 0), 0);
    const badge = document.getElementById(`badge-${sc}-${bomKey}`);
    if (badge) { badge.textContent = total.toFixed(1) + "%"; badge.className = "bom-total-badge " + (Math.abs(total - 100) < 0.01 ? "bom-total-ok" : "bom-total-bad"); }
  }
  const eolMatch = path.match(/^([AB])\.eol\.(composted|recycledOpen|recycledClosed|incinerated|landfilled)$/);
  if (eolMatch) {
    const sc = eolMatch[1];
    const e = state.scenarios[sc].eol;
    const total = e.composted + e.recycledOpen + e.recycledClosed + e.incinerated + e.landfilled;
    const badge = document.getElementById(`badge-${sc}-eol`);
    if (badge) { badge.textContent = total.toFixed(1) + "%"; badge.className = "bom-total-badge " + (Math.abs(total - 100) < 0.01 ? "bom-total-ok" : "bom-total-bad"); }
  }
  const retainMatch = path.match(/^([AB])\.(productionChain|repairChain)\.(\d+)\.retainedPct$/);
  if (retainMatch) {
    const [, sc, chainKey, idx] = retainMatch;
    const val = state.scenarios[sc][chainKey][idx].retainedPct;
    const pill = document.getElementById(`pill-${sc}-${chainKey}-${idx}`);
    if (pill) pill.textContent = `${val}% carries to next step`;
  }
}

function wireLeftEvents() {
  const left = document.getElementById("left-col");
  if (!left) return;

  left.oninput = (e) => {
    const t = e.target;
    if (t.dataset.path) {
      const path = t.dataset.path;
      const isNum = t.type === "number";
      let val = isNum ? parseFloat(t.value) : t.value;
      if (isNum && isNaN(val)) val = 0;
      const scKey = path.split(".")[0];
      const rest = path.split(".").slice(1).join(".");
      setPath(state.scenarios[scKey], rest, val);
      // material dropdown changed -> refresh sibling source select + default source
      if (rest.endsWith(".material")) {
        const parts = rest.split(".");
        const bomKey = parts[0], idx = parts[1];
        const item = state.scenarios[scKey][bomKey][idx];
        item.source = defaultSourceFor(item.material);
        renderLeft(); wireLeftEvents();
      }
      updateBadgesAndPills(path, scKey);
      renderResults();
    }
    if (t.dataset.slider) {
      state.compareT[t.dataset.slider] = Number(t.value);
      const dv = document.getElementById("deltaval-" + t.dataset.slider);
      if (dv) dv.textContent = t.value + "%";
      renderResults();
    }
  };

  left.onclick = (e) => {
    const btn = e.target.closest("button, .switch input");
    if (!btn) return;
    const action = btn.dataset ? btn.dataset.action : null;

    if (btn.id === "btn-copy-a-to-b") {
      state.scenarios.B = deepClone(state.scenarios.A);
      renderAll();
      return;
    }
    if (action === "add-bom") {
      state.scenarios[btn.dataset.sc][btn.dataset.bom].push(emptyBomItem());
      renderLeft(); wireLeftEvents(); renderResults();
    }
    if (action === "remove-bom") {
      state.scenarios[btn.dataset.sc][btn.dataset.bom].splice(Number(btn.dataset.idx), 1);
      renderLeft(); wireLeftEvents(); renderResults();
    }
    if (action === "add-step") {
      state.scenarios[btn.dataset.sc][btn.dataset.chain].push(emptyStep());
      renderLeft(); wireLeftEvents(); renderResults();
    }
    if (action === "remove-step") {
      state.scenarios[btn.dataset.sc][btn.dataset.chain].splice(Number(btn.dataset.idx), 1);
      renderLeft(); wireLeftEvents(); renderResults();
    }
    if (action === "toggle-repair") {
      const sc = btn.dataset.sc;
      state.scenarios[sc].repair.enabled = btn.checked;
      renderLeft(); wireLeftEvents(); renderResults();
    }
    if (btn.dataset.toggle) {
      state.compareT[btn.dataset.toggle] = Number(btn.dataset.val);
      renderLeft(); wireLeftEvents(); renderResults();
    }
    if (btn.id === "btn-reset-compare") {
      for (const d of state.compareDiffs) state.compareT[d.id] = 0;
      renderLeft(); wireLeftEvents(); renderResults();
    }
    if (btn.id === "btn-apply-compare") {
      for (const d of state.compareDiffs) state.compareT[d.id] = 100;
      renderLeft(); wireLeftEvents(); renderResults();
    }
  };
}

document.getElementById("tabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (!tab) return;
  state.activeTab = tab.dataset.tab;
  renderAll();
});

// ============================================================================
// EXPORT + RECORDING
// ============================================================================
function buildExportPayload() {
  const A = state.scenarios.A, B = state.scenarios.B;
  const resA = runModel(A);
  const payload = {
    recordedAt: new Date().toISOString(),
    recorder: {
      name: document.getElementById("rec-name").value,
      organisation: document.getElementById("rec-org").value,
      processLabel: document.getElementById("rec-process").value,
    },
    today: { inputs: A, results: { totalBurdens: resA.totalBurdens, seqTotal: resA.seqTotal, eolBenefits: resA.eolBenefits, net: resA.net } },
  };
  if (B) {
    const resB = runModel(B);
    payload.future = { inputs: B, results: { totalBurdens: resB.totalBurdens, seqTotal: resB.seqTotal, eolBenefits: resB.eolBenefits, net: resB.net } };
  }
  return payload;
}

document.getElementById("btn-export").addEventListener("click", () => {
  const payload = buildExportPayload();
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  const label = (document.getElementById("rec-process").value || "raw-impact").replace(/[^a-z0-9-]+/gi, "_");
  a.download = `${label}_${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
});

const modal = document.getElementById("modal-backdrop");
document.getElementById("btn-sheet-settings").addEventListener("click", () => {
  document.getElementById("sheet-url-input").value = state.sheetUrl;
  document.getElementById("apps-script-snippet").textContent =
`function doPost(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = JSON.parse(e.postData.contents);
  sheet.appendRow([
    new Date(), data.recorder.name, data.recorder.organisation, data.recorder.processLabel,
    data.today.results.net["climate change"],
    data.future ? data.future.results.net["climate change"] : "",
    JSON.stringify(data.today.inputs),
    data.future ? JSON.stringify(data.future.inputs) : ""
  ]);
  return ContentService.createTextOutput("OK");
}`;
  modal.classList.add("open");
});
document.getElementById("modal-cancel").addEventListener("click", () => modal.classList.remove("open"));
document.getElementById("modal-save").addEventListener("click", () => {
  state.sheetUrl = document.getElementById("sheet-url-input").value.trim();
  modal.classList.remove("open");
  setRecordStatus(state.sheetUrl ? `Recording target set. This isn't saved between page reloads — keep the URL somewhere safe.` : "Local export only.", "ok");
});

function setRecordStatus(msg, kind) {
  const el = document.getElementById("record-status");
  el.textContent = msg;
  el.className = "record-status" + (kind ? " " + kind : "");
}

document.getElementById("btn-record").addEventListener("click", async () => {
  const payload = buildExportPayload();
  if (!state.sheetUrl) {
    setRecordStatus("No Sheet connected — downloading JSON instead. Set up recording via the settings button above.", "err");
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `raw-impact-record_${Date.now()}.json`;
    a.click();
    return;
  }
  setRecordStatus("Sending…", "");
  try {
    await fetch(state.sheetUrl, {
      method: "POST",
      mode: "no-cors",
      headers: { "Content-Type": "text/plain" },
      body: JSON.stringify(payload),
    });
    setRecordStatus("Recorded to the shared Sheet (no-cors mode can't confirm receipt — check the Sheet).", "ok");
  } catch (err) {
    setRecordStatus("Couldn't reach the Sheet. Check the URL in recording settings.", "err");
  }
});

// ---------- boot ----------------------------------------------------------
renderAll();
