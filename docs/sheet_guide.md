# Guide to the Google Sheet

The sheet is where all numbers of the model live. This guide is the same text as the `README` tab of the sheet.

## Tab groups

Tabs are grouped and ordered by their role in the LCA. Each group has its own colour: the tab, its header row
(darker shade) and its cells (lighter shade). The `lci_raw_*` tabs are filled in by the **case partners**; all other
tabs are maintained by the LCA team.

| group | colour | tabs | what |
|---|---|---|---|
| 1 Goal and scope | purple | `fu_comparison`, `study_setup`, `impact_categories`, `scenarios` | the four comparative LCAs (functional unit, service life, baselines compared), product sizes, analysis settings, charted categories, background scenarios |
| 2 Life cycle inventories (LCI) | teal | `lci_raw_biopol`, `lci_raw_timber`, `lci_raw_cfw`, `lci_raw_knit`, `lci_baselines` | the LCI of each RAW prototype (materials, machines, lifetime, repair, end of life, location, scaled-up machine values) and of each baseline (per kg of product) |
| 3 Product size (parametric LCA) | green | `product_size_formulas` | the formula giving the kg of each product from its size (its constants are `product size` rows on the LCI tabs) |
| 4 Data sources and end-of-life constants | blue | `unit_burdens_dataSources`, `benefits_constants_dataSources`, `EoL_constants`, `eol_routes` | link to ecoinvent (and `eol_type` of waste treatments), carbon content, per-material end-of-life constants (allocation factor, quality, heating value), the RAW end-of-life routes |
| 5 Modelling constants | orange | `constants`, `gwpbio_table`, `dcf_bern` | physical and method constants, carbon storage method tables |

The `README` tab (grey) comes first.

## `fu_comparison`: one row per RAW case

Defines the functional unit of each of the four comparative LCAs and which two conventional baseline products
(`lci_baselines` tab) it's compared with.

| column | meaning |
|---|---|
| `raw_case` | the RAW case (matches `case_name` on `product_size_formulas` and `case` on the `lci_raw_*` tabs) |
| `fu_name`, `function` | free text describing the functional unit; `function` doesn't affect the model |
| `service_life`, `service_life_unit` | the reference period this comparative LCA is scaled over. Every product's burdens and benefits are multiplied by `service_life / L`, where `L` is that product's own service life (see below) |
| `quantifier_label`, `quantifier_unit` | documentation of the spec that sizes the product (e.g. "beam span", "m"); the formula machinery still uses `spec_variable`/`spec_label`/`spec_unit` on `product_size_formulas` |
| `baseline_biobased`, `baseline_fossil` | the conventional bio-based and fossil-based baseline this RAW case is compared with (case names on `lci_baselines`); leave one blank if there's no baseline of that kind yet |

## Product size rows (on every LCI tab)

The constants in a case's `product_size_formulas` formula (e.g. `depth_ratio`, `fibre_length_per_span`,
`areal_density`, densities) are rows on that case's LCI tab, with `stage = product size`, `item = product` and
`parameter` = the name used in the formula. Like any other number they have a typical value and a range:
- on the `lci_raw_*` tabs they are in the **design** group, so design improvements (e.g. a shorter fibre path per
  metre of span, a lighter knit per m2) show up in the sensitivity analysis and in the uncertainty analysis;
- on `lci_baselines` they vary in the uncertainty analysis only.

`wall_height` is part of the functional unit (a 3 m high partition wall): it is `fixed` and must be equal for the
compared walls. Glulam's `density` is also fixed, because glulam timber is bought in m3 at 1 / density m3 per kg of
product (its production row).

## `lci_baselines`: LCI per kg of product

Same columns as a RAW case tab (below), except `group`: the baselines are not in the sensitivity analysis. Every
input and output of a baseline is one row, per kg of product; the `product_size_formulas` tab gives how many kg of
product the functional unit needs.

| rows | `item` | `qualifier` | `parameter` |
|---|---|---|---|
| size formula constants (`stage = product size`) | `product` | - | the name used in the formula (see above) |
| materials and other inputs (`stage = production`) | an activity on `unit_burdens_dataSources` (e.g. `concrete`, `formwork`) | - | `amount per kg product` (unit of that activity per kg, e.g. `kg/kg`, `m3/kg`) |
| end of life (`stage = end-of-life`) | the waste treatment: an activity on `unit_burdens_dataSources` with an `eol_type` | the material that is treated: a row of `EoL_constants` | `amount per kg product` (kg of that material to that treatment per kg of product) |
| service life (`stage = use`) | `product` | - | `service life` |
| location (`stage = general`) | `product` | - | `location` (country whose electricity is displaced by energy recovery) |

A material may be split over several treatments (e.g. clay brick: 0.42 kg recycled, 0.42 kg landfilled). Material
that is reused needs no row. The model applies the circular footprint formula per row, from the treatment's
`eol_type` and the material's `EoL_constants` row:
- **recycling / composting**: treatment burden x (1 - A); credit -(1 - A) x Q x burden of the material's
  `recycling_credit_activity` (only if one is set on `EoL_constants`).
- **incineration**: full treatment burden; energy credit from the material's heating value and conversion
  efficiencies (heat and electricity at the case `location`).
- **landfill**: full treatment burden.

A material with a carbon content on `benefits_constants_dataSources` (e.g. `glulam timber`) gets the biogenic
carbon storage credit for the product's service life, for the mass in its end-of-life rows.

## A RAW case LCI tab (`lci_raw_*`): one row = one number

| column | meaning |
|---|---|
| `case` | the RAW case (do not change) |
| `group` | which kind of choice this number is (used by the sensitivity analysis, RAW cases only): **design** (what the product is made of), **manufacturing** (machines, loading, yield), **circularity** (lifetime, repair, end of life), **location** (which country's electricity) |
| `stage` | product size, production, repair, use, end-of-life, or general (the location row) |
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
`item` (the material must exist on the `unit_burdens_dataSources` tab, the step is any name). The constants of your
product's size formula are the `product size` rows at the top of the tab (see above).

### Things to know
- **Shares** (bill of materials, end-of-life routes) of one stage should add up to 100 %; the model re-normalises them.
- **Process yield** is the share of the material entering a step that leaves it as good output (the rest becomes waste).
- **Output rate** is how much material the machine processes per hour (kg/hr); **machine lifetime** is in operating hours.
- The **number of repair events** is not entered: it is the smallest number of repairs that makes the product last
  the service life of its functional unit (`fu_comparison`): (service life - expected lifetime) / lifetime extension
  per repair, rounded up, and 0 if the expected lifetime already reaches it.
- To be **scaled up**, a production step's `scaled_up` cells must all be filled in (machine weight, power, output
  rate, machine lifetime); steps with `scaled_up` left blank keep their prototype values in the scaled-up variant.
- Do not rename tabs or columns, and do not delete rows without asking: the model reads them by name.

## What happens to your numbers

`typical` values give the central results; `min`/`max` give the uncertainty bars and tell the sensitivity analysis
which of your choices matter most in each of the four groups.
