// Compares calc.js with the Python model (raw_lca) for every case, prototype / scaled-up x today / 2050,
// at typical values, in every impact category. Run from this folder (macOS JavaScriptCore or node):
//   /System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc data.js presets.js calc.js check_calc.js
const TOL = 1e-6;
const log = typeof print === "function" ? print : console.log;
let failures = 0, checked = 0;
const PARTS = ["materials", "production", "repair", "eolBurden", "sequestration", "circularity", "net"];
for (const c of RAW_CASES) {
  const meta = { specValue: c.spec.value, rsl: c.rsl };
  for (const [bgKey, bgT] of [["today", 0], ["future", 1]]) {
    for (const [variant, scaleT] of [["prototype", 0], ["scaledUp", 1]]) {
      const js = runCase(c.inputs, meta, scaleT, bgT);
      const py = RAW_REFERENCE[c.id][bgKey][variant];
      let worst = 0, where = "";
      for (const part of PARTS) {
        for (let i = 0; i < CATEGORIES.length; i++) {
          const a = js[part][i], b = py[part][i];
          const err = Math.abs(a - b) / Math.max(Math.abs(b), 1e-12);
          checked++;
          if (!(err <= TOL) && Math.abs(a - b) > 1e-15) {
            failures++;
            if (!(err <= worst)) { worst = err; where = `${part} / ${CATEGORIES[i]}: js ${a} vs python ${b}`; }
          }
        }
      }
      log(`${worst ? "FAIL" : "ok  "} ${c.id} ${variant} ${bgKey}: net GWP ${js.net[GWP].toFixed(4)} (python ${py.net[GWP].toFixed(4)})${worst ? "  worst " + where : ""}`);
    }
  }
}
// the Monte Carlo runs and gives a range around the typical value
const c0 = RAW_CASES[0];
const t0 = Date.now();
const mc = runMonteCarlo(c0.inputs, { specValue: c0.spec.value, rsl: c0.rsl }, [{ key: "p", scaleT: 0, bgT: 0 }], 300);
log(`MC ${c0.id}: net GWP 5-95% ${mc.p.lo[GWP].toFixed(2)} .. ${mc.p.hi[GWP].toFixed(2)} (${Date.now() - t0} ms for 300 draws)`);
log(failures ? `${failures} of ${checked} values differ` : `all ${checked} values match (rel. tol ${TOL})`);
if (failures && typeof quit === "function") quit(1);
if (failures && typeof process !== "undefined") process.exit(1);
