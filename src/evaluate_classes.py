"""Per-class evaluation for MindPulse (new, standalone file: nothing else in the project imports it).

Run from the project root:   python -m src.evaluate_classes

It repeats the SAME 80/20 band-stratified split and the SAME CatBoost settings used by src/train_production.py,
fits an evaluation model on the 20,000 training rows only, and reports, on the 5,000 untouched test rows:
  * precision, recall, F1 and support for At risk / Moderate / Healthy
  * a confusion matrix (counts and row percentages)
  * two simple baselines on the same split (predict-the-mean, and Ridge regression)
Output: printed tables + reports/class_metrics.json + reports/confusion_matrix.png + reports/per_class_metrics.png (the saved production model is NOT used,
because it was refit on all rows and would have seen the test rows).
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, mean_absolute_error, precision_recall_fscore_support, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .config import BAND_LABELS, RANDOM_STATE, REPORT_DIR, TARGET, TEST_SIZE
from .model import BASE_FEATURES, CAT, MODEL_FEATURES, engineer
from .train_production import _load_training_data, make_model, score_bands


def _band_report(y_true_bands, y_pred_bands) -> dict:
    p, r, f, s = precision_recall_fscore_support(y_true_bands, y_pred_bands, labels=BAND_LABELS, zero_division=0)
    per_class = {lab: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4), "f1": round(float(f[i]), 4), "support": int(s[i])}
                 for i, lab in enumerate(BAND_LABELS)}
    return {"accuracy": round(float(accuracy_score(y_true_bands, y_pred_bands)), 4),
            "macro_f1": round(float(f1_score(y_true_bands, y_pred_bands, labels=BAND_LABELS, average="macro", zero_division=0)), 4),
            "per_class": per_class}


def main() -> None:
    df, _ = _load_training_data()
    X = engineer(df[BASE_FEATURES])
    y = df[TARGET].astype(float).reset_index(drop=True)
    bands = score_bands(y)
    tr, te = train_test_split(np.arange(len(df)), test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=bands)
    X_tr, X_te, y_tr, y_te = X.iloc[tr], X.iloc[te], y.iloc[tr], y.iloc[te]
    true_b = score_bands(y_te)

    cat_idx = [X.columns.get_loc(c) for c in CAT]
    cat = make_model()
    cat.fit(X_tr, y_tr, cat_features=cat_idx)
    cat_pred = np.asarray(cat.predict(X_te), dtype=float)

    mean_pred = np.full(len(y_te), float(y_tr.mean()))

    num = [c for c in MODEL_FEATURES if c not in CAT]
    ridge = make_pipeline(ColumnTransformer([("n", StandardScaler(), num), ("c", OneHotEncoder(handle_unknown="ignore"), CAT)]), Ridge(alpha=1.0))
    ridge.fit(X_tr, y_tr)
    ridge_pred = ridge.predict(X_te)

    results = {}
    for name, pred in [("CatBoost (project model)", cat_pred), ("Ridge regression (baseline)", ridge_pred), ("Always predict the mean (baseline)", mean_pred)]:
        pb = score_bands(pred)
        rep = _band_report(true_b, pb)
        rep.update({"r2": round(float(r2_score(y_te, pred)), 4), "mae": round(float(mean_absolute_error(y_te, pred)), 4)})
        results[name] = rep

    cb = score_bands(cat_pred)
    cm = confusion_matrix(true_b, cb, labels=BAND_LABELS)
    cm_pct = cm / cm.sum(axis=1, keepdims=True) * 100

    print(f"\nTest rows: {len(y_te):,}  (same split as src/train_production.py)\n")
    print("Per-class results, CatBoost model")
    print(f"{'Class':24s}{'Precision':>10s}{'Recall':>9s}{'F1':>8s}{'Rows':>8s}")
    for lab, m in results["CatBoost (project model)"]["per_class"].items():
        print(f"{lab:24s}{m['precision']:>10.3f}{m['recall']:>9.3f}{m['f1']:>8.3f}{m['support']:>8d}")
    print("\nConfusion matrix (rows = actual, columns = predicted)")
    print(pd.DataFrame(cm, index=[f"actual {l}" for l in BAND_LABELS], columns=[f"pred {l}" for l in BAND_LABELS]).to_string())
    print("\nModel vs baselines")
    print(f"{'Model':38s}{'R2':>8s}{'MAE':>8s}{'Band acc':>10s}{'Macro-F1':>10s}")
    for name, m in results.items():
        print(f"{name:38s}{m['r2']:>8.3f}{m['mae']:>8.3f}{m['accuracy']:>10.3f}{m['macro_f1']:>10.3f}")

    REPORT_DIR.mkdir(exist_ok=True)
    out = {"test_rows": int(len(y_te)), "models": results,
           "confusion_matrix_counts": {"labels": BAND_LABELS, "rows_actual_cols_predicted": cm.tolist()},
           "confusion_matrix_row_percent": np.round(cm_pct, 1).tolist()}
    (REPORT_DIR / "class_metrics.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    fig, ax = plt.subplots(figsize=(6.2, 5))
    ax.imshow(cm_pct, cmap="Blues", vmin=0, vmax=100)
    ax.set_xticks(range(3)); ax.set_yticks(range(3))
    ax.set_xticklabels(BAND_LABELS, rotation=15); ax.set_yticklabels(BAND_LABELS)
    ax.set(xlabel="Predicted band", ylabel="Actual band", title="MindPulse confusion matrix (test set, row %)")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{cm_pct[i, j]:.0f}%\n({cm[i, j]})", ha="center", va="center", color="white" if cm_pct[i, j] > 55 else "black")
    fig.tight_layout(); fig.savefig(REPORT_DIR / "confusion_matrix.png", dpi=150); plt.close(fig)
    pc = results["CatBoost (project model)"]["per_class"]
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    w = 0.25
    for k, (metric, colour) in enumerate([("precision", "#4C78A8"), ("recall", "#F58518"), ("f1", "#54A24B")]):
        vals = [pc[lab][metric] for lab in BAND_LABELS]
        bars = ax.bar(np.arange(3) + (k - 1) * w, vals, w, label=metric.capitalize() if metric != "f1" else "F1", color=colour)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.012, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_xticks(range(3)); ax.set_xticklabels([f"{lab}\n({pc[lab]['support']} test rows)" for lab in BAND_LABELS])
    ax.set(ylim=(0, 1.05), ylabel="Score", title="MindPulse per-class precision, recall and F1 (test set)")
    ax.legend(loc="lower right"); fig.tight_layout(); fig.savefig(REPORT_DIR / "per_class_metrics.png", dpi=150); plt.close(fig)
    print(f"\nSaved {REPORT_DIR / 'class_metrics.json'}, {REPORT_DIR / 'confusion_matrix.png'} and {REPORT_DIR / 'per_class_metrics.png'}")


if __name__ == "__main__":
    main()