# Guide to the Google Sheet

The sheet is where all numbers of the model live. This guide is the same text as the `README` tab of the sheet.

## Who fills what

| tabs | who | what |
|---|---|---|
| `fu_comparison` | LCA team | the four comparative LCAs: each RAW case's functional unit (name, function, service life, quantifier) and the two baseline products it's compared with |
| `case_biopol`, `case_timber`, `case_cfw`, `case_knit` | **case partners** | the LCI numbers of your prototype: materials, machines, lifetime, repair, end of life, locations, scaled-up machine values |
| `baselines`, `products`, `product_size_constants`, `baseline_eol_setup` | LCA team | conventional products the RAW cases are compared with, the constants that size them, and the formulas that turn a product size into amounts |
| `materials` tabs (`unit_burdens_dataSources`, `benefits_constants_dataSources`, `EoL_constants`), `constants`, `eol_routes`, `gwpbio_table`, `dcf_bern` | LCA team | data sources: link to ecoinvent, carbon content, recycling/incineration constants, method constants |
| `study_setup`, `scenarios`, `impact_categories` | LCA team | product sizes compared, scenarios, charted categories, analysis settings |
| `lcaModel_logic` | - | a worked example of the calculation (explanation only) |

## `fu_comparison`: one row per RAW case

Defines the functional unit of each of the four comparative LCAs and which two conventional baseline products
(`baselines` tab) it's compared with.

| column | meaning |
|---|---|
| `raw_case` | the RAW case (matches `case_name` on `products` and `case` on the `case_*` tabs) |
| `fu_name`, `function` | free text describing the functional unit; `function` doesn't affect the model |
| `service_life`, `service_life_unit` | the reference period this comparative LCA is scaled over. Every product's burdens and benefits are multiplied by `service_life / L`, where `L` is that product's own service life (see below) |
| `quantifier_label`, `quantifier_unit` | documentation of the spec that sizes the product (e.g. "beam span", "m"); the formula machinery still uses `spec_variable`/`spec_label`/`spec_unit` on `products` |
| `baseline_biobased`, `baseline_fossil` | the conventional bio-based and fossil-based baseline this RAW case is compared with (case names on `baselines`); leave one blank if there's no baseline of that kind yet |

## `product_size_constants`: one row per constant

The fixed constants used in a case's `products` formula (e.g. `depth_ratio`, `steel_share`, `wall_height`). These
are geometry/material constants, not LCI data: they are **never varied** by the uncertainty or sensitivity
analysis, unlike the numbers on `case_*`/`baselines`.

| column | meaning |
|---|---|
| `case` | the case this constant belongs to (RAW case or baseline) |
| `parameter` | the name used in the `formula` column of `products` |
| `description`, `unit` | what the number is |
| `value` | the fixed value used by the model |
| `source`, `comments` | where the number comes from, anything the LCA team should know |

## A case tab: one row = one number

| column | meaning |
|---|---|
| `case` | the RAW case (do not change) |
| `group` | which kind of choice this number is: **design** (what the product is made of), **manufacturing** (machines, loading, yield), **circularity** (lifetime, repair, end of life), **location** (which country's electricity) |
| `stage` | production, repair, use, or end-of-life |
| `item` | the material, the process step or "waste" the number belongs to. The order of the process steps is the order of the rows |
| `parameter`, `description`, `unit` | what the number is |
| **`typical`** | your best estimate |
| **`min`, `max`** | how low / high it could realistically be. Leave both equal to `typical` if it is fixed |
| `scaled_up` | for production steps only: the machine weight / power / output rate / machine lifetime to use once this step runs at large scale. Leave blank to keep the step at prototype scale; if filled in, all four of these parameters must be filled in for that step |
| `distribution` | how values between min and max are treated: `triangular` (typical is the most likely value), `uniform`, `fixed`, or `choice` (for text values such as a country code) |
| `choices` | for `choice` rows: the options, separated by `;` (empty for locations = the list on `study_setup`) |
| **`source`** | where the number comes from (measurement, a colleague, a paper, a datasheet) |
| **`status`** | `placeholder` (a first guess by the LCA team), `partner estimate`, `measured`, `literature` |
| `comments` | anything the LCA team should know |

Please fill in `typical`, `min`, `max`, `source` and set `status` for every row. Empty ranges or `placeholder` rows are
highlighted. You may add rows for extra materials or process steps: copy an existing row of the same kind and change
`item` (the material must exist on the `unit_burdens_dataSources` tab, the step is any name). Product-size-formula
constants (density, depth/width ratios, ...) don't live here any more - they're on `product_size_constants`.

### Things to know
- **Shares** (bill of materials, end-of-life routes) of one stage should add up to 100 %; the model re-normalises them.
- **Process yield** is the share of the material entering a step that leaves it as good output (the rest becomes waste).
- **Output rate** is how much material the machine processes per hour (kg/hr); **machine lifetime** is in operating hours.
- To be **scaled up**, a production step's `scaled_up` cells must all be filled in (machine weight, power, output
  rate, machine lifetime); steps with `scaled_up` left blank keep their prototype values in the scaled-up variant.
- Do not rename tabs or columns, and do not delete rows without asking: the model reads them by name.

## What happens to your numbers

`typical` values give the central results; `min`/`max` give the uncertainty bars and tell the sensitivity analysis
which of your choices matter most in each of the four groups.
