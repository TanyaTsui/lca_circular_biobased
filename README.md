# RAW biobased construction: comparative LCA

Life cycle assessment of four RAW prototype products (3D-printed biopolymer wall, reclaimed-timber beam, coreless
filament-wound beam, knitted hemp membrane) against conventional baseline products, with today's and a 2050 background,
uncertainty analysis and sensitivity analysis. This repository is the supplementary material of the paper
*(reference to be added)* and reproduces every figure and table of the results.

## How it works

```
Google Sheet ──► sheet snapshot ──► background LCI ──► model ──► results
(all parameters)   data/sheet_snapshot/   data/background/   raw_lca/   results/
                   (frozen CSVs)          (Brightway,        + pipeline notebooks
                                           ecoinvent, premise)
```

- **All parameters are on the Google Sheet** (layout: [docs/RAW_LCA_inputs_v2.xlsx](docs/RAW_LCA_inputs_v2.xlsx), open it in
  Google Sheets to create the sheet; guide for partners: [docs/sheet_guide.md](docs/sheet_guide.md)): the numbers of the RAW cases
  (filled in by the case partners), the baseline products, the constants, the scenarios and the analysis settings. There
  are no parameters in the code.
- A **snapshot** of the sheet (one CSV per tab, `data/sheet_snapshot/<date>/`) is what the results are computed from, so they
  are reproducible without network access.
- The **background data** (unit burdens per material and process from ecoinvent 3.12 and premise scenarios, plus Monte Carlo
  samples of them) is built once by `pipeline/02_background_lci.ipynb` and committed.
- The **model** (`raw_lca/`) turns the parameters and the background data into burdens and benefits per impact category.
  See [docs/methods.md](docs/methods.md) for the equations, conventions and limitations.

## Reproduce the results

```bash
conda env create -f environment.yml && conda activate brightway_env
python run_all.py            # tests, sheet validation, then results, uncertainty and sensitivity (uses the committed data)
```

Steps individually:

| step | command / notebook | output |
|---|---|---|
| 1 | `python pipeline/01_fetch_sheet.py` (`--check` = validate the newest snapshot only; needs `SHEET_ID` in `raw_lca/sheet.py`) | `data/sheet_snapshot/<date>/` |
| 2 | `pipeline/02_background_lci.ipynb` (needs an ecoinvent licence and a premise key, see `.env.example`; hours) | `data/background/` |
| 3 | `pipeline/03_results.ipynb` | bar charts today vs. 2050, spec sweeps: `results/figures`, `results/tables` |
| 4 | `pipeline/04_uncertainty.ipynb` | the same charts with uncertainty intervals, probability tables |
| 5 | `pipeline/05_sensitivity.ipynb` | Sobol' indices per parameter group and parameter, tornado diagrams |
| - | `python -m pytest tests` | 21 tests: formulas, sheet validation, sampling, Sobol' benchmark, background-data completeness, regression against the earlier model |

Steps 3-5 need only the committed snapshot and background data. The number of Monte Carlo draws, seeds, the spec values,
the reference service life, the scenarios and the charted categories are all set on the sheet (`study_setup`,
`scenarios`, `impact_categories`).

## Layout

```
raw_lca/             the package: sheet.py (fetch, validate), params.py (parameter table, sampling), cases.py (resolved
                     products, scale-up), model.py (life cycle model), study.py, uncertainty.py, sensitivity.py,
                     plots.py, background.py (loader), build_background.py (Brightway; only used by step 2)
pipeline/            01_fetch_sheet.py, 02_background_lci.ipynb, 03_results.ipynb, 04_uncertainty.ipynb, 05_sensitivity.ipynb
data/sheet_snapshot/ frozen copies of the sheet
data/background/     unit burdens, carbon content, Monte Carlo samples
results/             figures and tables (generated)
tests/               tests, including the frozen numbers of the earlier notebook model (tests/golden)
docs/                methods.md, sheet_guide.md, RAW_LCA_inputs_v2.xlsx (the sheet layout to import into Google Sheets)
run_all.py           regenerate everything
```

## Changing an input

Edit the value on the sheet, fetch a new snapshot (`python pipeline/01_fetch_sheet.py`, validates it), rerun the notebooks
(`python run_all.py`). Nothing else has to change. A change that alters the background (a different ecoinvent dataset for a
material, a new scenario) needs step 2 as well.

## Status of the inputs

Every parameter row on the sheet has a `status` (placeholder / partner estimate / measured / literature); `03_results`
prints a summary. Numbers marked `placeholder` are first guesses by the LCA team and must be replaced before results
are quoted.

## Citation and licence

*(to be added)*
