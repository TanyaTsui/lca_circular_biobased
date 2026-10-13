# RAW Impact Explorer

A browser tool for RAW project fabrication partners to see the environmental
impact of their process today, sketch an optimised version, and explore which
individual changes matter most — before committing to them on the shop floor.

It's a direct port of `02_model.ipynb`: every function in `calc.js` mirrors a
function in the notebook by name, and the reference case (the 3D-printed
biopolymer example) is validated to reproduce the notebook's printed output
exactly (Material 1.4554 / Production 8.9899 / Repair 0.7869 kg CO2-eq, etc.,
with the background slider below at 0%/baseline).
If you update the LCA model, update `calc.js` to match and re-check against
the notebook before trusting the tool again.

## Files

- `index.html` — page structure & styling
- `presets.js` — the four "Load a case" worked examples (`RAW_PRESETS`)
- `data.js` — `unit_burdens*.csv`, `eol_constants.csv`, `benefits_constants.csv`
  baked into one JS object (`RAW_DATA`), so the tool works offline / from a
  double-clicked file, not just when served
- `build_data.py` — regenerates `data.js` from the three processed CSVs
- `calc.js` — the calculation engine (pure functions, no DOM)
- `app.js` — UI state, form rendering, the compare/diff/slider engine, export
  and recording

To refresh the underlying LCA data (new ecoinvent version, more materials,
updated CFF constants, a new premise scenario run, ...), run
`python build_data.py` from this directory. It reads the three CSVs from
`data/processed/` and rewrites `data.js` — nothing else in the tool needs to
change, since everything reads from `RAW_DATA`.

**Scenario data**: `01b_dataPrep_prospective.ipynb` has been run for real, so
`build_data.py`'s `SOURCE_UNIT_BURDENS` points at the real `unit_burdens.csv`
(baseline / `image_SSP2-M_2050` / `image_SSP2-L_2050`, from real premise
databases) — the synthetic `unit_burdens_dummy.csv` used during development is
no longer referenced. Re-run `python build_data.py` any time `01b` produces a
new scenario run.

## Starting a model

The tool **opens blank**. The Today tab shows a *Start a model* banner with four
worked examples (also reachable any time via **Load a case** in the top bar):

| Case | What it is |
|---|---|
| Biopolymer 3D printing | pea-protein/sawdust/seagrass, printed + baked; ships with an optimised future line |
| Reclaimed hardwood CNC | 100% recycled hardwood, scanned + CNC-milled (net-negative) |
| Knitted hemp fibre | virgin hemp carded/spun/knitted, closed-loop recycled |
| Coreless filament winding | hemp roving wet-wound with epoxy, incineration-heavy EoL |

Presets live in `presets.js` (same shape as an exported inputs file). *Blank
canvas* in the Load-a-case dialog clears everything. Every field stays editable
after loading.

## Inputs & results panel

- **Product basis** holds the lifetime assumptions and the repair on/off toggle.
  *Expected lifetime without repair* is always shown (it sets the carbon-storage
  duration); *lifetime extension per repair* and *number of repair events* only
  appear when repair is toggled on. Repair-only inputs (repair material %, repair
  BOM, repair chain) stay in the Repair section; the repair BOM and chain each
  have a *Copy from production* button.
- **Production process chain** steps can be reordered with the ↑/↓ buttons on
  each step card (the chain is still solved backward from the target output
  mass, so order changes the result).
- Material-source labels are display-only relabels: `co-product` shows as
  `by-product`, `Soft wood`/`Hard wood` as `wood, soft`/`wood, hard`. The
  canonical value is what `calc.js` and the CSVs use and what exports contain.
- The **Burden** bar in the results panel is segmented by component (material /
  production / repair / end-of-life). Each row in the itemised breakdown below
  expands on click to a per-item drill-down (per process, per material, per EoL
  route, growth vs. delayed-emissions for sequestration).
- With materials but **no process steps**, results are still shown — the input
  mass is taken to equal the target output mass (no processing losses).

## Compare tab

- A **master slider** ("Slide everything: Today → Future") at the top moves
  every lever to the same position at once; releasing it re-syncs the toggle
  buttons.
- Each **bill of materials** contributes a single mix slider (Today mix → Future
  mix) rather than one slider per material.
- Diff ids are now derived from group + label (stable across re-renders), so
  slider positions and toggles survive editing another lever.

## Import / export

- **Export inputs (.json)** downloads both scenarios' inputs (+ background).
- **Import inputs (.json)** reloads a previously exported file — Today, Future
  and background are all restored; missing keys are backfilled from the default
  scenario so older exports still load.

## Recording target (pre-configured)

`state.sheetUrl` in `app.js` is pre-set to the deployed Apps Script Web App for
the shared RAW project sheet
(`docs.google.com/spreadsheets/d/1V-yfoLJ4mOpQNL9FhD3dTIvIVj3SZCwywt3PAdA_jyw`),
so **Record to research log** works with no setup. Override it in Recording
settings if you need a different target.

## Background scenario slider

Alongside the existing Today/Future compare tab (which blends the *foreground*
recipe — BOM, process chain, EoL split), the results panel has a second,
independent slider: **Background: Today → Future**, plus a dropdown choosing
which IAM pathway "Future" means. It linearly interpolates *background* unit
burdens (electricity, cement, steel — the sectors `premise` actually updates)
between the `baseline` data and the selected scenario. This is a sensitivity/
exploration device, not a modelled emissions trajectory — most materials in
the BOM aren't premise-sensitive at all and won't move as you drag it.

## Deploying (GitHub Pages)

Same as your other tools: put these files (`index.html`, `data.js`,
`presets.js`, `calc.js`, `app.js`) in a folder in your
`tanyatsui.github.io` repo (or any static host) and it just works — no build
step, no server. Test locally first by opening `index.html` directly in a
browser (works fine without a server since data is inlined, not fetched).

## Setting up centralised recording (optional)

Local JSON export always works, no setup needed (top-right "Export inputs").
To collect every partner's submissions into one Google Sheet:

1. Create a new Google Sheet.
2. Extensions → Apps Script. Delete the placeholder code and paste in the
   snippet shown in the tool's "Recording settings" modal (also below).
3. Deploy → New deployment → type "Web app" → execute as yourself, who has
   access "Anyone". Deploy, then copy the generated URL
   (`https://script.google.com/macros/s/.../exec`).
4. Paste that URL into the tool's "Recording settings" modal.

```js
function doPost(e) {
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
}
```

Notes:
- The Sheet URL isn't saved between page reloads (the tool avoids browser
  storage so it behaves predictably everywhere it's opened). If you want it
  to persist for a specific deployment, hardcode it as the initial value of
  `state.sheetUrl` in `app.js`.
- Requests are sent with `mode: "no-cors"`, which is required for Apps Script
  but means the browser can't confirm the response — check the Sheet
  directly to confirm rows are landing.
- Every submission stores the full JSON of both scenarios' inputs, so nothing
  is lost even though the visible columns only show net climate-change
  impact — you can widen the recording later without losing history.

## What's not built yet (v2 ideas)

- Per-category ranked drivers currently only rank against the category
  selected in the results panel — fine for exploration, but if you want a
  fixed "always rank by climate change regardless of what's displayed"
  mode, that's a small change in `renderCompare()`.
- BOM percentage sliders in Compare don't enforce the 100% constraint while
  dragging (by design — it's meant for single-lever sensitivity, not a valid
  intermediate mix). If partners find this confusing, a "renormalise" toggle
  could be added.
- No undo/history within a session — Export often, especially before big
  edits.
