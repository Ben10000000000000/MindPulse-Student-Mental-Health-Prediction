# MindPulse — Student Mental-Health / Wellness Prediction

MindPulse is an academic web application that predicts a **0–10 mental-health score** from student lifestyle, study, social-media-use and stress inputs. It also produces a non-diagnostic wellness category and a root-cause/action report.

> **Important:** this is an educational ML project, not a medical diagnostic system.

## What was fixed in this version

### 1. The model is trained on the supplied 25,000-row dataset
The model is trained on `data/student_social_media_mental_health.csv` (25,000 rows, 20 columns). `src/train_production.py` prefers `data/MindPulse_Student_Mental_Health_Dataset_v1.xlsx` if that file is placed in `data/`; it is not included in this ZIP, so the CSV is used. The saved metadata shows:

- training rows: **25,000**
- duplicate rows: **0**
- missing target values: **0**
- academic-level categories: **9 standardized stages** (localized labels are mapped consistently)
- employment-status categories: **4** and included as a real model input
- model inputs: **13 fields** used by the web form/model

The production model was refit on **all 25,000 clean rows** after evaluation.

### 2. Form categories are standardized and dataset-aligned
The form now includes **Employment status** (`None (student only)`, `Part-time job`, `Internship`, `Full-time job`) and the CatBoost model uses it as a categorical feature. Academic-level labels from the workbook are consistently mapped to nine broad education stages, so the dropdown is clear rather than showing 65 localized variants. Country is a dropdown with the 25 countries represented in the training dataset; the API still safely normalizes common country aliases.

### 3. Authentication/session isolation was repaired
The supplied MongoDB screenshot shows these collections:

- `users`
- `login_otps`
- `sessions`
- `predictions`

The code now uses the existing **`login_otps`** collection, creates real server-side session records in **`sessions`**, and stores every new prediction with the authenticated user's `user_id`.

History endpoints require a valid Bearer session. A user cannot request another user's history by changing a browser/client ID.

Logout now revokes the server-side session and clears the private history UI immediately.

### 4. Frontend options and visual layer were upgraded
The existing visual style/animations were retained and enhanced with:

- subtle 3D glass/card tilt
- deeper glass lighting and reflections
- animated authentication glows
- dataset-driven academic-level options
- clearer account/session state
- reduced-motion support

## Model evaluation — honest result

The current production model is a `CatBoostRegressor` with deterministic feature engineering. `python -m src.train` is the single canonical training command; `src/train.py` delegates to the production pipeline, and the API loads the same `MindPulseModel` wrapper used during evaluation.

Current saved evaluation metrics (reproduced by re-running `python -m src.train`; see `reports/metrics.json`):

| Metric | Result |
|---|---:|
| Training rows | **25,000** (20,000 train / 5,000 holdout) |
| 3-fold grouped CV R² (mean ± std) | **0.6368 ± 0.0080** |
| Random holdout test R² | **0.6326** |
| Random holdout test MAE | **0.6055** |
| Random holdout test RMSE | **0.7586** |
| Random holdout wellness-band accuracy | **71.70%** |
| Random holdout macro F1 | **67.52%** |
| Strict unseen-profile R² | **0.6328** |
| Strict unseen-profile MAE / RMSE | **0.6116 / 0.7647** |
| Strict unseen-profile wellness-band accuracy | **70.96%** |
| Strict unseen-profile macro F1 | **66.97%** |

Per-band results on the 5,000-row holdout (`reports/class_metrics.json`):

| Band | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| At risk (< 5) | 0.7157 | 0.4752 | 0.5711 | 604 |
| Moderate (5–6.9) | 0.6986 | 0.8107 | 0.7505 | 2,625 |
| Healthy (>= 7) | 0.7534 | 0.6606 | 0.7040 | 1,771 |

Baselines on the same holdout: Ridge regression R² 0.6356, MAE 0.6035, band accuracy 70.60%; always-predict-the-mean R² 0.0, band accuracy 52.50%. Ridge is about as good as CatBoost on the regression metrics, so most of the learnable signal in this dataset is close to linear. The At-risk band has low recall (47.5%), so the app must not be used as a screening tool.

The production training uses 100 CatBoost boosting iterations for a practical, reproducible baseline on CPU. The untouched 5,000-row random holdout is not used to fit the final model. The final deployable artifact is refit on all 25,000 clean rows after evaluation.

So the project **must not claim 80–90% accuracy from this dataset**. The current evidence is about 71–72% for the three-level score category. That is much better than falsely reporting a high number that comes from leakage or overfitting. The dataset is described by the project owner as synthetic, so these numbers show internal consistency, not performance on real students.

The score-band boundaries are defined once in `src/config.py` and shared by training, metrics, and API: **At risk < 5, Moderate 5–6.9, Healthy >= 7**. The model predicts the continuous score; the app derives the displayed wellness band from that score.

## Run on Windows

From the extracted project folder:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/app
```

API documentation:

```text
http://127.0.0.1:8000/docs
```

### MongoDB

Start your local MongoDB server on:

```text
mongodb://localhost:27017
```

The application expects:

```text
Database: mental_health_db
Collections: users, login_otps, sessions, predictions
```

If MongoDB is not running, the API can still load the model, but authenticated history/prediction saving cannot work. The top status bar reports the database state instead of silently pretending that a record was saved.

## Authentication setup

Copy `.env.example` to `.env` and configure:

```text
AUTH_SECRET=<long random secret>
SMTP_USER=<Gmail sender>
SMTP_PASSWORD=<Gmail App Password>
SMTP_FROM=<Gmail sender>
PUBLIC_APP_URL=http://127.0.0.1:8000/app
```

Use a **Gmail App Password**, not the normal Gmail account password.

Signup flow:

1. User enters name, email and password.
2. MongoDB creates/updates the pending user record.
3. A 6-digit OTP and verification link are sent.
4. User verifies the OTP/link.
5. A server-side session is created.
6. Predictions are saved with that user's MongoDB ID.

Signin flow:

1. Email + password are checked.
2. The account must be verified.
3. A new session is created.
4. `/auth/me`, `/predict`, `/history` and record deletion all require that session.

Logout:

1. The browser sends `/auth/logout`.
2. The server deletes the session record.
3. The browser removes its access token.
4. The private history UI is cleared immediately.

## Existing MongoDB records

Older prediction records that do not contain `user_id` **cannot safely be assigned to a user automatically**, because there is no reliable ownership information in such documents. The repaired application intentionally hides those records from user-scoped history rather than risking one student's data being shown to another student.

New predictions created after this update are user-scoped correctly.

## Useful commands

Check the dataset:

```bat
python -m src.data_quality
```

Retrain the production model on the full workbook:

```bat
python -m src.train
```

Run tests:

```bat
pip install -r requirements-dev.txt
pytest -q
```

## Project structure

```text
api/
  main.py          FastAPI routes, auth and prediction API
  auth.py          password hashing, OTP, signed tokens and sessions
  database.py      MongoDB users/sessions/predictions

src/
  data.py          25k workbook loading/cleaning
  features.py      model preprocessing
  train.py         leak-aware training/evaluation
  inputs.py        input normalization and trained ranges
  root_cause.py   wellness guidance
  explain.py       model explanation

frontend/
  index.html       app + authentication/profile UI
  style.css        glass/3D visual design
  fx.js            background and 3D orb animation
  script.js        form/prediction/report logic
  auth.js          signup/signin/OTP/session/logout
  history.js       private history UI

data/
  student_social_media_mental_health.csv

models/
  mental_health_model.joblib
  model_meta.json

reports/
  metrics.json
  data_quality.json
  model_card.json
  class_metrics.json
  regression_comparison.csv
  confusion_matrix.png
  per_class_metrics.png
  predicted_vs_actual.png
```