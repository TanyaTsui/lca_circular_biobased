# RAW Impact Explorer

A browser tool for RAW project fabrication partners to see the environmental
impact of their process today, sketch an optimised version, and explore which
individual changes matter most — before committing to them on the shop floor.

It's a direct port of `02_model.ipynb`: every function in `calc.js` mirrors a
function in the notebook by name, and the reference case (the 3D-printed
biopolymer example) is validated to reproduce the notebook's printed output
exactly (Material 1.4554 / Production 8.9899 / Repair 0.7869 kg CO2-eq, etc.).
If you update the LCA model, update `calc.js` to match and re-check against
the notebook before trusting the tool again.

## Files

- `index.html` — page structure & styling
- `data.js` — `unit_burdens.csv`, `eol_constants.csv`, `benefits_constants.csv`
  baked into one JS object (`RAW_DATA`), so the tool works offline / from a
  double-clicked file, not just when served
- `calc.js` — the calculation engine (pure functions, no DOM)
- `app.js` — UI state, form rendering, the compare/diff/slider engine, export
  and recording

To refresh the underlying LCA data (new ecoinvent version, more materials,
updated CFF constants, ...), regenerate `data.js` from the three CSVs — the
conversion script is a ~30-line Python snippet (ask Claude to reproduce it,
or see the chat where this was built) and just needs to run again whenever
the CSVs change. Everything else in the tool reads from `RAW_DATA` and
doesn't need to change.

## Deploying (GitHub Pages)

Same as your other tools: put these four files in a folder in your
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
