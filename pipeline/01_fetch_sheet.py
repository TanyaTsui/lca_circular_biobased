"""
Step 1: download the Google Sheet into a dated snapshot and validate it.

    python pipeline/01_fetch_sheet.py                 # fetch a new snapshot, validate it
    python pipeline/01_fetch_sheet.py --check         # only validate the newest snapshot (no network)
    python pipeline/01_fetch_sheet.py --xlsx FILE     # build the snapshot from a downloaded copy of the sheet

All later steps read the newest folder of data/sheet_snapshot/, so results can be reproduced without network access.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raw_lca.paths import SNAPSHOTS, newest_snapshot  # noqa: E402
from raw_lca.sheet import fetch_snapshot, load_tables, report, snapshot_from_xlsx, validate  # noqa: E402


if __name__ == "__main__":
    if "--check" in sys.argv:
        folder = newest_snapshot()
    elif "--xlsx" in sys.argv:
        folder = snapshot_from_xlsx(sys.argv[sys.argv.index("--xlsx") + 1], SNAPSHOTS)
    else:
        folder = fetch_snapshot(SNAPSHOTS)
    print(f"snapshot: {folder}")
    issues = validate(load_tables(folder))
    report(issues)
    sys.exit(1 if any(i.level == "error" for i in issues) else 0)
