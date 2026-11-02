"""Canonical feature-engineering exports for MindPulse.

The only production estimator is CatBoostRegressor in ``src.train_production``.
This module deliberately contains no alternate estimator or competing training
pipeline, so training and inference share exactly the same engineered columns.
"""
from .model import BASE_FEATURES, MODEL_FEATURES, engineer

__all__ = ["BASE_FEATURES", "MODEL_FEATURES", "engineer"]
