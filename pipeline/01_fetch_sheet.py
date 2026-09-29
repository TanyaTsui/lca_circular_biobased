"""
Step 1: download the Google Sheet into a dated snapshot and validate it.

    python pipeline/01_fetch_sheet.py            # fetch a new snapshot, validate it
    python pipeline/01_fetch_sheet.py --check    # only validate the newest snapshot (no network)

All later steps read the newest folder of data/sheet_snapshot/, so results can be reproduced without network access.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raw_lca.sheet import fetch_snapshot, load_tables, report, validate  # noqa: E402

SNAPSHOTS = ROOT / "data" / "sheet_snapshot"


def newest_snapshot() -> Path:
    folders = sorted(p for p in SNAPSHOTS.glob("*") if (p / "fu_comparison.csv").exists())
    if not folders:
        raise SystemExit(f"no snapshot with the redesigned tabs found in {SNAPSHOTS}")
    return folders[-1]


if __name__ == "__main__":
    folder = newest_snapshot() if "--check" in sys.argv else fetch_snapshot(SNAPSHOTS)
    print(f"snapshot: {folder}")
    issues = validate(load_tables(folder))
    report(issues)
    sys.exit(1 if any(i.level == "error" for i in issues) else 0)
