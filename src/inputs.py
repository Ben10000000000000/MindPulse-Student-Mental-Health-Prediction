"""Make user input safe for the model.

Why this exists
---------------
The current 25,000-row model learned from the observed ranges in the bundled workbook; the API reports those ranges dynamically. If someone types sleep = 0 h or age = 10, some models (especially SVR) extrapolate to nonsense.
So we (1) give the model the nearest value it has seen and (2) tell the user, instead of silently guessing.
Country names are also tidied (case, spaces, common aliases) so "india", " India " and "United States"
reach the model as the names it was trained on.
"""
from __future__ import annotations
import pandas as pd

COUNTRY_ALIASES = {
    "united states": "USA", "united states of america": "USA", "us": "USA", "u.s": "USA", "u.s.a": "USA", "america": "USA",
    "united kingdom": "UK", "great britain": "UK", "britain": "UK", "england": "UK", "scotland": "UK", "wales": "UK",
    "united arab emirates": "UAE", "korea": "South Korea", "republic of korea": "South Korea",
    "czechia": "Czech Republic", "bosnia and herzegovina": "Bosnia", "trinidad and tobago": "Trinidad",
    "hongkong": "Hong Kong", "viet nam": "Vietnam", "russian federation": "Russia", "holland": "Netherlands",
    "the netherlands": "Netherlands", "bharat": "India", "republic of india": "India", "macedonia": "North Macedonia",
    "turkiye": "Turkey", "türkiye": "Turkey", "ivory coast": "Other", "vatican": "Vatican City",
}

# (payload key, DataFrame column, human label, unit)
NUMERIC_RANGES = [
    ("age", "Age", "Age", "years"),
    ("avg_daily_usage_hours", "Avg_Daily_Usage_Hours", "Daily screen time", "h"),
    ("daily_unlocks", "Daily_Unlocks", "Phone unlocks per day", ""),
    ("study_hours", "Study_Hours", "Study time", "h"),
    ("physical_activity_hours", "Physical_Activity_Hours", "Physical activity", "h"),
    ("sleep_hours_per_night", "Sleep_Hours_Per_Night", "Sleep", "h"),
]


def training_ranges(df: pd.DataFrame) -> dict:
    return {k: (float(df[c].min()), float(df[c].max())) for k, c, _, _ in NUMERIC_RANGES}


def known_countries(df: pd.DataFrame) -> dict:
    """lower-case name -> canonical name exactly as used in the training data."""
    return {c.lower(): c for c in df["Country"].unique()}


def clean_text(raw) -> str:
    return " ".join(str(raw).split())


def normalize_country(raw: str, known: dict) -> tuple[str, str | None]:
    """Return (country for the model, optional plain-language note)."""
    shown = clean_text(raw)
    key = shown.lower().rstrip(".")
    key = COUNTRY_ALIASES.get(key, key)
    hit = known.get(key.lower())
    if hit:
        return hit, None
    return "Other", (f"\"{shown}\" is not a country the model saw in training, so it is scored with the "
                     "dataset's general \"Other\" group. Country has a small effect on the score.")


def clip_to_training(d: dict, ranges: dict) -> tuple[dict, list[str]]:
    """Copy of `d` with numbers limited to the trained range + one plain-language note per change."""
    out, notes = dict(d), []
    for k, _, label, unit in NUMERIC_RANGES:
        lo, hi = ranges[k]
        v = d[k]
        if v < lo or v > hi:
            new = min(max(v, lo), hi)
            out[k] = int(round(new)) if isinstance(v, int) else new
            u = f" {unit}" if unit else ""
            notes.append(f"{label} ({v:g}{u}) is outside the range the model learned from ({lo:g}-{hi:g}{u}). "
                         f"The score uses {out[k]:g}{u}, so treat it as approximate. Your guidance below still uses your real value.")
    return out, notes
