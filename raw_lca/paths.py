"""Folders used by the pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "sheet_snapshot"
BACKGROUND = ROOT / "data" / "background"
RESULTS = ROOT / "results"


def newest_snapshot() -> Path:
    """Newest folder of data/sheet_snapshot/ that has the redesigned sheet tabs."""
    folders = sorted(p for p in SNAPSHOTS.glob("*") if (p / "products.csv").exists())
    if folders:
        return folders[-1]
    templates = ROOT / "data" / "sheet_templates"       # transition: before the redesigned sheet exists
    print(f"NOTICE: no sheet snapshot with the redesigned tabs yet - using {templates}")
    return templates
