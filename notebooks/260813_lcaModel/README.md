# RAW LCA model: pipeline

Google Sheet (`1Vx1XDlohZulOEaFFgliiqx3JaZp4rxqQ-LC8B0_qGW4`) -> data prep notebooks -> `data/processed/*.csv` -> model -> charts.
All model parameters live on the sheet; nothing is defined in the repo except the code, the sheet layout and the regression fixture in `test_engine.py`.

## Run order

| step | notebook | reads (sheet tab) | writes (`data/processed/`) |
|---|---|---|---|
| 1 | `01_dataPrep.ipynb` | `unit_burdens_dataSources`, `benefits_constants_dataSources`, `EoL_constants` (+ `data/data_sources/supplementary_sources.csv`) | `unit_burdens.csv` (baseline), `benefits_constants.csv`, `eol_constants.csv` |
| 2 | `01b_dataPrep_prospective.ipynb` | same source rows | adds the premise scenarios to `unit_burdens.csv` |
| 3 | `01c_dataPrep_productLCI.ipynb` | `product_LCIs`, `processes_typicalValues`, `raw_cases`, `raw_bom`, `raw_chain`, `raw_parameters` (+ `data/data_sources/baseline_eol_assumptions.csv`) | `product_lci.csv`, `machine_params.csv`, `raw_*.csv`, `baseline_eol.csv`, glulam row in `benefits_constants.csv` |
| 4 | `03_productComparison.ipynb` | all of the above | charts |

Run 01c **after** 01: 01 regenerates `benefits_constants.csv`, and 01c adds the glulam row to it.
`02_model.ipynb` is the original single-product (1 kg) model; it is kept as the reference the engine is tested against.

## Code

- `lca_engine.py`: model functions (same formulas as `02_model.ipynb`), safe formula evaluator, RAW and baseline runners.
- `cases.py`: builds the RAW cases from the `raw_*` tabs (`load_raw_cases`) and the scaled-up variants from `processes_typicalValues` (`scale_up_case`). No parameters in the file.
- `test_engine.py`: `python test_engine.py`. Checks the product-LCI formulas against the sheet, the sheet loader and scale-up, and reproduces `02_model.ipynb` (baseline and a prospective scenario).

## Scaled-up RAW cases

A production step whose `step_name` (tab `raw_chain`) equals a `machining_process` on `processes_typicalValues` gets that machine's large-scale weight, lifetime, output efficiency and power. Everything else is unchanged. To scale another step, change its name or add the machine to the tab.

## Things to know

- Baseline end-of-life shares are assumptions in `data/data_sources/baseline_eol_assumptions.csv` (not on the sheet yet).
- Baselines per RAW case come from the `comparison_raw_*` flags in `product_LCIs`; `ds.extra_baselines` in `03` adds more.
- The incineration credit multiplies LHV in MJ by an electricity burden per kWh (inherited from `02_model.ipynb`), which overstates the electricity credit by a factor of 3.6. Kept so results match `02`.
