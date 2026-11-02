"""Lightweight, model-agnostic local explanation for one prediction.
Feature ablation: replace ONE feature by a reference value (median / most common) and see how the score moves.
This is an educational explanation, not a causal one. All variants are scored in a single batch call (fast).
"""
import pandas as pd
from .config import FEATURES, NUMERIC


def explain_prediction(model, row: pd.DataFrame, reference: pd.DataFrame, base_score: float):
    ref = reference[FEATURES]
    variants = []
    for feature in FEATURES:
        changed = row.copy()
        changed[feature] = ref[feature].median() if feature in NUMERIC else ref[feature].mode(dropna=True).iloc[0]
        variants.append(changed)
    preds = model.predict(pd.concat(variants, ignore_index=True))
    out = []
    for feature, altered in zip(FEATURES, preds):
        delta = base_score - float(altered)
        out.append({"feature": feature, "impact": round(delta, 3),
                    "direction": "raises" if delta > 0.03 else "lowers" if delta < -0.03 else "neutral"})
    return sorted(out, key=lambda x: abs(x["impact"]), reverse=True)
