# RAW Impact Explorer

A browser tool for the RAW partner workshop. Partners check the life cycle inventory (LCI) of their case: they correct
each number, its min–max range and the scaled-up value, and add comments. They see straight away what this does to the
impact, compared with the conventional bio-based and fossil-based products, and then submit their numbers.

The tool computes with the same model as the paper. `calc.js` is a port of `raw_lca/model.py` (`Model.run_raw`), with
the same function names, and `check_calc.js` checks it against the Python results.

## Files

| file | what |
|---|---|
| `index.html` | page and styling |
| `app.js` | the form, results panel, comparison chart, export / import / submission |
| `calc.js` | the model (no DOM): `runRaw`, `plainInputs`, scale-up and background blending, Monte Carlo |
| `data.js` | **generated**: `RAW_DATA`, i.e. unit burdens today and 2050, carbon content, EoL constants and routes, constants, GWP_bio and Bern tables |
| `presets.js` | **generated**: `RAW_CASES` (the four cases as editable inputs), `RAW_BASELINES`, `RAW_REFERENCE` |
| `build_data.py` | writes `data.js` and `presets.js` from the newest sheet snapshot and `data/background/` |
| `check_calc.js` | compares `calc.js` with `RAW_REFERENCE` (every case, prototype / scaled-up × today / 2050, every category) |

## Updating the numbers

```bash
python pipeline/01_fetch_sheet.py                                  # new snapshot of the Google Sheet (repo root)
cd results/html_tools/raw_impact_explorer
python build_data.py                                               # brightway_env
/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc data.js presets.js calc.js check_calc.js
```

`build_data.py` always reads the newest folder of `data/sheet_snapshot/`. The page shows which snapshot it was built
from. Never edit `data.js` or `presets.js` by hand. If you change the model in `raw_lca/model.py`, change `calc.js` too
and rerun `check_calc.js` (`node` works as well as `jsc`).

## What the cases contain

Every number is an object `{v, min, max, dist, up?, comment, sheet}`, where `sheet` is the sheet row it comes from
(stage, item, qualifier, parameter, unit, source, comments, and `values`, the sheet's own numbers). Hovering the **i**
shows that row's source and comments. The sheet's `status` column is not used by the tool.

**Tidied defaults.** `build_data.py` starts every RAW case from the sheet with the obvious issues fixed, so that the
form opens without warnings:
- % values (shares, yields) are capped to 0–100 (e.g. yield max 120 → 100);
- negative values are set to 0;
- min ≤ typical ≤ max;
- values are rounded to at most 1 decimal, or 3 significant figures below 1. The biopolymer filler split is not shown
  and stays exact.

The tooltip names each tidied value, and the export's `sheet_*` columns hold the untidied sheet values, so the
LCA team sees these fixes as changes. The Python reference (`RAW_REFERENCE`) is computed at the tidied values. The
only typical value this changes is the CFW material density (3.135 → 3.1 kg/m, net GWP −1.1 %). The baselines are
only capped, not rounded.

Most inputs are one sheet row. A few are derived by the tool:

- **Material density** (kg per m span / m wall length / m² coverage) = the `product_size_formulas` formula at the study
  spec (`study_setup`) ÷ spec. Its min/max are the formula at the min/max of the `product size` rows.
- **Material savings from RAW optimisation** reduces the product mass: mass = spec × density × (1 − savings). Typical
  is 0 %, so the typical results equal the sheet's. A `product size` row whose range lies only below its typical value
  gives the maximum (CFW: fibre length 412.5–550 m/m → up to 25 %). That row is then kept at typical in the density
  range, so the saving isn't counted twice.
- **Number of repair events** is not entered: it is the smallest number that reaches the functional unit's service
  life, computed from the expected lifetime and the extension (also in the Monte Carlo, as in Python).
- **Biopolymer fillers**: the recipe (binder + filler combination + split) is shown as resolved shares (Sawdust,
  Seagrass), with min/max derived from the binder and split ranges. The sheet's variation of *which* fillers are used
  isn't represented.
- **Scaled-up** values exist for every input of the product, bill of materials, fabrication steps and circularity
  sections (`up`; `null` = same as typical, shown greyed). They're pre-filled from the sheet's `scaled_up` column
  where it has one (production machine weight / power / output rate / lifetime, as in `raw_lca.cases.scale_up_case`)
  and follow the typical value otherwise, so the default scaled-up results equal Python's. Repair and end of life
  have no scaled-up values. The sheet's `scaled_up` values for end-of-life shares are not used by the model, so the
  tool doesn't show them.
- **Building component performance**: typical / min / max / scaled-up plus a free-text unit. It's recorded for the
  LCA team and not used in the calculation.

## The form

The sections, in order:

1. **Product specifications**: material density, performance (with unit), material savings.
2. **Bill of materials**: one row per material (material, source, share).
3. **Fabrication steps**: one electricity location, then per step: machine weight, power, output rate, lifetime,
   process yield, machine source.
4. **Circularity specifications**: repair on/off, expected lifetime, repair material and extension. The user enters
   the value only: min / max are set to -20 % / +20 % of it, and the number of repairs is calculated (as in Python,
   `raw_lca.cases.repairs_needed`) and shown under the extension. Only the scaled-up product is repaired, with the
   product's own materials and fabrication steps, so the repair numbers are for the scaled-up product.
5. **End of life**.

**Different processes at scale.** Each production step has a *Used in* choice: prototype & scaled-up (default),
prototype only, or scaled-up only. Something that exists in one version
only has one set of values and no scaled-up column, and counts as absent in the other version: a step without
machine wear, electricity or losses (yield 100 %), or no repairs. The Prototype → Scaled-up slider fades it in or
out, so both ends are exact. Materials need no extra choice: a scaled-up share of 0 drops a material, and a
prototype share of 0 adds one at scale only.

These choices are not on the sheet and not in `raw_lca` yet. They are exported as extra rows (`used in` per
production step). To carry them into the paper results, the `lci_raw_*` tabs need a column for them and
`scale_up_case` / `resolve_raw_case` need to use it. At the defaults (every step in both versions) the tool matches
the Python results exactly.

Sections 1–4 have the columns prototype / min / max / scaled-up / comment. A scaled-up cell is grey while it follows
the prototype and highlighted when it differs. Clearing it makes it follow the prototype again.

Each row is marked as changed (compared with the sheet), commented, or to check. A row needs checking when min is
above typical, max is below it, a % is outside 0–100, a value is negative, or a rate, lifetime or yield is 0. The
results panel lists every row to check, with a link to it.

## Results

- **Impact result**: impact category, slider *Prototype → Scaled-up* (moves every input with a scaled-up value from
  its prototype value to it), slider *Today → 2050* (linear blend of the background unit burdens between
  ecoinvent today and premise `image_SSP2-L_2050`), net impact with its 5–95 % range, the burden / benefit bars.
  The per-item breakdown, the list of rows to check and the method notes are collapsed below the chart, so the panel
  fits on one screen.
- **Comparison**: today (fossil-based baseline, bio-based baseline, RAW prototype, RAW scaled-up), then 2050
  (fossil-based baseline, bio-based baseline, RAW scaled-up), under a header per period. Each row has a darker burden bar and a lighter benefit bar (both from zero), a dot for the net
  impact, and whiskers for its 5–95 % range. Hovering shows the numbers. Bars and dots are typical values. Whiskers
  show 5–95 % of a parameter Monte Carlo over the min–max ranges
  (triangular / uniform / fixed as on the sheet, background at its mean): 500 draws in the browser for the RAW case,
  recomputed after every edit (about 0.1 s; it runs in each user's own browser, so several groups at once don't slow
  each other down),
  and 500 draws in `build_data.py` for the baselines (fixed: partners don't edit them). These whiskers don't include the
  ecoinvent background uncertainty of `pipeline/04_uncertainty.ipynb`.

- **What matters most**: a quick global sensitivity analysis on the same Monte Carlo draws. For every number with a
  range, the Spearman rank correlation ρ between its sampled values and the net result. The panel shows ρ² as a share
  of the total, i.e. roughly each number's share of the result's spread; this is exact for a monotonic, additive
  model and a screening measure otherwise. It lists the top 8 for the prototype or the scaled-up result (today, the
  selected category), with ↑ / ↓ for the direction and a link to the row. Rows with |ρ| below 2 / √500 are faded
  (indistinguishable from noise). Numbers that are `fixed` on the sheet or have no range don't take part: most
  timber rows, for example. The full analysis is the Sobol' one in `pipeline/05_sensitivity.ipynb`.

## Export, import, submission

- **Export rows (.csv)**: one row per input, in sheet terms: `case, stage, item, qualifier, parameter, unit, typical,
  min, max, scaled_up, comments, changed, sheet_typical, sheet_min, sheet_max, sheet_scaled_up, sheet_source`.
  `scaled_up` is always the value used (the typical value if not set). `changed` names what differs from the sheet,
  including values the tool tidied, or says `new row`.
- **Export / Import (.json)**: the full state of one case (inputs, ranges, comments), to continue later.
- **General comments** (optional, above the submit button): sent and exported as one extra row (`stage` general,
  `item` submission, `parameter` general comment, the text in `comments`), so the receiving sheet needs no new column.
- **Submit to RAW sheet** sends the same rows plus the comparison-chart values (all impact categories) to a Google Apps Script Web App.
  Until a URL is set, it downloads the CSV instead.

### Submitting to a Google Sheet (to set up)

1. Create the workshop Google Sheet with the account that should own the responses.
2. In Extensions → Apps Script, paste the script shown in the tool's *Submission settings* (generated from
   `ROW_COLUMNS` in `app.js`, so it always matches the columns) and save.
3. Deploy → New deployment → Web app, execute as *Me*, access *Anyone*. Approve the permissions (Google warns the
   app is unverified: Advanced → Go to …). Copy the `.../exec` URL. Opening it in a browser should show
   `{"ok":true,"message":"RAW workshop submissions endpoint is running"}`.
4. Put the URL in `SUBMIT_URL` at the top of `app.js` (or paste it in *Submission settings* for one session).
5. Submit a test case. The tool should say *Saved ✓*. Check the two tabs the script creates:
   - `submissions`: one row per input: `submission_id, submitted_at, name, organisation, snapshot` + the export
     columns;
   - `submission_results`: the seven comparison-chart products (baselines today and 2050, prototype, scaled-up,
     scaled-up 2050) in every impact category: burden, benefit, net, 5 % and 95 %.

After editing the script: Deploy → Manage deployments → Edit → Version: *New version*. Otherwise the URL keeps
running the old code.

How saving works:
- every submission gets an id (`<case>-<time>-<random>`), shown to the partner and written on every row;
- the script writes under a lock, so simultaneous submissions can't overwrite each other, and it skips an id that is
  already in the sheet;
- it replies `{ok, id, rows}` (or `{ok: false, error}`), which the tool reads and shows as *Saved ✓* or *Not saved*;
- if the reply can't be read (offline, or the browser blocks it), the submission may still have arrived: the tool
  doesn't send it again, but downloads a CSV backup and says so. A *Not saved* also downloads the CSV.

The URL is visible in `app.js`, so anyone who has it can post to the sheet: share the tool only with the partners.
The sheet stores partners' names and organisations: tell them before they submit.

## Deploying

Static files, no build step and no server: open `index.html` directly, or copy the folder to any static host (e.g.
GitHub Pages).
