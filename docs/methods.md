# Methods

This document describes what the model computes. Every number it uses is either on the Google Sheet (see
[sheet_guide.md](sheet_guide.md)), in the background data (`data/background/`, built from ecoinvent and premise),
or a physical constant on the sheet's `constants` tab. Code: `raw_lca/`.

## 1. Scope and functional unit

Each **RAW case** (biopol wall, reclaimed-timber beam, coreless filament winding beam, knitted membrane) is compared
with its **baseline products** (its `baseline_biobased`/`baseline_fossil` on the `fu_comparison` tab) for the same
**product spec** (beam span in m, wall length in m, membrane coverage in m2; values on `study_setup`). The
`fu_comparison` tab states each comparative LCA's functional unit: its name, function (documentation only), and
quantifier (the spec that sizes the product).

All products of one comparative LCA are compared over that RAW case's **reference service life** `RSL`
(`fu_comparison.service_life`). The burdens and benefits of a product with service life `L` are multiplied by
`RSL / L` (per-year amortisation, continuous in `L`). `L` of a RAW case is `expected lifetime + n_repairs x
lifetime extension per repair`, where `n_repairs` is the smallest number of repairs that reaches `RSL`:
`ceil((RSL - expected lifetime) / lifetime extension per repair)`, and 0 if the expected lifetime already reaches it
(so `L >= RSL` whenever repair extends the life). `L` of a baseline is its `service life` on the `lci_baselines` tab. Results are in the
EF v3.1 impact categories (25 categories in the data, the ones plotted are flagged on `impact_categories`).

**Product size.** The mass (kg) of every product follows from the spec through one formula per product on the
`product_size_formulas` tab (e.g. beam mass = depth x width x span x density with depth = span / `depth_ratio`). The constants in the formulas are
fixed values on the `product_size_constants` tab, not numbers inside the formula, and are not varied by the
uncertainty or sensitivity analysis.

## 2. RAW case life cycle

Stages, all per product spec:

1. **Materials.** The bill of materials (BOM, `share of input mass` per material and source: virgin, co-product,
   recycled, wild-harvested) is applied to the total input mass needed at the first production step.
   Burden of one kg: direct unit burden for virgin, co-product and wild-harvested material; for **recycled** material
   the circular footprint formula (CFF): `A x E_recycled + (1 - A) x E_virgin x (Q_s / Q_p)` with `A` (allocation factor)
   and `Q_s` (quality ratio) from `EoL_constants`, `Q_p` from `constants`.
2. **Production.** The process chain is solved backward from the product mass: the required input of a step is its
   output divided by its `process yield`. Per step: process time = input / `output rate`; machine wear (kg) =
   `machine weight` x time / `machine lifetime`; electricity (kWh) = `power` x time. Impact = machine wear x burden of
   `machine wear` (virgin or recycled machine) + electricity x burden of `energy use` in the step's country.
3. **Repair.** Each of `n_repairs` events adds `share of product mass per repair` of new material, produced with the
   repair chain in the same way. Repair events are sequential: event `i` (of `n`) stores its carbon for
   `(n - i + 1) x lifetime extension` years.
4. **End of life.** The product mass plus all repair mass is split into five routes (composted, recycled open loop,
   recycled closed loop, incinerated, landfilled). Treatment burden = share x mass x burden of the route's treatment
   activity (`eol_routes` tab); for composting and recycling it is multiplied by `(1 - A)` (CFF). Credits:
   composting and open-loop recycling: `-(1 - A) x share x mass x avoided burden x Q_s`; incineration:
   `-share x mass x LHV x (efficiency_heat x burden_heat + efficiency_electricity x burden_electricity / 3.6)` with LHV and
   conversion efficiencies of the `RAW product` row of `EoL_constants` (fuel energy in MJ, heat burden per MJ,
   electricity burden per kWh). Closed-loop recycling gets no credit (it would double count the recycled input).
5. **Carbon storage** (climate change only). Carbon content and rotation period per material: `materials_carbon.csv`.
   *Virgin* material (growth attributable to this product): `C x kg x 44/12 x GWP_bio(rotation, storage)` with the
   table of Guest et al. (2012) (sheet tab `gwpbio_table`), interpolated in the storage period. *Co-product, recycled and
   wild-harvested* material (carbon that would otherwise be released): `C x kg x 44/12 x (DCF(storage) - 1)` with the
   dynamic characterisation factor of Levasseur et al. (2010) built from the Bern-model coefficients (tab `dcf_bern`)
   over the time horizon on `constants`. Storage time = product service life (production material) or the time
   left after the repair event (repair material).

**Scaled-up variant.** Each RAW case is also run with its production machines scaled up: a production step whose
`scaled_up` cells are filled in (machine weight, power, output rate, machine lifetime, on its own `lci_raw_*` tab) uses
those values instead of the prototype ones. All other steps, the repair chain, BOM, lifetimes and end of life are
unchanged.

## 3. Baseline products

A baseline is an LCI per kg of product (`lci_baselines` tab) times the product mass from the `product_size_formulas` formula.
Cradle-to-gate burden = sum over the production rows of unit burden x amount per kg x product mass.

End of life: each end-of-life row sends `m` kg of one material to one waste treatment. The circular footprint
formula is applied per row with the treated material's constants from `EoL_constants` (allocation factor `A`,
quality ratio `Q`, heating value, conversion efficiencies), depending on the treatment's `eol_type`
(`unit_burdens_dataSources`):
- recycling / composting: `(1 - A) x m x E_treatment`, and a credit `-(1 - A) x m x Q x E_substituted`, where
  `E_substituted` is the material's `recycling_credit_activity` (no credit where none is set);
- incineration: `m x E_treatment`, and an energy credit as for the RAW cases, from the material's heating value and
  efficiencies, with electricity of the case's `location`;
- landfill: `m x E_treatment`.

Materials with a carbon content (`benefits_constants_dataSources`; of the baselines only glulam timber) get the
growth-type storage credit for the product's service life, for their mass in the end-of-life rows. Transport of
materials to site is not added for either RAW or baselines.

The reinforced concrete beam's formwork is a fixed amount per kg of beam, exact at the 6 m reference span; formwork
area grows with span^2 while beam mass grows with span^3, so the spec sweep over-counts formwork at longer spans
(0.4 % of the beam's net GWP at 12 m).

## 4. Scenarios (background)

`baseline` (ecoinvent 3.12 cut-off as it is) is *today*. The 2050 background is an IAM scenario built with premise
(`scenarios` tab: model, pathway, year); premise rewrites the whole database (electricity, industry, transport, ...).
Only the background changes between scenarios; the product designs and all sheet parameters stay the same.

## 5. Uncertainty analysis

Monte Carlo (`raw_lca/uncertainty.py`). Each parameter of the sheet is drawn from its distribution
(`triangular` with mode = typical value, `uniform`, or `fixed`; categorical parameters - locations, machine source - are
kept at their typical value). BOM and end-of-life shares are re-normalised to 100 % after sampling. The same draws
are used in every scenario (paired), and each draw also uses one iteration of the background Monte Carlo
(`data/background/unit_burden_samples_<scenario>.npz`): the technosphere and biosphere matrices are sampled from
ecoinvent's uncertainty data once per iteration and all activities are solved on that draw, so processes shared between
materials are correlated. When there are more parameter draws than background iterations (2000 vs. 500 by default), draw `i`
uses background iteration `i mod 500`. Characterisation factors, carbon contents and the constants on the sheet are not sampled;
background uncertainty is only sampled for the countries in `location_choices` and only for the scenarios flagged `in_results`.
Reported: median and the percentile interval set on `study_setup`, and the share of draws in which a RAW case has a lower
net impact than a baseline.

## 6. Sensitivity analysis

`raw_lca/sensitivity.py`. Output: net impact of a RAW case per impact category. Inputs: the parameters of the case that
have a range (min < max, or several choices). **Groups**: *design* (product formula constants, BOM), *manufacturing*
(machine weight, power, output rate, machine lifetime, process yield, machine source), *circularity* (lifetime, repair,
end-of-life shares), *location* (electricity country of each step and of the disposal grid; drawn uniformly from
`location_choices`). Methods: variance-based total-order (Jansen) and first-order (Saltelli) Sobol' indices with
bootstrap 95 % intervals, per group and per parameter; one-at-a-time swings between min and max (tornado). The
implementation is tested against the analytic Ishigami function. Background uncertainty is not part of the sensitivity
analysis.

## 7. Conventions and limitations to keep in mind

- **Placeholders.** The `status` column of the sheet marks every parameter as placeholder / partner estimate / measured /
  literature. Results are only as good as these values; `03_results` prints the status counts.
- **Waste-treatment burdens** are ecoinvent treatment datasets whose reference flow is waste (negative sign); the absolute
  value is used as burden (as in the earlier notebook model).
- **Circularity credits** (avoided heat and electricity of incineration, avoided compost/wood chips) appear in every impact
  category, not only climate change, and can be large for products with high incineration shares.
- **Biogenic carbon:** storage credits are computed for climate change only; the biogenic CO2 released at incineration is
  part of the incineration treatment dataset. The interplay of storage credit and incineration should be reviewed.
- **Baseline lifetimes and end-of-life shares** are LCA-team assumptions (status `placeholder` until sourced).
- **Change relative to the earlier notebook model (`02_model.ipynb`, tag `v0.1-product-comparison`):** the incineration
  electricity credit multiplied the fuel energy in MJ by a burden per kWh; it is now divided by 3.6 MJ/kWh (constant on
  the sheet). Setting `mj_per_kwh = 1` reproduces the earlier numbers exactly (`tests/test_model.py`). Results are also
  now scaled to the reference service life, and the CO2/C molar ratio and all constants come from the sheet.
