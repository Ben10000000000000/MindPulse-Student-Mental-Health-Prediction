"""Fast checks for model artifact, input contract, and report consistency."""
import json
import sys
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import BAND_EDGES, BAND_LABELS, MODEL_PATH, REPORT_DIR, XLSX_PATH
from src.data import load_clean, get_xy
from src.model import BASE_FEATURES, MODEL_FEATURES, MindPulseModel


def test_saved_artifact_and_metadata_use_same_production_model():
    model = joblib.load(MODEL_PATH)
    meta = json.loads(MODEL_PATH.with_name("model_meta.json").read_text(encoding="utf-8"))
    assert isinstance(model, MindPulseModel)
    assert type(model.estimator).__name__ == meta["estimator_class"].split(".")[-1]
    assert meta["chosen_model"] == "CatBoostRegressor + deterministic feature engineering"
    assert meta["training_rows"] == 25_000
    assert meta["base_features"] == BASE_FEATURES
    assert meta["model_features"] == MODEL_FEATURES


def test_model_predicts_finite_scores_from_current_form_inputs():
    df = load_clean()
    X, _ = get_xy(df)
    assert len(df) == 25_000
    assert len(BASE_FEATURES) == 13
    assert "Employment_Status" in BASE_FEATURES
    predictions = joblib.load(MODEL_PATH).predict(X.iloc[:32])
    assert predictions.shape == (32,)
    assert np.isfinite(predictions).all()
    assert ((predictions >= 0) & (predictions <= 10)).all()


def test_evaluation_reports_match_canonical_estimator_and_score_bands():
    metrics = json.loads((REPORT_DIR / "metrics.json").read_text(encoding="utf-8"))
    card = json.loads((REPORT_DIR / "model_card.json").read_text(encoding="utf-8"))
    meta = json.loads(MODEL_PATH.with_name("model_meta.json").read_text(encoding="utf-8"))
    assert metrics["chosen_model"] == meta["chosen_model"] == card["model"]
    assert metrics["training_rows"] == meta["training_rows"] == 25_000
    assert metrics["score_band_edges"] == BAND_EDGES
    assert metrics["score_band_labels"] == BAND_LABELS
    assert 0 <= metrics["random_test"]["band_accuracy"] <= 1
    assert 0 <= metrics["strict_unseen_profile_test"]["band_macro_f1"] <= 1


def test_score_bands_have_consistent_boundary_convention():
    from src.train_production import score_bands
    assert score_bands([4.99, 5.0, 6.99, 7.0, 10.0]).tolist() == [
        BAND_LABELS[0], BAND_LABELS[1], BAND_LABELS[1], BAND_LABELS[2], BAND_LABELS[2]
    ]
