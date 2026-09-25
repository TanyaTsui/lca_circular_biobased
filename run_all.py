"""
Regenerate every result from the committed inputs:

    python run_all.py               tests, sheet validation, then results, uncertainty and sensitivity notebooks
    python run_all.py --background  also rebuild data/background (needs Brightway, ecoinvent, premise; hours)
    python run_all.py --fetch       also download a fresh snapshot of the Google Sheet first

Notebooks are executed in place (outputs are stored in them); figures and tables go to results/.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def run(*cmd):
    print("\n$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=ROOT, check=True)


def scrub_paths(name):
    """Replace this machine's home and repository paths in the stored outputs of a notebook (so no local paths are published)."""
    path = ROOT / "pipeline" / f"{name}.ipynb"
    text = path.read_text()
    for prefix, repl in ((str(ROOT), "<repo>"), (str(Path.home()), "~"), (json.dumps(str(ROOT))[1:-1], "<repo>")):
        text = text.replace(prefix, repl)
    path.write_text(text)


def notebook(name):
    run(PY, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
        "--ExecutePreprocessor.timeout=-1", f"pipeline/{name}.ipynb")
    scrub_paths(name)


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        run(PY, "pipeline/01_fetch_sheet.py")
    else:
        run(PY, "pipeline/01_fetch_sheet.py", "--check")
    run(PY, "-m", "pytest", "-q", "tests")
    if "--background" in sys.argv:
        notebook("02_background_lci")
    for nb in ("03_results", "04_uncertainty", "05_sensitivity"):
        notebook(nb)
    print("\nDone. Figures: results/figures, tables: results/tables")
