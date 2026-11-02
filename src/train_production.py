"""Reproducible production training, validation, and final fit for MindPulse.

Evaluation is performed before the final all-data fit:
* 80/20 target-band-stratified holdout test
* 3-fold GroupKFold CV on the training partition only
* separate group holdout for unseen combinations of profile attributes

The holdout scores are evaluation estimates. The final saved artifact is then
refit on all clean rows for deployment; its training fit is not reported as test
performance. Score bands use the same 0-5 / 5-7 / 7-10 boundaries as the API.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, train_test_split

from .config import BAND_EDGES, BAND_LABELS, FEATURES, RANDOM_STATE, REPORT_DIR, MODEL_PATH, TARGET, TEST_SIZE, XLSX_PATH, DATA_PATH
from .model import BASE_FEATURES, CAT, MODEL_FEATURES, MindPulseModel, engineer
from .categories import normalize_academic_level, normalize_employment_status


def _load_training_data() -> tuple[pd.DataFrame, dict]:
    """Load the canonical workbook, validate schema, and apply explicit cleaning."""
    if XLSX_PATH.exists():
        raw = pd.read_excel(XLSX_PATH, sheet_name="Dataset")
        source = XLSX_PATH.name
    elif DATA_PATH.exists():
        raw = pd.read_csv(DATA_PATH)
        source = DATA_PATH.name
    else:
        raise FileNotFoundError(f"Dataset not found: {XLSX_PATH} or {DATA_PATH}")

    missing_columns = sorted(set(BASE_FEATURES + [TARGET]) - set(raw.columns))
    if missing_columns:
        raise ValueError(f"Dataset is missing required columns: {missing_columns}")

    raw_rows = len(raw)
    # Normalize raw localized academic labels and employment labels before splitting.
    raw["Academic_Level"] = raw["Academic_Level"].map(normalize_academic_level)
    raw["Employment_Status"] = raw["Employment_Status"].map(normalize_employment_status)
    duplicate_rows = int(raw.duplicated().sum())
    df = raw.drop_duplicates().copy().reset_index(drop=True)
    missing_before = {c: int(df[c].isna().sum()) for c in BASE_FEATURES + [TARGET]}

    numeric_features = [c for c in BASE_FEATURES if c not in CAT]
    for col in numeric_features + [TARGET]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Never impute a target or numeric model input from the target distribution.
    # Drop rows with missing required numeric inputs/target; preserve missing
    # categorical values as an explicit category handled by CatBoost.
    required_numeric = numeric_features + [TARGET]
    df = df.dropna(subset=required_numeric).reset_index(drop=True)
    for col in CAT:
        df[col] = df[col].fillna("__MISSING__").astype(str).str.strip()
        df.loc[df[col].eq(""), col] = "__MISSING__"

    if df.empty:
        raise ValueError("No usable rows remain after validating required numeric fields and target.")
    target_min, target_max = float(df[TARGET].min()), float(df[TARGET].max())
    if target_min < 0 or target_max > 10:
        raise ValueError(f"Expected {TARGET} in the 0-10 range, found {target_min:g} to {target_max:g}.")

    quality = {
        "source": source,
        "raw_rows": int(raw_rows),
        "duplicates_removed": duplicate_rows,
        "clean_rows": int(len(df)),
        "dropped_for_missing_numeric_or_target": int(raw_rows - duplicate_rows - len(df)),
        "missing_before_cleaning": missing_before,
        "categorical_missing_policy": "Explicit __MISSING__ category; no target-based imputation",
        "target": TARGET,
        "target_min": target_min,
        "target_max": target_max,
        "base_feature_count": len(BASE_FEATURES),
        "model_feature_count": len(MODEL_FEATURES),
        "academic_level_count": int(df["Academic_Level"].nunique()),
    }
    return df, quality


def score_bands(scores) -> np.ndarray:
    """Use the single source of truth for score categories (0-5, 5-7, 7-10)."""
    values = np.asarray(scores, dtype=float)
    return np.where(values < BAND_EDGES[1], BAND_LABELS[0],
                    np.where(values < BAND_EDGES[2], BAND_LABELS[1], BAND_LABELS[2]))


def regression_metrics(actual, predicted) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return {
        "r2": float(r2_score(actual, predicted)),
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "band_accuracy": float(accuracy_score(score_bands(actual), score_bands(predicted))),
        "band_macro_f1": float(f1_score(score_bands(actual), score_bands(predicted), labels=BAND_LABELS, average="macro", zero_division=0)),
    }


def make_model() -> CatBoostRegressor:
    """One explicitly named estimator used for CV, holdouts, and production."""
    return CatBoostRegressor(
        iterations=100,
        depth=5,
        learning_rate=0.04,
        l2_leaf_reg=10,
        loss_function="RMSE",
        random_seed=RANDOM_STATE,
        verbose=False,
        thread_count=2,
        allow_writing_files=False,
    )


def main() -> None:
    started = time.time()
    df, quality = _load_training_data()
    X = engineer(df[BASE_FEATURES])
    y = df[TARGET].astype(float).reset_index(drop=True)
    groups = df[ ["Country", "Gender", "Academic_Level", "Employment_Status", "Most_Used_Platform", "Purpose_Of_Use", "Stress_Level"] ].astype(str).agg("|".join, axis=1).reset_index(drop=True)
    cat_indices = [X.columns.get_loc(c) for c in CAT]
    bands = score_bands(y)

    all_indices = np.arange(len(df))
    train_idx, test_idx = train_test_split(
        all_indices, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=bands
    )
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    groups_train = groups.iloc[train_idx]

    print(f"Loaded {len(df):,} clean rows; fitting 3-fold grouped validation...", flush=True)
    # CV never sees the final holdout test partition.
    cv_scores = []
    cv = GroupKFold(n_splits=3)
    for fit_idx, val_idx in cv.split(X_train, y_train, groups_train):
        fold_model = make_model()
        fold_model.fit(X_train.iloc[fit_idx], y_train.iloc[fit_idx], cat_features=cat_indices)
        cv_scores.append(r2_score(y_train.iloc[val_idx], fold_model.predict(X_train.iloc[val_idx])))

    print("Grouped CV complete; fitting holdout evaluation model...", flush=True)
    evaluation_model = make_model()
    fit_started = time.time()
    evaluation_model.fit(X_train, y_train, cat_features=cat_indices)
    fit_seconds = round(time.time() - fit_started, 2)
    test_metrics = regression_metrics(y_test, evaluation_model.predict(X_test))

    print("Holdout evaluation complete; checking unseen profile combinations...", flush=True)
    # Additional group split evaluates unseen profile combinations separately.
    group_split = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    unseen_train_idx, unseen_test_idx = next(group_split.split(X, y, groups))
    unseen_model = make_model()
    unseen_model.fit(X.iloc[unseen_train_idx], y.iloc[unseen_train_idx], cat_features=cat_indices)
    unseen_metrics = regression_metrics(y.iloc[unseen_test_idx], unseen_model.predict(X.iloc[unseen_test_idx]))

    metrics = {
        "chosen_model": "CatBoostRegressor + deterministic feature engineering",
        "task": "Regression of Mental_Health_Score (0-10); wellness bands are derived from predicted score",
        "training_rows": int(len(df)),
        "evaluation_split": {
            "train_rows": int(len(train_idx)), "test_rows": int(len(test_idx)),
            "strategy": "80/20 stratified by score band; test set held out from CV and fitting during evaluation",
        },
        "cv": {"folds": 3, "grouped_on_profile": True, "mean_r2": float(np.mean(cv_scores)), "std_r2": float(np.std(cv_scores))},
        "random_test": test_metrics,
        "strict_unseen_profile_test": unseen_metrics,
        "training_partition_fit": regression_metrics(y_train, evaluation_model.predict(X_train)),
        "params": {"iterations": 100, "depth": 5, "learning_rate": 0.04, "l2_leaf_reg": 10, "random_seed": RANDOM_STATE, "thread_count": 2},
        "evaluation_fit_seconds": fit_seconds,
        "score_band_edges": BAND_EDGES,
        "score_band_labels": BAND_LABELS,
    }

    print("Validation complete; fitting final deployment model on all clean rows...", flush=True)
    # The deployable model is deliberately refit on all clean rows only AFTER
    # evaluation metrics have been computed and stored separately.
    final_model = make_model()
    final_started = time.time()
    final_model.fit(X, y, cat_features=cat_indices)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(MindPulseModel(final_model), MODEL_PATH, compress=3)

    import sklearn
    meta = {
        "artifact_format_version": 2,
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "chosen_model": metrics["chosen_model"],
        "estimator_class": "catboost.CatBoostRegressor",
        "training_rows": int(len(df)),
        "raw_rows": quality["raw_rows"],
        "duplicates_removed": quality["duplicates_removed"],
        "missing_values_before_imputation": quality["missing_before_cleaning"],
        "categorical_missing_policy": quality["categorical_missing_policy"],
        "base_features": BASE_FEATURES,
        "model_features": MODEL_FEATURES,
        "derived_features": [c for c in MODEL_FEATURES if c not in BASE_FEATURES],
        "score_band_edges": BAND_EDGES,
        "score_band_labels": BAND_LABELS,
        "academic_level_count": int(df["Academic_Level"].nunique()),
        "academic_levels": sorted(df["Academic_Level"].astype(str).unique().tolist()),
        "employment_statuses": sorted(df["Employment_Status"].astype(str).unique().tolist()),
        "params": metrics["params"],
        "final_fit": "refit on all cleaned rows after holdout evaluation",
        "final_fit_seconds": round(time.time() - final_started, 2),
        "sklearn_version": sklearn.__version__,
        "python_sklearn_version": sklearn.__version__,
    }
    quality["score_band_edges"] = BAND_EDGES
    quality["score_band_labels"] = BAND_LABELS
    (MODEL_PATH.with_name("model_meta.json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (REPORT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (REPORT_DIR / "data_quality.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")

    pd.DataFrame([
        {"metric": k, "random_holdout_test": v, "strict_unseen_profile_test": unseen_metrics.get(k)}
        for k, v in test_metrics.items()
    ]).to_csv(REPORT_DIR / "regression_comparison.csv", index=False)

    # This chart is generated from the held-out evaluation model, not the
    # all-data production fit, so the visualization remains a genuine test view.
    test_predictions = evaluation_model.predict(X_test)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(y_test, test_predictions, s=8, alpha=0.35)
    ax.plot([0, 10], [0, 10], "r--", linewidth=1)
    ax.set(xlabel="Actual score", ylabel="Predicted score", title="MindPulse CatBoost — untouched holdout test")
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    fig.tight_layout()
    fig.savefig(REPORT_DIR / "predicted_vs_actual.png", dpi=130)
    plt.close(fig)

    card = {
        "model": metrics["chosen_model"],
        "estimator_class": meta["estimator_class"],
        "task": metrics["task"],
        "selection": "Fixed CatBoost estimator; grouped cross-validation is a validation estimate, not test-set model selection.",
        "training_rows": int(len(df)),
        "evaluation": {"grouped_cv_r2_mean": metrics["cv"]["mean_r2"], "grouped_cv_r2_std": metrics["cv"]["std_r2"], "random_test": test_metrics, "strict_unseen_profile_test": unseen_metrics},
        "score_bands": {"edges": BAND_EDGES, "labels": BAND_LABELS},
        "limitations": [
            "This survey-style dataset may be synthetic or unrepresentative of real student populations.",
            "Predictions are educational wellness estimates, not medical diagnoses or clinical assessments.",
            "Feature-ablation explanations are associations, not causal effects.",
            "Random holdout and profile-group holdout measure different generalization settings; neither proves real-world clinical validity.",
        ],
    }
    (REPORT_DIR / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")

    print(json.dumps(metrics, indent=2))
    print(f"Saved production model trained on {len(df):,} clean rows: {MODEL_PATH}")
    print(f"Completed in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
