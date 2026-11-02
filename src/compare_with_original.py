"""Re-creates the ORIGINAL GitHub model (default Random Forest, top-10 country grouping) and scores it on the
same two test splits used for the upgraded model, so the before/after comparison is fair.
Run:  python -m src.compare_with_original"""
import numpy as np, pandas as pd, json
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split, GroupShuffleSplit
from sklearn.metrics import r2_score, mean_absolute_error
from .config import *
from .data import load_clean, get_groups
from .features import make_preprocessor
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OrdinalEncoder, OneHotEncoder

df = load_clean(); groups = get_groups(df)
top = df.Country.value_counts().index[:10]
df["Country"] = df.Country.where(df.Country.isin(top), "Other")
X, y = df[FEATURES], df[TARGET]
prep = ColumnTransformer([("n", StandardScaler(), NUMERIC), ("o", OrdinalEncoder(categories=[STRESS_ORDER]), ORDINAL),
                          ("c", OneHotEncoder(handle_unknown="ignore"), NOMINAL)])
def run(tri, tei):
    m = Pipeline([("p", prep), ("m", RandomForestRegressor(random_state=42))]).fit(X.iloc[tri], y.iloc[tri])
    return dict(train_r2=r2_score(y.iloc[tri], m.predict(X.iloc[tri])), test_r2=r2_score(y.iloc[tei], m.predict(X.iloc[tei])),
                test_mae=mean_absolute_error(y.iloc[tei], m.predict(X.iloc[tei])))
idx = np.arange(len(df))
a, b = train_test_split(idx, test_size=TEST_SIZE, random_state=RANDOM_STATE)
c, d = next(GroupShuffleSplit(1, test_size=TEST_SIZE, random_state=RANDOM_STATE).split(X, y, groups))
out = {"original_random_split": run(a, b), "original_unseen_profiles_split": run(c, d)}
print(json.dumps(out, indent=2)); json.dump(out, open(REPORT_DIR / "original_model_scores.json", "w"), indent=2)
