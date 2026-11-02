"""Production model wrapper. Keeps the public API on the original form input fields including employment status while
adding deterministic, non-user-entered derived features before CatBoost prediction."""
import numpy as np
import pandas as pd

BASE_FEATURES = [
    "Age", "Avg_Daily_Usage_Hours", "Daily_Unlocks", "Study_Hours",
    "Physical_Activity_Hours", "Sleep_Hours_Per_Night", "Stress_Level",
    "Gender", "Academic_Level", "Employment_Status", "Most_Used_Platform", "Purpose_Of_Use", "Country"
]
NUMERIC = ["Age", "Avg_Daily_Usage_Hours", "Daily_Unlocks", "Study_Hours", "Physical_Activity_Hours", "Sleep_Hours_Per_Night"]
CAT = ["Stress_Level", "Gender", "Academic_Level", "Employment_Status", "Most_Used_Platform", "Purpose_Of_Use", "Country"]
DERIVED = ["Wake_Hours", "Usage_Wake_Ratio", "Unlocks_Per_Usage_Hour", "Study_Activity_Hours", "Sleep_Deficit", "Digital_Study_Ratio", "Daily_Load", "Activity_Sleep_Ratio"]
MODEL_FEATURES = NUMERIC + DERIVED + CAT


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    for c in CAT:
        if c in x.columns:
            x[c] = x[c].fillna("__MISSING__").astype(str)
    x["Wake_Hours"] = (24.0 - x["Sleep_Hours_Per_Night"]).clip(lower=0.5)
    x["Usage_Wake_Ratio"] = x["Avg_Daily_Usage_Hours"] / x["Wake_Hours"]
    x["Unlocks_Per_Usage_Hour"] = x["Daily_Unlocks"] / x["Avg_Daily_Usage_Hours"].clip(lower=0.25)
    x["Study_Activity_Hours"] = x["Study_Hours"] + x["Physical_Activity_Hours"]
    x["Sleep_Deficit"] = 8.0 - x["Sleep_Hours_Per_Night"]
    x["Digital_Study_Ratio"] = x["Avg_Daily_Usage_Hours"] / x["Study_Hours"].clip(lower=0.25)
    x["Daily_Load"] = x["Avg_Daily_Usage_Hours"] + x["Study_Hours"] + x["Physical_Activity_Hours"]
    x["Activity_Sleep_Ratio"] = x["Physical_Activity_Hours"] / x["Sleep_Hours_Per_Night"].clip(lower=0.5)
    return x[MODEL_FEATURES]


class MindPulseModel:
    def __init__(self, estimator):
        self.estimator = estimator

    def predict(self, X):
        return np.asarray(self.estimator.predict(engineer(X)), dtype=float)

