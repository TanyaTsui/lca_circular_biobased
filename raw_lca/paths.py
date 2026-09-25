"""Folders used by the pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "sheet_snapshot"
BACKGROUND = ROOT / "data" / "background"
RESULTS = ROOT / "results"


def newest_snapshot() -> Path:
    """Newest folder of data/sheet_snapshot/ (they are named by date)."""
    folders = sorted(p for p in SNAPSHOTS.glob("*") if (p / "products.csv").exists())
    if not folders:
        raise FileNotFoundError(f"no sheet snapshot in {SNAPSHOTS} - run pipeline/01_fetch_sheet.py")
    return folders[-1]
