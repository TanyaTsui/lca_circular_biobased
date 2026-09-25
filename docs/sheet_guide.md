# Guide to the Google Sheet

The sheet is where all numbers of the model live. This guide is the same text as the `README` tab of the sheet.

## Who fills what

| tabs | who | what |
|---|---|---|
| `case_biopol`, `case_timber`, `case_cfw`, `case_knit` | **case partners** | the numbers of your prototype: size formula, materials, machines, lifetime, repair, end of life, locations |
| `processes_typicalValues` | partners (read) / LCA team | typical small- and large-scale machine values you can use as a reference |
| `baselines`, `products`, `baseline_eol_setup` | LCA team | conventional products the RAW cases are compared with, and the formulas that turn a product size into amounts |
| `materials` tabs (`unit_burdens_dataSources`, `benefits_constants_dataSources`, `EoL_constants`), `constants`, `eol_routes`, `gwpbio_table`, `dcf_bern` | LCA team | link to ecoinvent, carbon content, recycling/incineration constants, method constants |
| `study_setup`, `scenarios`, `impact_categories` | LCA team | product sizes compared, reference service life, scenarios, charted categories, analysis settings |
| `lcaModel_logic` | - | a worked example of the calculation (explanation only) |

## A case tab: one row = one number

| column | meaning |
|---|---|
| `case` | the RAW case (do not change) |
| `group` | which kind of choice this number is: **design** (what the product is made of and how big it is), **manufacturing** (machines, loading, yield), **circularity** (lifetime, repair, end of life), **location** (which country's electricity) |
| `stage` | production, repair, use, end-of-life, or product (size formula) |
| `item` | the material, the process step or "waste" the number belongs to. The order of the process steps is the order of the rows |
| `parameter`, `description`, `unit` | what the number is |
| **`typical`** | your best estimate |
| **`min`, `max`** | how low / high it could realistically be. Leave both equal to `typical` if it is fixed |
| `distribution` | how values between min and max are treated: `triangular` (typical is the most likely value), `uniform`, `fixed`, or `choice` (for text values such as a country code) |
| `choices` | for `choice` rows: the options, separated by `;` (empty for locations = the list on `study_setup`) |
| **`source`** | where the number comes from (measurement, a colleague, a paper, a datasheet) |
| **`status`** | `placeholder` (a first guess by the LCA team), `partner estimate`, `measured`, `literature` |
| `comments` | anything the LCA team should know |

Please fill in `typical`, `min`, `max`, `source` and set `status` for every row. Empty ranges or `placeholder` rows are
highlighted. You may add rows for extra materials or process steps: copy an existing row of the same kind and change
`item` (the material must exist on the `unit_burdens_dataSources` tab, the step is any name).

### Things to know
- **Shares** (bill of materials, end-of-life routes) of one stage should add up to 100 %; the model re-normalises them.
- **Process yield** is the share of the material entering a step that leaves it as good output (the rest becomes waste).
- **Output rate** is how much material the machine processes per hour (kg/hr); **machine lifetime** is in operating hours.
- **Size formula** rows (`stage = product`) are the constants inside the formula that turns e.g. a beam span into a mass
  (density, depth/width ratios, fibre length per span, ...). Their names are used on the `products` tab.
- To be **scaled up** with the sheet's large-scale machine values, a production step must carry the exact name of a
  machine on the `processes_typicalValues` tab (e.g. "CNC milling", "3D printing", "CNC knitting", "Coreless filament winding").
- Do not rename tabs or columns, and do not delete rows without asking: the model reads them by name.

## What happens to your numbers

`typical` values give the central results; `min`/`max` give the uncertainty bars and tell the sensitivity analysis
which of your choices matter most in each of the four groups.
