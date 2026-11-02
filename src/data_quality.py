"""Create a reproducible data-quality report for the project dataset."""
import json
import pandas as pd
from .config import XLSX_PATH, DATA_PATH, REPORT_DIR, FEATURES, TARGET
from .data import load_clean

def main():
    if XLSX_PATH.exists():
        raw = pd.read_excel(XLSX_PATH, sheet_name="Dataset")
    else:
        raw = pd.read_csv(DATA_PATH)
    clean = load_clean()
    report = {
        "source": XLSX_PATH.name if XLSX_PATH.exists() else DATA_PATH.name,
        "raw_rows": int(len(raw)), "clean_rows": int(len(clean)),
        "duplicates_removed": int(len(raw)-len(clean)),
        "columns": list(raw.columns),
        "missing_values": {k:int(v) for k,v in raw.isna().sum().items()},
        "target": TARGET,
        "target_min": float(clean[TARGET].min()), "target_max": float(clean[TARGET].max()),
        "feature_count": len(FEATURES),
        "numeric_features": [f for f in FEATURES if f in clean.columns and pd.api.types.is_numeric_dtype(clean[f])],
        "categorical_features": [f for f in FEATURES if f not in ["Age", "Avg_Daily_Usage_Hours", "Daily_Unlocks", "Study_Hours", "Physical_Activity_Hours", "Sleep_Hours_Per_Night"]],
        "academic_level_count": int(clean["Academic_Level"].nunique()),
        "academic_levels": sorted(clean["Academic_Level"].astype(str).unique().tolist()),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR/'data_quality.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
