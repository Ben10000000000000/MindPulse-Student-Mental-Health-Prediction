"""Regenerate the model card from the canonical production evaluation report."""
import json
from .config import REPORT_DIR

def main():
    metrics = json.loads((REPORT_DIR / "metrics.json").read_text(encoding="utf-8"))
    card = {
        "model": metrics.get("chosen_model", "unknown"),
        "task": metrics.get("task", "Regression of Mental_Health_Score (0-10)"),
        "selection": "The production estimator is fixed in src/train_production.py; grouped CV is a validation estimate, not holdout-test model selection.",
        "training_rows": metrics.get("training_rows"),
        "evaluation": {
            "grouped_cv": metrics.get("cv", {}),
            "random_test": metrics.get("random_test", {}),
            "strict_unseen_profile_test": metrics.get("strict_unseen_profile_test", {}),
        },
        "score_bands": {"edges": metrics.get("score_band_edges"), "labels": metrics.get("score_band_labels")},
        "limitations": [
            "This survey-style dataset may be synthetic or unrepresentative of real student populations.",
            "Predictions are educational wellness estimates, not medical diagnoses or clinical assessments.",
            "Feature-ablation explanations are associations, not causal effects.",
            "Random holdout and profile-group holdout measure different generalization settings; neither proves real-world clinical validity.",
        ],
    }
    (REPORT_DIR / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(json.dumps(card, indent=2))

if __name__ == "__main__":
    main()
