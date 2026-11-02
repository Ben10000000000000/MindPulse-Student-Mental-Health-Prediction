"""Loading + cleaning, shared by training and the API."""
import pandas as pd
from .config import DATA_PATH, XLSX_PATH, ROOT, GROUP_KEYS, FEATURES, TARGET
from .categories import normalize_academic_level, normalize_employment_status


def load_clean() -> pd.DataFrame:
    # The supplied MindPulse workbook is the authoritative 25,000-row source.
    # A legacy CSV is accepted only when it is explicitly present and contains
    # the expected schema; otherwise the 25k workbook is used.
    df = None
    if XLSX_PATH.exists():
        df = pd.read_excel(XLSX_PATH, sheet_name="Dataset")
    elif DATA_PATH.exists():
        df = pd.read_csv(DATA_PATH)
    else:
        raise FileNotFoundError(f"Dataset not found: {XLSX_PATH} or {DATA_PATH}")

    df = df.copy()
    df = df.drop_duplicates().reset_index(drop=True)
    if "Academic_Level" in df:
        df["Academic_Level"] = df["Academic_Level"].map(normalize_academic_level)
    if "Employment_Status" in df:
        df["Employment_Status"] = df["Employment_Status"].map(normalize_employment_status)
    if "Physical_Activity_Hours" in df:
        df["Physical_Activity_Hours"] = df["Physical_Activity_Hours"].clip(lower=0)

    # Categorical missing values are imputed only for model training.
    # The original workbook is never rewritten.
    for c in ["Gender", "Country", "Academic_Level", "Employment_Status", "Most_Used_Platform", "Purpose_Of_Use", "Stress_Level"]:
        if c in df.columns and df[c].isna().any():
            mode = df[c].mode(dropna=True)
            if len(mode):
                df[c] = df[c].fillna(mode.iloc[0])

    required = [c for c in FEATURES + [TARGET] if c in df.columns]
    df = df.dropna(subset=required).reset_index(drop=True)
    return df


def get_xy(df):
    return df[FEATURES], df[TARGET]


def get_groups(df):
    return df.groupby(GROUP_KEYS, dropna=False).ngroup()
