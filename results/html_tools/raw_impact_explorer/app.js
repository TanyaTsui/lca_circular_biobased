// ============================================================================
// app.js — workshop form (typical / min / max / scaled-up / comment for every
// LCI number), results panel, comparison chart, export and submission.
// The model is in calc.js; the cases and baselines in presets.js (generated).
// ============================================================================

// Apps Script Web App that receives submissions (see README "Submitting to a Google Sheet").
// Empty until it is set up; Submit then downloads the CSV instead.
const SUBMIT_URL = "https://script.google.com/macros/s/AKfycbzgW5xs1l5Anp3U7A6OrnGxfDekZ3e5NH-lacjqYPHi_OQVojYRfzhm8-SkEDReZ1MAfw/exec";

// ---------- helpers ----------------------------------------------------------
function deepClone(o) { return JSON.parse(JSON.stringify(o)); }
function esc(s) {
  return String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function fmt(n) {
  if (n === undefined || n === null || isNaN(n)) return "—";
  const a = Math.abs(n);
  if (a === 0) return "0";
  if (a >= 1) return String(Math.round(n * 10) / 10);
  if (a < 1e-4) return n.toExponential(2);
  return String(Number(n.toPrecision(3)));
}
// typed numbers: accept "3,4" as well as "3.4"
function parseNum(s) {
  const t = String(s).trim().replace(",", ".");
  return t === "" ? NaN : Number(t);
}
function numOrBlank(v) { return v === null || v === undefined || v === "" || isNaN(v) ? "" : v; }
function getPath(root, path) {
  return path.split(".").reduce((o, k) => (o === undefined ? undefined : o[/^\d+$/.test(k) ? Number(k) : k]), root);
}
// Display-only relabels; the canonical value stays in state and is what calc.js looks up.
const DISPLAY_LABELS = { "Soft wood": "wood, soft", "Hard wood": "wood, hard", "co-product": "by-product" };
function disp(v) { return DISPLAY_LABELS[v] !== undefined ? DISPLAY_LABELS[v] : v; }
const ROUTE_LABELS = { composted: "Composted", recycled_open: "Recycled (open loop)", recycled_closed: "Recycled (closed loop)",
  incinerated: "Incinerated", landfilled: "Landfilled" };
// which product version a production step (usedIn) or repair (circularity.repairIn) belongs to
const VERSIONS = [["both", "prototype & scaled-up"], ["prototype", "prototype only"], ["scaledUp", "scaled-up only"]];
const versionOf = c => (c && c.v) || "both";
const STEP_FIELDS = [   // [field, label, unit, sheet parameter]
  ["kgMachine", "Machine weight", "kg", "machine weight"],
  ["powerKW", "Power", "kW", "power"],
  ["rateKgHr", "Output rate", "kg/hr", "output rate"],
  ["lifetimeHrs", "Machine lifetime", "hrs", "machine lifetime"],
  ["yieldPct", "Process yield", "%", "process yield"],
];
function repairsNeeded(expected, extension, serviceLife) {     // raw_lca.cases.repairs_needed
  if (expected >= serviceLife || extension <= 0) return 0;
  return Math.ceil((serviceLife - expected) / extension - 1e-9);
}

// ---------- state --------------------------------------------------------------
const state = {
  caseId: null,
  meta: null,          // the RAW_CASES entry (spec, rsl, baselines, names)
  inputs: null,        // editable inputs (changed by the form)
  original: {},        // sheet key -> the preset's {v, min, max, up} (for "changed" markers)
  category: "climate change",
  scaleT: 0,           // prototype (0) -> scaled-up (100)
  bgT: 0,              // today (0) -> 2050 (100)
  mc: null, mcStale: true,
  expanded: {},
  sensKey: "scaledUp",  // which result the sensitivity ranking is for: prototype / scaledUp
  submitUrl: SUBMIT_URL,
};
const caseMeta = () => ({ specValue: state.meta.spec.value, rsl: state.meta.rsl });

// ---------- every input as a sheet row (export, submission, change markers) ---------
function sheetKey(sheet) { return [sheet.stage, sheet.item, sheet.qualifier || "", sheet.parameter].join("|"); }
// [{path, label, p, kind}] in form order; kind = "num" | "choice"; optional = may be left blank
function inputList(inp) {
  const out = [];
  const pr = inp.product;
  out.push({ path: "product.density", label: "Material density", p: pr.density, kind: "num" });
  out.push({ path: "product.performance", label: "Building component performance", p: pr.performance, kind: "num", optional: true });
  out.push({ path: "product.savings", label: "Material savings from RAW optimisation", p: pr.savings, kind: "num" });
  inp.productionBom.forEach((x, i) => out.push({ path: `productionBom.${i}.share`, label: `${disp(x.material)} (${disp(x.source)})`, p: x.share, kind: "num" }));
  out.push({ path: "location", label: "Electricity location", p: inp.location, kind: "choice" });
  const steps = (list, key, stage) => list.forEach((s, i) => {
    STEP_FIELDS.forEach(([f, lbl]) => out.push({ path: `${key}.${i}.${f}`, label: `${s.name}: ${lbl.toLowerCase()}`, p: s[f], kind: "num" }));
    out.push({ path: `${key}.${i}.machineSource`, label: `${s.name}: machine source`, p: s.machineSource, kind: "choice" });
    if (s.usedIn) out.push({ path: `${key}.${i}.usedIn`, label: `${s.name}: used in`, p: s.usedIn, kind: "choice" });
  });
  steps(inp.productionChain, "productionChain", "production");
  const c = inp.circularity;
  if (c.enabled && c.repairIn) out.push({ path: "circularity.repairIn", label: "Repair in", p: c.repairIn, kind: "choice" });
  out.push({ path: "circularity.materialPct", label: "Repair material", p: c.materialPct, kind: "num" });
  out.push({ path: "circularity.expectedLifetime", label: "Expected lifetime without repair", p: c.expectedLifetime, kind: "num" });
  out.push({ path: "circularity.extension", label: "Lifetime extension per repair event", p: c.extension, kind: "num" });
  out.push({ path: "circularity.numRepairs", label: "Number of repair events", p: c.numRepairs, kind: "num" });
  if (c.enabled) {
    inp.repairBom.forEach((x, i) => out.push({ path: `repairBom.${i}.share`, label: `Repair: ${disp(x.material)} (${disp(x.source)})`, p: x.share, kind: "num" }));
    steps(inp.repairChain, "repairChain", "repair");
  }
  ROUTES.forEach(r => out.push({ path: `eol.${r}`, label: `End of life: ${ROUTE_LABELS[r].toLowerCase()}`, p: inp.eol[r], kind: "num" }));
  for (const e of out) e.sheet = e.p.sheet || e.sheet;
  return out;
}
function buildOriginal(inputs) {
  const m = {};
  for (const e of inputList(inputs)) m[sheetKey(e.sheet)] = { v: e.p.v, min: e.p.min, max: e.p.max, up: e.p.up, unit: e.p.unit };
  return m;
}
const isBlank = x => x === null || x === undefined || x === "" || (typeof x === "number" && isNaN(x));
const same = (a, b) => (isBlank(a) && isBlank(b)) || (typeof a === "number" && typeof b === "number" ? Math.abs(a - b) < 1e-9 : String(a) === String(b));
function changedFields(e) {
  const o = state.original[sheetKey(e.sheet)];
  if (!o) return ["new"];
  return ["v", "min", "max", "up", "unit"].filter(f => (f in e.p || f in o) && !same(e.p[f], o[f]));
}
function warnings(e) {
  const p = e.p, w = [];
  if (e.kind !== "num") return w;
  if (e.optional && ["v", "min", "max", "up"].every(f => numOrBlank(p[f]) === "")) return w;
  const v = Number(p.v);
  if (!isFinite(v)) w.push("typical value missing");
  if (v === 0 && ["output rate", "machine lifetime", "process yield"].includes(p.sheet && p.sheet.parameter)) w.push("cannot be 0");
  if (isFinite(p.min) && p.min > v) w.push("min is above typical");
  if (isFinite(p.max) && p.max < v) w.push("max is below typical");
  const unit = (p.sheet && p.sheet.unit) || "";
  if (unit.startsWith("%")) {
    const bad = [["typical", p.v], ["min", p.min], ["max", p.max]].filter(([, x]) => isFinite(x) && (x < 0 || x > 100)).map(([k]) => k);
    if (bad.length) w.push(`${bad.join(", ")} outside 0–100 %`);
  } else if (["v", "min", "max", "up"].some(f => isFinite(p[f]) && p[f] < 0)) {
    w.push("negative value");
  }
  return w;
}
function rowClasses(e) {
  const cls = [];
  if (changedFields(e).length) cls.push("changed");
  if (e.p.comment) cls.push("commented");
  if (warnings(e).length) cls.push("warn");
  return cls.join(" ");
}

// ============================================================================
// FORM
// ============================================================================
function infoTitle(sheet) {
  if (!sheet) return "";
  const parts = [sheet.description, sheet.source && `Source: ${sheet.source}`,
    sheet.comments && sheet.comments !== sheet.description && `Sheet comments: ${sheet.comments}`, sheet.adjusted].filter(Boolean);
  return parts.join("\n\n");
}
function infoIcon(sheet) {
  const t = infoTitle(sheet);
  return t ? `<button type="button" class="info" data-tip="${esc(t)}" aria-label="About this number">i</button>` : "";
}
function tableHead(withUp, opts = {}) {
  return `<div class="rrow rhead${withUp ? " with-up" : ""}${opts.cls ? " " + opts.cls : ""}">
    <div>${opts.first || "Parameter"}</div><div>${opts.typical || (withUp ? "Prototype" : "Typical")}</div><div>Min</div><div>Max</div>${withUp ? "<div>Scaled-up</div>" : ""}<div>Comments</div></div>`;
}
const hasUp = p => p.up !== null && p.up !== undefined && p.up !== "" && isFinite(p.up);
// the scaled-up cell: blank in the data (= same as prototype) is shown as the prototype value, greyed
function upCellHtml(e, p) {
  const follow = !hasUp(p);
  const cls = follow ? "up-follow" : (same(p.up, p.v) ? "" : "up-diff");
  return `<input type="text" inputmode="decimal" data-num="1" class="${cls}" value="${numOrBlank(follow ? p.v : p.up)}" data-path="${e.path}" data-field="up" title="Value at large scale. Grey = same as the prototype; type a value to change it, clear it to follow the prototype again.">`;
}
// One number: typical | min | max | (scaled-up) | comment. opts: withUp (table has the column), labelHtml, disabled, hint
function rangeRow(e, opts = {}) {
  const p = e.p, unit = (p.sheet && p.sheet.unit) || opts.unit || "";
  const dis = opts.disabled ? "disabled" : "";
  const upCell = !opts.withUp ? "" : ("up" in p && !opts.noUp ? upCellHtml(e, p) : `<div class="na">—</div>`);
  const label = opts.labelHtml || `<span>${esc(opts.label || e.label)}${unit && unit !== "-" ? ` <span class="unit">(${esc(unit)})</span>` : ""}</span>`;
  return `<div class="rrow${opts.withUp ? " with-up" : ""}${opts.cls ? " " + opts.cls : ""} ${rowClasses(e)}" data-row="${e.path}">
    <div class="rlabel"><span class="mark"></span>${label}${infoIcon(p.sheet)}${opts.hint ? `<div class="rhint">${opts.hint}</div>` : ""}</div>
    <input type="text" inputmode="decimal" data-num="1" value="${numOrBlank(p.v)}" data-path="${e.path}" data-field="v" ${dis}>
    <input type="text" inputmode="decimal" data-num="1" value="${numOrBlank(p.min)}" data-path="${e.path}" data-field="min" ${dis}>
    <input type="text" inputmode="decimal" data-num="1" value="${numOrBlank(p.max)}" data-path="${e.path}" data-field="max" ${dis}>
    ${upCell}
    <input type="text" class="comment" value="${esc(p.comment)}" data-path="${e.path}" data-field="comment" placeholder="comment" ${dis}>
    <div class="rwarn">${warnings(e).map(esc).join(" · ")}</div>
  </div>`;
}
// One choice value + comment (spans the typical/min/max/scaled-up columns)
function wideRow(e, control, opts = {}) {
  return `<div class="rrow wide${opts.withUp ? " with-up" : ""} ${rowClasses(e)}" data-row="${e.path}">
    <div class="rlabel"><span class="mark"></span><span>${esc(opts.label || e.label)}</span>${infoIcon(e.p.sheet)}</div>
    <div class="wide-control">${control}</div>
    <input type="text" class="comment" value="${esc(e.p.comment)}" data-path="${e.path}" data-field="comment" placeholder="comment">
    <div class="rwarn"></div>
  </div>`;
}
function entry(path, label) {
  const e = inputList(state.inputs).find(x => x.path === path);
  return Object.assign({}, e, label ? { label } : {});
}
function versionSelect(path, value) {
  return `<select data-path="${path}" data-field="v" data-rerender="1">${VERSIONS.map(([v, l]) => `<option value="${v}" ${v === value ? "selected" : ""}>${l}</option>`).join("")}</select>`;
}
function select(path, value, options, field = "v") {
  return `<select data-path="${path}" data-field="${field}">${options.map(o => `<option value="${esc(o)}" ${o === value ? "selected" : ""}>${esc(disp(o))}</option>`).join("")}</select>`;
}
function totalBadge(id, values) {
  const total = values.reduce((s, x) => s + (Number(x) || 0), 0);
  return `<span class="bom-total-badge ${Math.abs(total - 100) < 0.01 ? "bom-total-ok" : "bom-total-bad"}" id="${id}">${total.toFixed(1)}%</span>`;
}

function productKg(inp) {
  return state.meta.spec.value * Number(inp.product.density.v) * (1 - Number(inp.product.savings.v) / 100);
}
function renderProduct() {
  const m = state.meta, perf = entry("product.performance");
  const perfLabel = `<span>Building component performance</span>
    <input type="text" class="unit-input" value="${esc(perf.p.unit)}" data-path="product.performance" data-field="unit" placeholder="unit, e.g. kN·m">`;
  return `<div class="section">
    <div class="section-head"><h3>1 · Product specifications</h3><span class="hint">functional unit: ${esc(m.spec.label)} ${fmt(m.spec.value)} ${esc(m.spec.unit)}, ${fmt(m.rsl)} yr</span></div>
    <p class="section-note">${esc(m.fuName)}. Product mass = ${esc(m.spec.label)} × material density × (1 − savings) = <b id="product-kg">${fmt(productKg(state.inputs))}</b> kg (prototype).</p>
    <div class="rtable">${tableHead(true)}
      ${rangeRow(entry("product.density"), { withUp: true })}
      ${rangeRow(perf, { withUp: true, labelHtml: perfLabel, hint: "e.g. structural strength; recorded only, not used in the calculation" })}
      ${rangeRow(entry("product.savings"), { withUp: true, hint: "compared with the non-optimised product of the density above" })}
    </div>
  </div>`;
}
function bomEditor(key, title, withNote) {
  const bom = state.inputs[key], withUp = key === "productionBom";
  const rows = bom.map((x, i) => {
    const opts = RAW_DATA.bomMaterials[x.material] || [x.source];
    const pick = `<div class="bom-pick">${select(`${key}.${i}.material`, x.material, Object.keys(RAW_DATA.bomMaterials), "material")}
      ${select(`${key}.${i}.source`, x.source, opts, "source")}
      <button class="icon-btn" data-action="remove-bom" data-key="${key}" data-idx="${i}" title="remove this material" aria-label="remove">×</button></div>`;
    return rangeRow(entry(`${key}.${i}.share`), { withUp, labelHtml: pick, cls: "bom" });
  }).join("");
  return `<div class="sub-head"><h4>${title}</h4>${totalBadge(`badge-${key}`, bom.map(x => x.share.v))}</div>
    ${withNote ? `<p class="section-note">${withNote}</p>` : ""}
    <div class="rtable">${tableHead(withUp, { first: "Material · source", typical: withUp ? "Prototype %" : "Share %", cls: "bom" })}${rows}</div>
    <button class="add-row-btn" data-action="add-bom" data-key="${key}">+ add material</button>`;
}
function chainEditor(key, scalable) {
  const list = state.inputs[key];
  const cards = list.map((s, i) => {
    const ms = entry(`${key}.${i}.machineSource`);
    const used = scalable ? versionOf(s.usedIn) : "both", withUp = scalable && used === "both";
    const rows = STEP_FIELDS.map(([f, lbl]) => rangeRow(entry(`${key}.${i}.${f}`), { withUp, label: lbl })).join("");
    const usedRow = scalable && s.usedIn ? wideRow(entry(`${key}.${i}.usedIn`), versionSelect(`${key}.${i}.usedIn`, used), { withUp, label: "Used in" }) : "";
    const note = used === "prototype" ? "Only in the prototype: left out of the scaled-up product."
      : used === "scaledUp" ? "Only in the scaled-up product: these are its values; the prototype doesn't have this step." : "";
    const card = `<div class="item-card${used !== "both" ? " only-one" : ""}">
      <div class="item-card-head">
        <div class="item-title"><span class="item-index">${i + 1}</span>
          <input type="text" class="step-name" value="${esc(s.name)}" data-path="${key}.${i}.name" data-field="name"></div>
        <div class="item-actions">
          <button class="remove-btn" data-action="move-step" data-key="${key}" data-idx="${i}" data-dir="-1" ${i === 0 ? "disabled" : ""} title="move up">&uarr;</button>
          <button class="remove-btn" data-action="move-step" data-key="${key}" data-idx="${i}" data-dir="1" ${i === list.length - 1 ? "disabled" : ""} title="move down">&darr;</button>
          <button class="remove-btn" data-action="remove-step" data-key="${key}" data-idx="${i}">remove</button>
        </div>
      </div>
      ${note ? `<p class="section-note only-note">${note}</p>` : ""}
      <div class="rtable">${tableHead(withUp, { typical: used === "scaledUp" ? "Scaled-up" : withUp ? "Prototype" : scalable ? "Prototype" : "Typical" })}${usedRow}${rows}
        ${wideRow(ms, select(`${key}.${i}.machineSource`, ms.p.v, ["virgin", "recycled"]), { withUp, label: "Machine source" })}</div>
    </div>`;
    const conn = i < list.length - 1 ? `<div class="flow-connector"><div class="line"></div><span class="arrow">&darr;</span>
      <span class="pct-pill" id="pill-${key}-${i}">${fmt(Number(s.yieldPct.v))}% carries to next step</span></div>` : "";
    return card + conn;
  }).join("");
  return `<div class="card-list">${cards}</div>
    <button class="add-row-btn" data-action="add-step" data-key="${key}">+ add fabrication step</button>`;
}
function renderFabrication() {
  const loc = entry("location");
  return `<div class="section">
    <div class="section-head"><h3>3 · Fabrication steps</h3><span class="hint">solved backward from the product mass</span></div>
    <p class="section-note">Machine weight, power, output rate and lifetime give the machine wear and electricity per step; process yield is the share of the input that leaves the step as good output. <b>Scaled-up</b>: the value at large scale; grey = same as the prototype, highlighted = different.</p>
    <div class="rtable">${wideRow(loc, select("location", loc.p.v, RAW_DATA.locations))}</div>
    <p class="section-note" style="margin-top:6px;">The location is used for the electricity of every step (and repair step) and for the electricity displaced by energy recovery at end of life.</p>
    ${chainEditor("productionChain", true)}
  </div>`;
}
function renderCircularity() {
  const c = state.inputs.circularity, m = state.meta;
  const need = repairsNeeded(Number(c.expectedLifetime.v), Number(c.extension.v), m.rsl);
  const off = !c.enabled;
  const rIn = versionOf(c.repairIn), oneV = c.enabled && rIn !== "both";
  const oneNote = !oneV ? "" : `; ${rIn === "scaledUp" ? "scaled-up" : "prototype"} only, one set of values`;
  return `<div class="section">
    <div class="section-head"><h3>4 · Circularity specifications</h3>
      <label class="toggle-row"><span class="switch"><input type="checkbox" ${c.enabled ? "checked" : ""} data-action="toggle-repair"><span class="slider"></span></span>
      <span class="hint">${c.enabled ? "repair included" : "no repair"}</span></label></div>
    <p class="section-note">Service life = expected lifetime + number of repairs × extension. Results are scaled to the ${fmt(m.rsl)}-yr functional unit (× ${fmt(m.rsl)} / service life).</p>
    <div class="rtable${off ? " is-off" : ""}">${tableHead(true)}
      ${c.enabled && c.repairIn ? wideRow(entry("circularity.repairIn"), versionSelect("circularity.repairIn", rIn), { withUp: true, label: "Repair in" }) : ""}
      ${rangeRow(entry("circularity.materialPct", "Repair material"), { withUp: true, noUp: oneV, disabled: off, hint: "per repair event, % of product mass" + oneNote })}
      ${rangeRow(entry("circularity.expectedLifetime", "Expected lifetime without repair"), { withUp: true })}
      ${rangeRow(entry("circularity.extension", "Lifetime extension per repair event"), { withUp: true, noUp: oneV, disabled: off, hint: oneNote.replace(/^; /, "") })}
      ${rangeRow(entry("circularity.numRepairs", "Number of repair events"), { withUp: true, noUp: oneV, disabled: off, hint: `<span id="repairs-hint">To reach ${fmt(m.rsl)} yr the model needs ${need} repair${need === 1 ? "" : "s"}.</span>` })}
    </div>
  </div>`;
}
function renderRepair() {
  if (!state.inputs.circularity.enabled) {
    return `<div class="section"><div class="section-head"><h3>5 · Repair: materials and fabrication</h3><span class="hint">switch repair on in section 4</span></div></div>`;
  }
  return `<div class="section">
    <div class="section-head"><h3>5 · Repair: materials and fabrication</h3>${versionOf(state.inputs.circularity.repairIn) !== "both" ? `<span class="hint">${versionOf(state.inputs.circularity.repairIn) === "scaledUp" ? "scaled-up product only" : "prototype only"}</span>` : ""}</div>
    <button class="add-row-btn" data-action="copy-prod-bom" style="margin-bottom:10px;">⧉ Copy bill of materials from production</button>
    ${bomEditor("repairBom", "Repair bill of materials")}
    <div class="sub-head" style="margin-top:16px;"><h4>Repair fabrication steps</h4></div>
    <button class="add-row-btn" data-action="copy-prod-chain" style="margin-bottom:10px;">⧉ Copy fabrication steps from production</button>
    ${chainEditor("repairChain", false)}
  </div>`;
}
function renderEol() {
  return `<div class="section">
    <div class="section-head"><h3>6 · End of life</h3>${totalBadge("badge-eol", ROUTES.map(r => state.inputs.eol[r].v))}</div>
    <p class="section-note">What happens to the product (and the repair material) at end of life, as % of the waste. Shares are re-normalised to 100 %.</p>
    <div class="rtable">${tableHead(false)}${ROUTES.map(r => rangeRow(entry(`eol.${r}`, ROUTE_LABELS[r]))).join("")}</div>
  </div>`;
}
function renderLeft() {
  const nChanged = inputList(state.inputs).filter(e => changedFields(e).length).length;
  const nComments = inputList(state.inputs).filter(e => e.p.comment).length;
  document.getElementById("left-col").innerHTML = `<div class="panel">
    <div class="section intro">
      <div class="section-head"><h3>${esc(state.meta.name)}</h3><span class="hint" id="change-count">${nChanged} changed · ${nComments} commented</span></div>
      <p class="section-note">All numbers are pre-filled from the RAW LCA sheet (snapshot ${esc(RAW_DATA.snapshot)}). Please check every value: correct the typical value, the min–max range (how low / high it could realistically be) and add a comment where useful. Hover <span class="info">i</span> for the sheet's source and notes. <span class="legend-inline"><span class="mark changed"></span>changed &nbsp;<span class="mark commented"></span>commented &nbsp;<span class="mark warn"></span>check</span></p>
    </div>
    ${renderProduct()}
    <div class="section">
      <div class="section-head"><h3>2 · Bill of materials</h3></div>
      ${bomEditor("productionBom", "Production", "Composition of the material entering the first fabrication step, % of its mass. Shares are re-normalised to 100 %.")}
    </div>
    ${renderFabrication()}
    ${renderCircularity()}
    ${renderRepair()}
    ${renderEol()}
  </div>`;
}

// refresh the markers of one row + badges after a value edit, without re-rendering the form
function refreshRow(path) {
  const e = inputList(state.inputs).find(x => x.path === path);
  const row = document.querySelector(`[data-row="${CSS.escape(path)}"]`);
  if (e && row) {
    ["changed", "commented", "warn"].forEach(c => row.classList.remove(c));
    rowClasses(e).split(" ").filter(Boolean).forEach(c => row.classList.add(c));
    const w = row.querySelector(".rwarn");
    if (w) w.textContent = warnings(e).join(" · ");
    const up = row.querySelector('[data-field="up"]');
    if (up && document.activeElement !== up) up.outerHTML = upCellHtml(e, e.p);
    else if (up) up.className = hasUp(e.p) ? (same(e.p.up, e.p.v) ? "" : "up-diff") : "up-follow";
  }
  for (const key of ["productionBom", "repairBom"]) {
    const b = document.getElementById(`badge-${key}`);
    if (b) b.outerHTML = totalBadge(`badge-${key}`, state.inputs[key].map(x => x.share.v));
  }
  const be = document.getElementById("badge-eol");
  if (be) be.outerHTML = totalBadge("badge-eol", ROUTES.map(r => state.inputs.eol[r].v));
  const m = state.meta, inp = state.inputs;
  const kg = document.getElementById("product-kg");
  if (kg) kg.textContent = fmt(productKg(inp));
  const c = inp.circularity, need = repairsNeeded(Number(c.expectedLifetime.v), Number(c.extension.v), m.rsl);
  const rh = document.getElementById("repairs-hint");
  if (rh) rh.textContent = `To reach ${fmt(m.rsl)} yr the model needs ${need} repair${need === 1 ? "" : "s"}.`;
  const pm = path.match(/^(productionChain|repairChain)\.(\d+)\.yieldPct$/);
  if (pm) { const pill = document.getElementById(`pill-${pm[1]}-${pm[2]}`); if (pill) pill.textContent = `${fmt(Number(getPath(inp, path).v))}% carries to next step`; }
  const list = inputList(inp);
  const cc = document.getElementById("change-count");
  if (cc) cc.textContent = `${list.filter(x => changedFields(x).length).length} changed · ${list.filter(x => x.p.comment).length} commented`;
}

// ---------- new rows -----------------------------------------------------------
function newParam(v, stage, item, qualifier, parameter, unit, scalable) {
  const p = { v, min: v, max: v, dist: "triangular", comment: "",
    sheet: { stage, item, qualifier, parameter, unit, description: "", source: "", status: "", comments: "" } };
  if (scalable) p.up = null;
  return p;
}
function newBomItem(stage) {
  const m = Object.keys(RAW_DATA.bomMaterials)[0], src = RAW_DATA.bomMaterials[m][0];
  return { material: m, source: src, share: newParam(0, stage, m, src, "share of input mass", "%", stage === "production") };
}
const NEW_STEP_VALUES = { kgMachine: 50, powerKW: 1, rateKgHr: 5, lifetimeHrs: 15000, yieldPct: 95 };   // starting point, to be edited
function newStep(stage, name = "New step") {
  const s = { name };
  for (const [f, , unit, param] of STEP_FIELDS) {
    s[f] = newParam(NEW_STEP_VALUES[f], stage, name, "", param, unit, stage === "production");
  }
  s.machineSource = { v: "virgin", comment: "", sheet: { stage, item: name, qualifier: "", parameter: "machine source", unit: "-" } };
  if (stage === "production") s.usedIn = newUsedIn(name);
  return s;
}
function newUsedIn(name, v = "both") {
  return { v, comment: "", sheet: { stage: "production", item: name, qualifier: "", parameter: "used in", unit: "-",
    description: "Not on the sheet yet: whether this step is part of the prototype, the scaled-up product, or both.", source: "", comments: "" } };
}
function retagStep(s, stage, name) {   // keep sheet refs in step with the step name / stage
  for (const [f] of STEP_FIELDS) { s[f].sheet.item = name; s[f].sheet.stage = stage; }
  s.machineSource.sheet.item = name; s.machineSource.sheet.stage = stage;
  if (s.usedIn) s.usedIn.sheet.item = name;
}
// inputs exported by an earlier version of the tool: add what is missing
function upgradeInputs(inp) {
  for (const s of inp.productionChain || []) if (!s.usedIn) s.usedIn = newUsedIn(s.name);
  const c = inp.circularity;
  if (c && !c.repairIn) c.repairIn = { v: "both", comment: "", sheet: { stage: "use", item: "product", qualifier: "", parameter: "repair in", unit: "-",
    description: "Not on the sheet yet: whether the prototype, the scaled-up product or both are repaired.", source: "", comments: "" } };
  return inp;
}

// ---------- form events ----------------------------------------------------------
function wireLeft() {
  const left = document.getElementById("left-col");
  left.oninput = (ev) => {
    const t = ev.target, path = t.dataset.path, field = t.dataset.field;
    if (!path || !field) return;
    if (field === "name") {                                   // step renamed
      const s = getPath(state.inputs, path.replace(/\.name$/, ""));
      s.name = t.value;
      retagStep(s, path.startsWith("production") ? "production" : "repair", t.value);
      return scheduleResults();
    }
    if (field === "material" || field === "source") return;   // handled on change
    const p = getPath(state.inputs, path);
    if (field === "comment") p.comment = t.value;
    else if (t.dataset.num) p[field] = t.value.trim() === "" ? (field === "up" ? null : NaN) : parseNum(t.value);
    else p[field] = t.value;
    refreshRow(path);
    if (field !== "comment") scheduleResults();
  };
  left.onchange = (ev) => {
    const t = ev.target, path = t.dataset.path, field = t.dataset.field;
    if (field === "material" || field === "source") {
      const item = getPath(state.inputs, path.replace(/\.(material|source)$/, ""));
      item[field] = t.value;
      if (field === "material") item.source = (RAW_DATA.bomMaterials[item.material] || [item.source])[0];
      item.share.sheet.item = item.material; item.share.sheet.qualifier = item.source;
      rerender();
    } else if (t.tagName === "SELECT" && t.dataset.rerender) {
      getPath(state.inputs, path).v = t.value;
      rerender();                                // columns change with the product version
    } else if (t.tagName === "SELECT") {
      refreshRow(path); scheduleResults();
    } else if (field === "up") {
      setTimeout(() => refreshRow(path), 0);   // focus has left: show "same as prototype" again if cleared
    }
  };
  left.onclick = (ev) => {
    const b = ev.target.closest("button, .switch input");
    if (!b || !b.dataset.action) return;
    const a = b.dataset.action, key = b.dataset.key, i = Number(b.dataset.idx), inp = state.inputs;
    const stage = key && key.startsWith("repair") ? "repair" : "production";
    if (a === "add-bom") inp[key].push(newBomItem(stage));
    if (a === "remove-bom") inp[key].splice(i, 1);
    if (a === "add-step") inp[key].push(newStep(stage));
    if (a === "remove-step") inp[key].splice(i, 1);
    if (a === "move-step") {
      const j = i + Number(b.dataset.dir);
      if (j >= 0 && j < inp[key].length) [inp[key][i], inp[key][j]] = [inp[key][j], inp[key][i]];
    }
    if (a === "copy-prod-bom") {
      inp.repairBom = deepClone(inp.productionBom);
      inp.repairBom.forEach(x => { x.share.sheet.stage = "repair"; delete x.share.up; });
    }
    if (a === "copy-prod-chain") {
      inp.repairChain = deepClone(inp.productionChain);
      inp.repairChain.forEach(s => { retagStep(s, "repair", s.name); delete s.usedIn; for (const [f] of STEP_FIELDS) delete s[f].up; });
    }
    if (a === "toggle-repair") {
      inp.circularity.enabled = b.checked;
      const c = inp.circularity;
      if (b.checked && Number(c.numRepairs.v) === 0) {
        const n = repairsNeeded(Number(c.expectedLifetime.v), Number(c.extension.v), state.meta.rsl);
        c.numRepairs.v = n; c.numRepairs.min = Math.min(c.numRepairs.min, n); c.numRepairs.max = Math.max(c.numRepairs.max, n);
      }
    }
    rerender();
  };
}
function rerender() {
  const y = window.scrollY;
  renderLeft();
  window.scrollTo(0, y);
  scheduleResults();
}

// ============================================================================
// RESULTS
// ============================================================================
const COLORS = { fossil: "#5f655e", bio: "#9aa293", prototype: "#d9a066", scaledUp: "#b5651d", scaledUp2050: "#7a3d10" };
function catIndex() { return CATEGORIES.indexOf(state.category); }
function unit() { return RAW_DATA.units[state.category] || ""; }

const MC_DRAWS = 500;      // same as the baselines' Monte Carlo in build_data.py
let mcTimer = null, typTimer = null;
// sliderOnly: only the slider position changed, so the chart's Monte Carlo is still valid
function scheduleResults(sliderOnly = false) {
  if (!sliderOnly) state.mcStale = true;
  clearTimeout(typTimer);
  typTimer = setTimeout(renderResultsBody, 30);
  clearTimeout(mcTimer);
  mcTimer = setTimeout(runMC, 350);
}
function runMC() {
  try {
    state.mc = runMonteCarlo(state.inputs, caseMeta(), [
      { key: "current", scaleT: state.scaleT / 100, bgT: state.bgT / 100 },
      { key: "prototype", scaleT: 0, bgT: 0 },
      { key: "scaledUp", scaleT: 1, bgT: 0 },
      { key: "scaledUp2050", scaleT: 1, bgT: 1 },
    ], MC_DRAWS);
    state.mcPos = [state.scaleT, state.bgT];
    state.mcStale = false;
  } catch (err) {
    state.mc = null;
  }
  renderResultsBody();
}

function renderResultsControls() {
  const charted = RAW_DATA.chartedCategories, others = CATEGORIES.filter(c => !charted.includes(c));
  const opt = c => `<option value="${esc(c)}" ${c === state.category ? "selected" : ""}>${esc(RAW_DATA.categoryLabels[c] || c)}</option>`;
  const fut = RAW_DATA.scenarioLabels[RAW_DATA.scenarios.future];
  document.getElementById("results-controls").innerHTML = `
    <div class="results-head">
      <h3 style="color:var(--ink);">Impact result</h3>
      <select class="cat-select" id="category-select"><optgroup label="Main categories">${charted.map(opt).join("")}</optgroup>
        <optgroup label="Other categories">${others.map(opt).join("")}</optgroup></select>
    </div>
    <div class="slider-card">
      <div class="slider-col">
        <div class="slider-top"><span class="name">Prototype &rarr; Scaled-up</span><span class="mono" id="scale-label">${state.scaleT}%</span></div>
        <input type="range" min="0" max="100" step="1" value="${state.scaleT}" class="diff-slider" id="scale-slider" aria-label="Prototype to scaled-up">
      </div>
      <div class="slider-col">
        <div class="slider-top"><span class="name">Today &rarr; ${esc(fut)}</span><span class="mono" id="bg-label">${state.bgT}%</span></div>
        <input type="range" min="0" max="100" step="1" value="${state.bgT}" class="diff-slider" id="bg-slider" aria-label="Today to ${esc(fut)} background">
      </div>
    </div>`;
  document.getElementById("category-select").onchange = (e) => { state.category = e.target.value; renderResultsBody(); };
  document.getElementById("scale-slider").oninput = (e) => {
    state.scaleT = Number(e.target.value); document.getElementById("scale-label").textContent = state.scaleT + "%"; scheduleResults(true);
  };
  document.getElementById("bg-slider").oninput = (e) => {
    state.bgT = Number(e.target.value); document.getElementById("bg-label").textContent = state.bgT + "%"; scheduleResults(true);
  };
}

function rangeText(r, ci) {
  if (!r) return "";
  return `5–95 %: ${fmt(r.lo[ci])} to ${fmt(r.hi[ci])}`;
}
function renderResultsBody() {
  const ci = catIndex(), u = unit();
  let result;
  try { result = runCase(state.inputs, caseMeta(), state.scaleT / 100, state.bgT / 100); }
  catch (err) {
    document.getElementById("results-body").innerHTML = `<div class="error-box">Can't compute: ${esc(err.message)}</div>`;
    return;
  }
  const val = k => result[k][ci];
  const net = val("net"), burden = val("burdens"), seq = val("sequestration"), circ = val("circularity");
  const repairOn = result.info.nRepairs > 0;
  const mcCur = state.mc && !state.mcStale && state.mcPos[0] === state.scaleT && state.mcPos[1] === state.bgT ? state.mc.current : null;
  const maxAbs = Math.max(Math.abs(burden), Math.abs(seq), Math.abs(circ), Math.abs(net), 1e-12);
  const barRow = (label, v, color) => {
    const w = Math.abs(v) / maxAbs * 50, left = v >= 0 ? 50 : 50 - w;
    return `<div class="bar-row"><div class="bar-label">${label}</div>
      <div class="bar-track"><div class="zero-line" style="left:50%;"></div><div class="bar-fill" style="left:${left}%;width:${w}%;background:${color};"></div></div>
      <div class="bar-val">${fmt(v)}</div></div>`;
  };
  const segs = [["Material", val("materials"), "var(--rust-deep)"], ["Production", val("production"), "var(--rust)"],
    ...(repairOn ? [["Repair", val("repair"), "var(--tan)"]] : []), ["End of life", val("eolBurden"), "var(--purple)"]];
  let acc = 50;
  const segHtml = segs.map(([l, v, c]) => { const w = Math.max(v, 0) / maxAbs * 50; const h = `<div class="bar-fill" style="left:${acc}%;width:${w}%;background:${c};" title="${l}: ${fmt(v)} ${esc(u)}"></div>`; acc += w; return h; }).join("");

  const d = result.detail;
  const child = list => list.filter(([, v]) => Math.abs(v) > 1e-12).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .map(([l, v, c]) => `<div class="breakdown-row child"><div class="lbl"><span class="breakdown-dot" style="background:${c};"></span>${esc(l)}</div><div class="val">${fmt(v)} ${esc(u)}</div></div>`).join("");
  const xn = result.info.nRepairs ? ` (×${result.info.nRepairs})` : "";
  const sub = {
    mat: d.materialItems.map(it => [`${disp(it.material)} — ${disp(it.source)}`, it.burden[ci], "var(--rust-deep)"]),
    prod: d.productionSteps.map(s => [s.name, s.burden[ci], "var(--rust)"]),
    rep: [...d.repairMaterialItems.map(it => [`${disp(it.material)}${xn}`, it.burden[ci], "var(--tan)"]),
      ...d.repairSteps.map(s => [`${s.name}${xn}`, s.burden[ci], "var(--tan)"])],
    eol: ROUTES.map(r => [ROUTE_LABELS[r], d.eolRoutes[r][ci], "var(--purple)"]),
    seq: [["Biogenic carbon uptake (virgin bio-based)", d.growth, "var(--teal)"], ["Delayed emissions (by-products, recycled, wild-harvested)", d.delayed, "var(--teal)"]],
    circ: [["Avoided — composting", d.credits.composted[ci], "var(--blue)"], ["Avoided — open-loop recycling", d.credits.recycled_open[ci], "var(--blue)"],
      ["Avoided — incineration (heat + power)", d.credits.energy[ci], "var(--blue)"]],
  };
  const items = [{ k: "mat", l: "Material burden", v: val("materials"), c: "var(--rust-deep)" }, { k: "prod", l: "Production burden", v: val("production"), c: "var(--rust)" },
    ...(repairOn ? [{ k: "rep", l: "Repair burden", v: val("repair"), c: "var(--tan)" }] : []), { k: "eol", l: "End-of-life burden", v: val("eolBurden"), c: "var(--purple)" },
    ...(ci === GWP ? [{ k: "seq", l: "Carbon storage benefit", v: seq, c: "var(--teal)" }] : []), { k: "circ", l: "Circularity benefit (EoL)", v: circ, c: "var(--blue)" }];
  const breakdown = items.filter(it => Math.abs(it.v) > 1e-12).sort((a, b) => Math.abs(b.v) - Math.abs(a.v)).map(it => {
    const kids = child(sub[it.k] || []), open = kids && state.expanded[it.k];
    return `<div class="breakdown-row parent${kids ? " expandable" : ""}" ${kids ? `data-expand="${it.k}"` : ""}>
      <div class="lbl"><span class="breakdown-caret">${kids ? (open ? "▾" : "▸") : ""}</span><span class="breakdown-dot" style="background:${it.c};"></span>${it.l}</div>
      <div class="val">${fmt(it.v)} ${esc(u)}</div></div>${open ? `<div class="breakdown-children">${kids}</div>` : ""}`;
  }).join("");

  const fut = RAW_DATA.scenarioLabels[RAW_DATA.scenarios.future];
  const where = `${state.scaleT === 0 ? "prototype" : state.scaleT === 100 ? "scaled-up" : `${state.scaleT}% scaled-up`}, ${state.bgT === 0 ? "today" : state.bgT === 100 ? fut : `${state.bgT}% towards ${fut}`}`;
  document.getElementById("results-body").innerHTML = `
    <div class="net-row">
      <div class="net-number ${net <= 0 ? "negative" : "positive"}">${fmt(net)}<span class="net-unit"> ${esc(u)}</span></div>
      <div class="net-caption">net impact, ${esc(where)}<br><span class="${mcCur ? "" : "stale"}">${mcCur ? rangeText(mcCur, ci) : "computing range…"}</span><br>
        ${fmt(result.info.productKg)} kg · ${fmt(result.info.serviceLife)} yr service life${result.info.nRepairs ? ` (${result.info.nRepairs} repairs)` : ""} · × ${fmt(result.info.scaling)} to ${fmt(state.meta.rsl)} yr</div>
    </div>
    <div class="bars">
      <div class="bar-row"><div class="bar-label">Burden</div><div class="bar-track"><div class="zero-line" style="left:50%;"></div>${segHtml}</div><div class="bar-val">${fmt(burden)}</div></div>
      ${barRow("Carbon storage", seq, "var(--teal)")}${barRow("Circularity", circ, "var(--blue)")}${barRow("Net", net, "var(--net)")}
    </div>
    <div class="legend">${[["Material", "--rust-deep"], ["Production", "--rust"], ...(repairOn ? [["Repair", "--tan"]] : []), ["End of life", "--purple"], ["Carbon storage", "--teal"], ["Circularity", "--blue"]]
      .map(([l, c]) => `<div class="legend-item"><span class="legend-swatch" style="background:var(${c});"></span>${l}</div>`).join("")}${ci !== GWP ? `<div class="legend-item">(carbon storage: climate change only)</div>` : ""}</div>
    <div class="compare-box">
      <div class="compare-head"><h4>Comparison</h4><span class="hint">${esc(u)} per functional unit</span></div>
      ${comparisonChart(ci, u)}
    </div>
    ${renderSensitivity(ci)}
    <details class="fold" id="fold-breakdown" ${state.openBreakdown ? "open" : ""}><summary>Breakdown by item</summary><div class="breakdown-list">${breakdown}</div></details>
    ${renderWarnings()}
    <details class="fold" id="fold-notes" ${state.openNotes ? "open" : ""}><summary>About these numbers</summary>
      <p class="section-note">Bars are typical values; whiskers are 5–95 % of a Monte Carlo over the min–max ranges (500 draws for the RAW case, recomputed after every change, and 500 for the baselines; background data at its mean, so the ecoinvent uncertainty is not included). The ranking in "What matters most" is a quick global sensitivity analysis on the same draws: each number's squared rank correlation with the result, as a share of the total (fainter rows can't be told apart from noise). The paper's Sobol\' analysis (pipeline/05_sensitivity.ipynb) is the full version. The Today &rarr; ${esc(fut)} slider blends the background unit burdens linearly; the Prototype &rarr; Scaled-up slider moves every input to its scaled-up value.</p></details>`;
  for (const [id, key] of [["fold-breakdown", "openBreakdown"], ["fold-warn", "openWarn"], ["fold-notes", "openNotes"]]) {
    const el = document.getElementById(id);
    if (el && el.addEventListener) el.addEventListener("toggle", () => { state[key] = el.open; });
  }
  document.getElementById("results-body").onclick = (e) => {
    const sb = e.target.closest("[data-sens]");
    if (sb) { state.sensKey = sb.dataset.sens; renderResultsBody(); return; }
    const r = e.target.closest("[data-expand]");
    if (r) { state.expanded[r.dataset.expand] = !state.expanded[r.dataset.expand]; renderResultsBody(); }
  };
  wireChartTooltip();
}

// "What matters most": the numbers whose min-max ranges move the selected result most (rank correlations of the
// Monte Carlo draws, see calc.js sensitivity), for the prototype or the scaled-up product (today).
function renderSensitivity(ci) {
  const key = state.sensKey, labels = Object.fromEntries(inputList(state.inputs).map(e => [e.path, e.label]));
  const head = `<div class="compare-head"><h4>What matters most</h4>
    <span class="seg">${[["prototype", "prototype"], ["scaledUp", "scaled-up"]].map(([k, l]) =>
      `<button type="button" class="${k === key ? "on" : ""}" data-sens="${k}">${l}</button>`).join("")}</span></div>`;
  if (!state.mc || !state.mc.draws) return `<div class="sens-box">${head}<p class="section-note">computing…</p></div>`;
  const rows = sensitivity(state.mc.draws, key, ci).slice(0, 8);
  const noise = 2 / Math.sqrt(MC_DRAWS);
  const list = rows.map((r, i) => {
    const label = labels[r.path] || r.path;
    const weak = Math.abs(r.rho) < noise;
    return `<div class="sens-row${weak ? " weak" : ""}">
      <span class="sens-rank">${i + 1}</span>
      <a href="#" data-goto="${esc(r.path)}" class="sens-name">${esc(label)}</a>
      <span class="sens-bar"><i style="width:${(r.share * 100).toFixed(1)}%"></i></span>
      <span class="sens-val">${Math.round(r.share * 100)}%</span>
      <span class="sens-dir" title="${r.rho > 0 ? "a higher value raises the impact" : "a higher value lowers the impact"}">${r.rho > 0 ? "↑" : "↓"}</span></div>`;
  }).join("");
  return `<div class="sens-box${state.mcStale ? " stale" : ""}">${head}
    <p class="section-note">Share of the spread in the ${key === "prototype" ? "prototype" : "scaled-up"} result (${esc(RAW_DATA.categoryLabels[state.category] || state.category)}, today) that comes from each number's min–max range. ↑ / ↓: a higher value raises / lowers the impact. Numbers that are fixed or have no range don't appear.</p>
    ${list || `<p class="section-note">No number with a range.</p>`}</div>`;
}
// burden / benefit / net of a vector set (Python `vectors` or a runRaw result) in category ci
function splitResult(r, ci) {
  const burden = r.burdens ? r.burdens[ci] : r.materials[ci] + r.production[ci] + r.repair[ci] + r.eolBurden[ci];
  const benefit = r.benefits ? r.benefits[ci] : r.sequestration[ci] + r.circularity[ci];
  return { burden, benefit, v: r.net[ci] };
}
// The comparison: today (baselines, RAW prototype, RAW scaled-up), then 2050 (baselines, RAW scaled-up).
function chartRows(ci) {
  const B = RAW_BASELINES[state.caseId] || {};
  const fut = RAW_DATA.scenarioLabels[RAW_DATA.scenarios.future];
  const mc = state.mc;     // may lag an edit by a moment; recomputed after every change
  const base = (period, bkey) => [["fossil", "Fossil-based baseline"], ["bio", "Bio-based baseline"]].filter(([k]) => B[k]).map(([k, label]) =>
    Object.assign({ key: k + (bkey === "future" ? "2050" : ""), group: "base", label, sub: B[k].label, period,
      lo: B[k][bkey].lo[ci], hi: B[k][bkey].hi[ci] }, splitResult(B[k][bkey], ci)));
  const raw = (key, label, period, sc, bg) => Object.assign({ key, group: "raw", label, sub: "", period,
    lo: mc ? mc[key].lo[ci] : NaN, hi: mc ? mc[key].hi[ci] : NaN }, splitResult(runCase(state.inputs, caseMeta(), sc, bg), ci));
  return [...base("today", "today"), raw("prototype", "RAW prototype", "today", 0, 0), raw("scaledUp", "RAW scaled-up", "today", 1, 0),
    ...base(fut, "future"), raw("scaledUp2050", "RAW scaled-up", fut, 1, 1)];
}
function productName(r) { return `${r.label}${r.sub ? ` (${r.sub})` : ""}, ${r.period}`; }
function niceTicks(lo, hi, n = 4) {
  const span = hi - lo || 1, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || 10 * mag;
  const ticks = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9 * step; t += step) ticks.push(Math.abs(t) < step * 1e-9 ? 0 : t);
  return ticks;
}
// burden = darker bar, benefit = lighter bar (both from zero, stacked if they share a sign), net = dot, whiskers = 5-95 %
const CHART_COLORS = { base: { burden: "#5f655e", benefit: "#c3c7bb" }, raw: { burden: "#a4521a", benefit: "#e8bd90" } };
function barPath(from, to, y, h, r) {   // rectangle from x=from to x=to, rounded only at the `to` end
  const a = Math.min(from, to), b = Math.max(from, to), w = b - a;
  if (w < 0.5) return "";
  r = Math.min(r, w, h / 2);
  return to >= from
    ? `M${a},${y} H${b - r} Q${b},${y} ${b},${y + r} V${y + h - r} Q${b},${y + h} ${b - r},${y + h} H${a} Z`
    : `M${b},${y} H${a + r} Q${a},${y} ${a},${y + r} V${y + h - r} Q${a},${y + h} ${a + r},${y + h} H${b} Z`;
}
function comparisonChart(ci, u) {
  const rows = chartRows(ci);
  state.chartRows = rows;
  const W = 560, L = 168, R = W - 12, rowH = 32, headH = 18;
  const periods = [...new Set(rows.map(r => r.period))];
  const ys = [];                                            // top of each row, with a header above each period
  let yy = 4;
  rows.forEach((r, i) => { if (i === 0 || r.period !== rows[i - 1].period) yy += headH; ys.push(yy); yy += rowH; });
  const top = 4, H = yy + 22;
  const vals = rows.flatMap(r => [r.burden, r.benefit, r.v, r.lo, r.hi, r.burden + (Math.sign(r.benefit) === Math.sign(r.burden) ? r.benefit : 0)]).filter(isFinite);
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (lo === hi) hi = lo + 1;
  const ticks = niceTicks(lo, hi);
  lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
  const x = v => L + (v - lo) / (hi - lo) * (R - L);
  const x0 = x(0);
  const grid = ticks.map(t => `<line x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${H - 20}" class="grid"/><text x="${x(t)}" y="${H - 6}" class="tick" text-anchor="middle">${fmt(t)}</text>`).join("");
  const heads = periods.map(pd => {
    const i = rows.findIndex(r => r.period === pd), y = ys[i] - 6;
    return `<text x="4" y="${y}" class="phead">${esc(pd === "today" ? "Today" : pd)}</text>${i > 0 ? `<line x1="0" x2="${W}" y1="${y - 13}" y2="${y - 13}" class="psep"/>` : ""}`;
  }).join("");
  const bars = rows.map((r, i) => {
    const y = ys[i] + 6, h = 16, c = CHART_COLORS[r.group], cy = y + h / 2;
    const stack = Math.sign(r.benefit) === Math.sign(r.burden);           // same sign: benefit continues after the burden
    const bStart = stack ? r.burden : 0, gap = stack && r.burden !== 0 ? Math.sign(r.benefit) * 2 : 0;
    const burden = barPath(x0, x(r.burden), y, h, 4);
    const benefit = barPath(x(bStart) + gap, x(bStart + r.benefit), y, h, 4);
    const whisk = isFinite(r.lo) && isFinite(r.hi)
      ? `<line x1="${x(r.lo)}" x2="${x(r.hi)}" y1="${cy}" y2="${cy}" class="whisker"/><line x1="${x(r.lo)}" x2="${x(r.lo)}" y1="${cy - 5}" y2="${cy + 5}" class="whisker"/><line x1="${x(r.hi)}" x2="${x(r.hi)}" y1="${cy - 5}" y2="${cy + 5}" class="whisker"/>` : "";
    return `<g class="crow" data-i="${i}">
      <rect x="0" y="${y - 6}" width="${W}" height="${rowH}" class="hit"/>
      <text x="${L - 10}" y="${r.sub ? y + 5 : y + 12}" class="rlab" text-anchor="end">${esc(r.label)}</text>
      ${r.sub ? `<text x="${L - 10}" y="${y + 17}" class="rsub" text-anchor="end">${esc(r.sub.length > 30 ? r.sub.slice(0, 29) + "…" : r.sub)}</text>` : ""}
      ${burden ? `<path d="${burden}" fill="${c.burden}"/>` : ""}${benefit ? `<path d="${benefit}" fill="${c.benefit}"/>` : ""}
      ${whisk}<circle cx="${x(r.v)}" cy="${cy}" r="4.5" class="net-dot"/></g>`;
  }).join("");
  const key = `<div class="chart-key">
    <span><i class="sw" style="background:${CHART_COLORS.raw.burden}"></i><i class="sw" style="background:${CHART_COLORS.base.burden}"></i>burden</span>
    <span><i class="sw" style="background:${CHART_COLORS.raw.benefit}"></i><i class="sw" style="background:${CHART_COLORS.base.benefit}"></i>benefit</span>
    <span><i class="dot"></i>net</span><span><i class="whisk"></i>net 5–95 %</span></div>`;
  return `${key}<div class="chart-wrap"><svg viewBox="0 0 ${W} ${H}" class="cmp-chart" role="img" aria-label="Burden, benefit and net impact of the baselines and the RAW case">
    ${grid}<line x1="${x0}" x2="${x0}" y1="${top}" y2="${H - 20}" class="zero"/>${heads}${bars}</svg>
    <div class="chart-tip" id="chart-tip"></div></div>
    <table class="sr-table"><tr><th>Product</th><th>Burden</th><th>Benefit</th><th>Net</th><th>5 %</th><th>95 %</th></tr>${rows.map(r => `<tr><td>${esc(productName(r))}</td><td>${fmt(r.burden)}</td><td>${fmt(r.benefit)}</td><td>${fmt(r.v)}</td><td>${fmt(r.lo)}</td><td>${fmt(r.hi)}</td></tr>`).join("")}</table>`;
}
function wireChartTooltip() {
  const svg = document.querySelector(".cmp-chart"), tip = document.getElementById("chart-tip");
  if (!svg || !tip) return;
  svg.onmousemove = (e) => {
    const g = e.target.closest(".crow");
    svg.querySelectorAll(".crow").forEach(n => n.classList.toggle("dim", !!g && n !== g));
    if (!g) { tip.style.display = "none"; return; }
    const r = state.chartRows[Number(g.dataset.i)], u = esc(unit());
    tip.innerHTML = `<b>${esc(r.label)}</b>${r.sub ? ` · ${esc(r.sub)}` : ""} · ${esc(r.period)}<br>burden ${fmt(r.burden)} · benefit ${fmt(r.benefit)}<br><b>net ${fmt(r.v)}</b> ${u}${isFinite(r.lo) ? `<br>5–95 %: ${fmt(r.lo)} to ${fmt(r.hi)}` : ""}`;
    const box = svg.parentElement.getBoundingClientRect();
    tip.style.display = "block";
    tip.style.left = Math.min(e.clientX - box.left + 12, box.width - 230) + "px";
    tip.style.top = (e.clientY - box.top + 12) + "px";
  };
  svg.onmouseleave = () => { tip.style.display = "none"; svg.querySelectorAll(".crow").forEach(n => n.classList.remove("dim")); };
}
function renderWarnings() {
  const list = inputList(state.inputs).map(e => [e, warnings(e)]).filter(([, w]) => w.length);
  const sums = [];
  for (const [key, lbl] of [["productionBom", "Bill of materials"], ["repairBom", "Repair bill of materials"]]) {
    if (key === "repairBom" && !state.inputs.circularity.enabled) continue;
    const t = state.inputs[key].reduce((s, x) => s + (Number(x.share.v) || 0), 0);
    if (state.inputs[key].length && Math.abs(t - 100) > 0.01) sums.push(`${lbl} adds up to ${fmt(t)} % (re-normalised to 100 %)`);
  }
  const te = ROUTES.reduce((s, r) => s + (Number(state.inputs.eol[r].v) || 0), 0);
  if (Math.abs(te - 100) > 0.01) sums.push(`End-of-life shares add up to ${fmt(te)} % (re-normalised to 100 %)`);
  if (!list.length && !sums.length) return "";
  return `<details class="fold warn-box" id="fold-warn" ${state.openWarn ? "open" : ""}><summary>To check (${list.length + sums.length})</summary><ul>
    ${sums.map(s => `<li>${esc(s)}</li>`).join("")}
    ${list.map(([e, w]) => `<li><a href="#" data-goto="${esc(e.path)}">${esc(e.label)}</a>: ${esc(w.join(", "))}</li>`).join("")}</ul></details>`;
}
document.getElementById("results-col").addEventListener("click", (e) => {
  const a = e.target.closest("[data-goto]");
  if (!a) return;
  e.preventDefault();
  const row = document.querySelector(`[data-row="${CSS.escape(a.dataset.goto)}"]`);
  if (row) { row.scrollIntoView({ behavior: "smooth", block: "center" }); row.classList.add("flash"); setTimeout(() => row.classList.remove("flash"), 1200); }
});

// ============================================================================
// CASES, EXPORT, IMPORT, SUBMISSION
// ============================================================================
function loadCase(id, inputs) {
  const c = RAW_CASES.find(x => x.id === id);
  if (!c) return false;
  state.caseId = id;
  state.meta = c;
  state.original = buildOriginal(c.inputs);
  state.inputs = upgradeInputs(deepClone(inputs || c.inputs));
  state.expanded = {};
  state.mc = null;
  document.getElementById("case-select").value = id;
  renderLeft();
  renderResultsControls();
  scheduleResults();
  return true;
}
function hasEdits() {
  return inputList(state.inputs).some(e => changedFields(e).length || e.p.comment);
}
document.getElementById("case-select").innerHTML = RAW_CASES.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
document.getElementById("case-select").addEventListener("change", (e) => {
  if (hasEdits() && !confirm("Switch case? Your edits to this case are lost unless you export or submit them first.")) {
    e.target.value = state.caseId; return;
  }
  loadCase(e.target.value);
});
document.getElementById("btn-reset").addEventListener("click", () => {
  if (!hasEdits() || confirm("Reset every value of this case to the sheet values?")) loadCase(state.caseId);
});

// Columns of the CSV export and of the rows sent to the Google Sheet.
const ROW_COLUMNS = ["case", "stage", "item", "qualifier", "parameter", "unit", "typical", "min", "max", "scaled_up", "comments",
  "changed", "sheet_typical", "sheet_min", "sheet_max", "sheet_scaled_up", "sheet_source"];
// What differs from the sheet itself (sheet.values) — including values the tool tidied (e.g. a max of 120 % -> 100 %).
// Inputs that are not one sheet row (density, savings, repairs, new rows) compare with the tool's defaults.
function exportChanged(e, o, isNew) {
  if (isNew) return "new row";
  const p = e.p, eff = x => (hasUp(x) ? x.up : x.v);
  const out = [];
  if (!same(p.v, o.v)) out.push("typical");
  if (e.kind === "num" && !same(p.min, o.min)) out.push("min");
  if (e.kind === "num" && !same(p.max, o.max)) out.push("max");
  if ("up" in p && !same(eff(p), eff(o))) out.push("scaled_up");
  if ("unit" in p && !same(p.unit, o.unit)) out.push("unit");
  return out.join(";");
}
function inputRows() {
  return inputList(state.inputs).filter(e => !(e.path.startsWith("circularity.") && e.path !== "circularity.expectedLifetime" && !state.inputs.circularity.enabled))
    .map(e => {
      const p = e.p, s = e.sheet, def = state.original[sheetKey(s)];
      const o = s.values || def || {};
      return { case: state.caseId, stage: s.stage, item: s.item, qualifier: s.qualifier || "", parameter: s.parameter, unit: p.unit || s.unit || "",
        typical: e.kind === "num" ? numOrBlank(p.v) : (p.v || ""), min: e.kind === "num" ? numOrBlank(p.min) : "", max: e.kind === "num" ? numOrBlank(p.max) : "",
        scaled_up: "up" in p ? numOrBlank(hasUp(p) ? p.up : p.v) : "", comments: p.comment || "",
        changed: exportChanged(e, o, !def),
        sheet_typical: e.kind === "num" ? numOrBlank(o.v) : (o.v || ""), sheet_min: numOrBlank(o.min), sheet_max: numOrBlank(o.max), sheet_scaled_up: numOrBlank(o.up),
        sheet_source: s.source || "" };
    });
}
function csvCell(v) { const s = String(v === undefined || v === null ? "" : v); return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; }
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click();
}
function fileStem() {
  const who = (document.getElementById("rec-org").value || document.getElementById("rec-name").value || "").replace(/[^a-z0-9-]+/gi, "_");
  return `${state.caseId}${who ? "_" + who : ""}_${new Date().toISOString().slice(0, 10)}`;
}
function rowsCsv() {
  return [ROW_COLUMNS.join(","), ...inputRows().map(r => ROW_COLUMNS.map(c => csvCell(r[c])).join(","))].join("\n");
}
document.getElementById("btn-export-csv").addEventListener("click", () => download(`${fileStem()}.csv`, rowsCsv(), "text/csv"));
document.getElementById("btn-export").addEventListener("click", () => {
  download(`${fileStem()}.json`, JSON.stringify({ tool: "RAW Impact Explorer", snapshot: RAW_DATA.snapshot, caseId: state.caseId,
    exportedAt: new Date().toISOString(), submitter: submitter(), inputs: state.inputs }, null, 1), "application/json");
});
document.getElementById("btn-import").addEventListener("click", () => document.getElementById("file-import").click());
document.getElementById("file-import").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result);
      if (!data.caseId || !data.inputs || !loadCase(data.caseId, data.inputs)) throw new Error("no case");
      if (data.submitter) { document.getElementById("rec-name").value = data.submitter.name || ""; document.getElementById("rec-org").value = data.submitter.organisation || ""; }
      setStatus(`Imported ${file.name}` + (data.snapshot !== RAW_DATA.snapshot ? ` (made with sheet snapshot ${data.snapshot}; "changed" markers compare with ${RAW_DATA.snapshot})` : ""), "ok");
    } catch (err) {
      setStatus("That file isn't an export of this tool (Export inputs .json).", "err");
    }
    e.target.value = "";
  };
  reader.readAsText(file);
});

function submitter() {
  return { name: document.getElementById("rec-name").value.trim(), organisation: document.getElementById("rec-org").value.trim() };
}
function newSubmissionId() {
  return `${state.caseId}-${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}-${Math.random().toString(36).slice(2, 6)}`;
}
function buildSubmission() {
  if (state.mcStale || !state.mc) runMC();          // ranges must match the submitted inputs
  const num = x => isFinite(x) ? x : null;
  // the five comparison-chart products, in every impact category
  const results = CATEGORIES.flatMap((cat, ci) => chartRows(ci).map(r => ({ category: cat, unit: RAW_DATA.units[cat] || "",
    product: productName(r), burden: num(r.burden), benefit: num(r.benefit), net: num(r.v), p5: num(r.lo), p95: num(r.hi) })));
  return { tool: "RAW Impact Explorer", snapshot: RAW_DATA.snapshot, submissionId: newSubmissionId(), submittedAt: new Date().toISOString(),
    submitter: submitter(), case: { id: state.caseId, name: state.meta.name },
    columns: ROW_COLUMNS, rows: inputRows(),
    results };
}
function setStatus(msg, kind) {
  const el = document.getElementById("record-status");
  el.textContent = msg;
  el.className = "record-status" + (kind ? " " + kind : "");
}
// Sends the submission to the Apps Script Web App and reads its reply: {ok, id, rows} or {ok: false, error} from the
// current script, plain "OK" from the earlier one. Apps Script answers a plain-text POST with a redirect to a page
// that allows any origin, so the reply is readable. A reply that can't be read or understood means the submission
// may or may not have arrived: it is not sent again (that could duplicate it); the caller downloads a CSV backup.
async function sendSubmission(url, payload) {
  let res, text = "";
  try {
    res = await fetch(url, { method: "POST", headers: { "Content-Type": "text/plain;charset=utf-8" }, body: JSON.stringify(payload) });
    text = await res.text();
  } catch (err) {
    return { state: "unknown", error: (typeof navigator !== "undefined" && navigator.onLine === false) ? "you seem to be offline" : "no readable reply" };
  }
  let reply = null;
  try { reply = JSON.parse(text); } catch (err) { /* not JSON */ }
  if (res.ok && reply && reply.ok) return { state: "saved", reply };
  if (res.ok && text.trim() === "OK") return { state: "saved", reply: { rows: payload.rows.length, legacy: true } };
  if (reply && reply.ok === false) return { state: "failed", error: reply.error || "the script reported an error" };
  if (!res.ok) return { state: "failed", error: `the sheet answered HTTP ${res.status}` };
  const snippet = text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 60);
  return { state: "unknown", error: `unexpected reply${snippet ? `: "${snippet}"` : ""}` };
}
const submitBtn = document.getElementById("btn-submit");
submitBtn.addEventListener("click", async () => {
  const sub = submitter();
  if (!sub.name || !sub.organisation) { setStatus("Please fill in your name and organisation first.", "err"); return; }
  if (!state.submitUrl) {
    download(`${fileStem()}.csv`, rowsCsv(), "text/csv");
    setStatus("No Google Sheet connected yet — downloaded the CSV instead. Please send it to the LCA team.", "err");
    return;
  }
  const payload = buildSubmission();
  submitBtn.disabled = true;
  setStatus("Sending…", "");
  const r = await sendSubmission(state.submitUrl, payload);
  submitBtn.disabled = false;
  if (r.state === "saved") {
    setStatus(`Saved ✓ ${r.reply.rows} rows for ${state.meta.name} (submission ${payload.submissionId}). Thank you!`
      + (r.reply.legacy ? " (The sheet runs an older script: deploy a new version of the current one from Submission settings.)" : ""), "ok");
  } else if (r.state === "failed") {
    download(`${fileStem()}.csv`, rowsCsv(), "text/csv");
    setStatus(`Not saved: ${r.error}. Downloaded the CSV instead — please send it to the LCA team.`, "err");
  } else {
    download(`${fileStem()}.csv`, rowsCsv(), "text/csv");
    setStatus(`Sent, but couldn't confirm it was saved (${r.error}). A CSV backup was downloaded; submission ${payload.submissionId}.`, "err");
  }
});

// Apps Script for the receiving Google Sheet (also described in README.md). Writes are serialised with a lock so
// simultaneous submissions can't overwrite each other; a submission id that is already in the sheet is not
// written twice.
function appsScriptSnippet() {
  return `// RAW Impact Explorer: receives workshop submissions.
// Google Sheet > Extensions > Apps Script: paste this, save, then
// Deploy > New deployment > Web app (execute as: Me, who has access: Anyone).
// After editing: Deploy > Manage deployments > Edit > Version: New version (the URL stays the same).
var COLUMNS = ${JSON.stringify(ROW_COLUMNS)};
var RESULT_COLUMNS = ["case", "category", "unit", "product", "burden", "benefit", "net", "p5", "p95"];
var META = ["submission_id", "submitted_at", "name", "organisation", "snapshot"];

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
function tab(ss, name, head) {
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) { sh.appendRow(head); sh.setFrozenRows(1); }
  return sh;
}
function append(sh, rows) {
  if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
}
function alreadySaved(sh, id) {
  if (sh.getLastRow() < 2) return false;
  return sh.getRange(2, 1, sh.getLastRow() - 1, 1).getValues().some(function (r) { return r[0] === id; });
}
function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    var data = JSON.parse(e.postData.contents);
    lock.waitLock(30000);                      // one submission at a time
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sub = tab(ss, "submissions", META.concat(COLUMNS));
    var res = tab(ss, "submission_results", META.concat(RESULT_COLUMNS));
    if (alreadySaved(sub, data.submissionId)) return reply({ ok: true, id: data.submissionId, rows: data.rows.length, duplicate: true });
    var meta = [data.submissionId, data.submittedAt, data.submitter.name, data.submitter.organisation, data.snapshot];
    append(sub, data.rows.map(function (r) {
      return meta.concat(COLUMNS.map(function (c) { return r[c] === undefined || r[c] === null ? "" : r[c]; }));
    }));
    append(res, data.results.map(function (b) {
      return meta.concat([data.case.id, b.category, b.unit, b.product, b.burden, b.benefit, b.net, b.p5, b.p95]);
    }));
    SpreadsheetApp.flush();
    return reply({ ok: true, id: data.submissionId, rows: data.rows.length });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}
// Opening the /exec URL in a browser shows this: a quick check that the deployment works.
function doGet() {
  return reply({ ok: true, message: "RAW workshop submissions endpoint is running" });
}`;
}
const modal = document.getElementById("modal-backdrop");
document.getElementById("btn-sheet-settings").addEventListener("click", () => {
  document.getElementById("sheet-url-input").value = state.submitUrl;
  document.getElementById("apps-script-snippet").textContent = appsScriptSnippet();
  modal.classList.add("open");
});
document.getElementById("modal-cancel").addEventListener("click", () => modal.classList.remove("open"));
document.getElementById("modal-save").addEventListener("click", () => {
  state.submitUrl = document.getElementById("sheet-url-input").value.trim();
  modal.classList.remove("open");
  setStatus(state.submitUrl ? "Submission target set for this session (set SUBMIT_URL in app.js to make it permanent)." : "No Google Sheet connected: Submit downloads a CSV.", "ok");
});
modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.remove("open"); });

// ---------- info tooltips (the "i" next to a parameter) -------------------------------
const infoTip = document.getElementById("info-tip");
function showTip(btn) {
  infoTip.textContent = btn.dataset.tip;
  infoTip.style.display = "block";
  const r = btn.getBoundingClientRect(), w = infoTip.offsetWidth, h = infoTip.offsetHeight;
  const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
  const top = r.bottom + 6 + h > window.innerHeight ? r.top - h - 6 : r.bottom + 6;
  infoTip.style.left = left + "px"; infoTip.style.top = top + "px";
  infoTip.dataset.for = btn.dataset.tip;
}
function hideTip() { infoTip.style.display = "none"; infoTip.dataset.for = ""; }
document.addEventListener("mouseover", (e) => { const b = e.target.closest && e.target.closest(".info[data-tip]"); if (b) showTip(b); });
document.addEventListener("mouseout", (e) => { if (e.target.closest && e.target.closest(".info[data-tip]")) hideTip(); });
document.addEventListener("focusin", (e) => { if (e.target.matches && e.target.matches(".info[data-tip]")) showTip(e.target); });
document.addEventListener("focusout", (e) => { if (e.target.matches && e.target.matches(".info[data-tip]")) hideTip(); });
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest(".info[data-tip]");
  if (b) { e.preventDefault(); if (infoTip.style.display === "block" && infoTip.dataset.for === b.dataset.tip) hideTip(); else showTip(b); }
  else hideTip();
});
window.addEventListener("scroll", hideTip, { passive: true });

// ---------- boot -------------------------------------------------------------------
document.getElementById("snapshot-label").textContent = RAW_DATA.snapshot;
wireLeft();
loadCase(RAW_CASES[0].id);
setStatus(state.submitUrl ? "Submissions go to the RAW workshop sheet." : "No Google Sheet connected yet: Submit downloads a CSV.", "");
