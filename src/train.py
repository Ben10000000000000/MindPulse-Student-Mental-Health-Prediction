"""Canonical training entry point for MindPulse.

Use ``python -m src.train`` for the production CatBoost pipeline.  The API,
training code, metadata, and evaluation reports therefore always describe the
same estimator and feature-engineering path.
"""
from .train_production import main

if __name__ == "__main__":
    main()
