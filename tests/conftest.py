import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# inputs used by the tests: the newest sheet snapshot (data/sheet_snapshot/<date>/)
from raw_lca.paths import newest_snapshot  # noqa: E402

SNAPSHOT = newest_snapshot()
BACKGROUND = ROOT / "data" / "background"
GOLDEN = ROOT / "tests" / "golden" / "02_model_biopol.json"
