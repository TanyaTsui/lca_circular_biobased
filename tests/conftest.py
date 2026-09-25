import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# inputs used by the tests: the newest sheet snapshot (data/sheet_snapshot/<date>/), else the templates
_snaps = sorted(p for p in (ROOT / "data" / "sheet_snapshot").glob("*") if (p / "case_timber.csv").exists())
SNAPSHOT = _snaps[-1] if _snaps else ROOT / "data" / "sheet_templates"
BACKGROUND = ROOT / "data" / "background"
GOLDEN = ROOT / "tests" / "golden" / "02_model_biopol.json"
