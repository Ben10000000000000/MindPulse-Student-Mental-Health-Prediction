"""FastAPI service for MindPulse: prediction + root-cause guidance + MongoDB history.

Run from the project folder:   uvicorn api.main:app --reload
Then open:                     http://127.0.0.1:8000/app     (website)   |   http://127.0.0.1:8000/docs   (API docs)
"""
from __future__ import annotations
import json, logging, re, sys, warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import joblib, pandas as pd
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import MODEL_PATH, BAND_EDGES, BAND_LABELS, FEATURES, TARGET   # noqa: E402
from src.data import load_clean                                                # noqa: E402
from src.categories import ACADEMIC_LEVELS, EMPLOYMENT_STATUSES, normalize_academic_level, normalize_employment_status  # noqa: E402
from src.explain import explain_prediction                                     # noqa: E402
from src.inputs import training_ranges, known_countries, normalize_country, clip_to_training, clean_text  # noqa: E402
from src import root_cause as rc                                               # noqa: E402
from api import database as db                                                 # noqa: E402
from api.database import PyMongoError
from api import auth                                          # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mindpulse")
VERSION = "4.0.0"

# ---- load model + reference data once ---------------------------------------------------------------------
with warnings.catch_warnings(record=True) as _w:
    warnings.simplefilter("always")
    model = joblib.load(MODEL_PATH)
MODEL_WARNING = next((str(x.message) for x in _w if "version" in str(x.message).lower()), None)
if MODEL_WARNING:
    log.warning("Model was saved with a different scikit-learn version. Re-run `python -m src.train`. (%s)", MODEL_WARNING[:160])

try:
    MODEL_META = json.loads(MODEL_PATH.with_name("model_meta.json").read_text(encoding="utf-8"))
except Exception:
    MODEL_META = {}
import sklearn                                                                 # noqa: E402
if MODEL_META.get("sklearn_version") and MODEL_META["sklearn_version"] != sklearn.__version__ and not MODEL_WARNING:
    MODEL_WARNING = f"Model trained with scikit-learn {MODEL_META['sklearn_version']}, running {sklearn.__version__}."

DF = load_clean()
RANGES = training_ranges(DF)
KNOWN = known_countries(DF)
REPORTS = ROOT / "reports"

GENDERS = sorted(DF["Gender"].dropna().astype(str).unique().tolist())
LEVELS = list(ACADEMIC_LEVELS)
EMPLOYMENT = list(EMPLOYMENT_STATUSES)
PLATFORMS = sorted(DF["Most_Used_Platform"].dropna().astype(str).unique().tolist())
PURPOSES = sorted(DF["Purpose_Of_Use"].dropna().astype(str).unique().tolist())
STRESS = ["Low", "Medium", "High", "Very High"]


STAGE_ORDER = ["Pre-primary", "Primary", "Lower Secondary", "Upper Secondary", "Vocational / Short-cycle",
               "Bachelor / Undergraduate", "Master / Postgraduate", "Doctoral", "Other"]


def _academic_from_dataset() -> dict:
    """Academic-level labels exactly as written in the training workbook (Dataset sheet, Academic_Level column),
    grouped by the workbook's own Education_Stage_Standard, plus which labels occur in each country.
    The API still normalises whatever is chosen to the model's categories, so predictions are unchanged."""
    try:
        from src.config import XLSX_PATH
        import pandas as pd
        raw = pd.read_excel(XLSX_PATH, sheet_name="Dataset", usecols=["Country", "Academic_Level", "Education_Stage_Standard"]).dropna()
        raw = raw.astype(str)
        stage_of = raw.groupby("Academic_Level")["Education_Stage_Standard"].agg(lambda s: s.value_counts().idxmax())
        counts = raw["Academic_Level"].value_counts()
        stages = []
        for st in STAGE_ORDER + sorted(set(stage_of) - set(STAGE_ORDER)):
            labels = [l for l in counts.index if stage_of[l] == st]
            if labels:
                stages.append({"stage": st, "labels": labels})
        by_country = {c: g["Academic_Level"].value_counts().index.tolist() for c, g in raw.groupby("Country")}
        return {"stages": stages, "by_country": by_country, "count": int(len(counts))}
    except Exception as e:  # optional: the page falls back to the nine model categories
        log.warning("Dataset academic levels unavailable: %s", e)
        return {}


ACADEMIC_DATASET = _academic_from_dataset()


@asynccontextmanager
async def lifespan(_app):
    s = db.init_db()
    if s["online"]:
        try:
            db.init_auth_db()
        except PyMongoError as e:
            log.warning("Auth indexes could not be created: %s", e)
    if not auth.configured():
        log.warning("AUTH_SECRET is missing in .env - sign-in cannot work until you set it.")
    _problem = auth.email_config_problem()
    if _problem:
        log.warning("EMAIL NOT READY: %s", _problem)
    log.info("MongoDB %s (%s/%s)%s", "ONLINE" if s["online"] else "OFFLINE", s["database"], s["collection"],
             "" if s["online"] else f" - {s['error']}. Predictions still work; they will not be saved.")
    yield


app = FastAPI(title="MindPulse Student Wellness Analytics API", version=VERSION, lifespan=lifespan,
              description="Educational ML analytics API with lifestyle root-cause guidance. Not a medical diagnostic system.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["*"])


def _canon(value, options):
    """Case/space-insensitive match to the canonical option, so 'male' or ' very high ' still work."""
    if isinstance(value, str):
        key = " ".join(value.split()).lower()
        for o in options:
            if o.lower() == key:
                return o
    return value


class StudentData(BaseModel):
    age: int = Field(..., ge=5, le=30)
    gender: str = Field(..., min_length=1, max_length=40)
    country: str = Field(..., min_length=1, max_length=60)
    academic_level: str = Field(..., min_length=1, max_length=100)
    employment_status: str = Field(..., min_length=1, max_length=50)
    most_used_platform: str = Field(..., min_length=1, max_length=50)
    purpose_of_use: str = Field(..., min_length=1, max_length=50)
    avg_daily_usage_hours: float = Field(..., ge=0, le=24)
    daily_unlocks: int = Field(..., ge=0, le=1000)
    study_hours: float = Field(..., ge=0, le=24)
    physical_activity_hours: float = Field(..., ge=0, le=24)
    sleep_hours_per_night: float = Field(..., ge=0, le=24)
    stress_level: Literal["Low", "Medium", "High", "Very High"]

    @field_validator("age", mode="before")
    @classmethod
    def _age(cls, v):
        try:
            n = float(v)
        except (TypeError, ValueError):
            return v  # let the normal integer validation report it
        if n < 5 or n > 30:
            raise ValueError("You can check mental analysis only between age 5 and 30, not less than 5 or greater than 30.")
        return v

    @field_validator("gender", mode="before")
    @classmethod
    def _g(cls, v): return _canon(v, GENDERS)

    @field_validator("academic_level", mode="before")
    @classmethod
    def _l(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Academic level is required.")

        raw = " ".join(v.strip().lower().split())

        # Recognize canonical categories and legitimate aliases.
        canonical = {
            "early childhood / pre-primary": "Early Childhood / Pre-primary",
            "primary school": "Primary School",
            "middle school / lower secondary": "Middle School / Lower Secondary",
            "high school / upper secondary": "High School / Upper Secondary",
            "diploma / vocational": "Diploma / Vocational",
            "undergraduate": "Undergraduate",
            "postgraduate (master's)": "Postgraduate (Master's)",
            "doctoral (phd)": "Doctoral (PhD)",
            "other": "Other",
            "unknown": "Other",
            "not specified": "Other",
            "__missing__": "Other",
        }

        if raw in canonical:
            return canonical[raw]

        # Allow localized dataset labels only when the normalizer
        # identifies them as a real education category, not its fallback.
        normalized = normalize_academic_level(v)
        if normalized != "Other":
            return normalized

        raise ValueError(
            "Unsupported academic level. Choose one of the dataset categories."
        )

    @field_validator("employment_status", mode="before")
    @classmethod
    def _employment(cls, v): return normalize_employment_status(v)

    @field_validator("most_used_platform", mode="before")
    @classmethod
    def _p(cls, v): return _canon(v, PLATFORMS)

    @field_validator("purpose_of_use", mode="before")
    @classmethod
    def _u(cls, v): return _canon(v, PURPOSES)

    @field_validator("stress_level", mode="before")
    @classmethod
    def _s(cls, v): return _canon(v, STRESS)

    @field_validator("gender", "academic_level", "employment_status", "most_used_platform", "purpose_of_use", mode="after")
    @classmethod
    def _known_category(cls, v, info):
        pools = {"gender": GENDERS, "academic_level": LEVELS, "employment_status": EMPLOYMENT, "most_used_platform": PLATFORMS, "purpose_of_use": PURPOSES}
        options = pools.get(info.field_name, [])
        value = _canon(v, options)
        if value not in options:
            raise ValueError(f"Unsupported {info.field_name.replace('_', ' ')}. Choose one of the dataset categories.")
        return value

    @field_validator("country", mode="before")
    @classmethod
    def _c(cls, v):
        v = clean_text(v) if v is not None else ""
        if not v:
            raise ValueError("Country is required.")
        return v

    @model_validator(mode="after")
    def _day_budget(self):
        used = self.sleep_hours_per_night + self.study_hours + self.physical_activity_hours
        if used > 24:
            raise ValueError(f"Sleep, study and physical activity add up to {used:g} h, which is more than 24 h in a day. Please check these values.")
        if self.avg_daily_usage_hours > 24 - self.sleep_hours_per_night:
            raise ValueError(f"Screen time ({self.avg_daily_usage_hours:g} h) cannot be more than your waking hours ({24 - self.sleep_hours_per_night:g} h).")
        return self


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)

class EmailRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)

class VerifyRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    code: str = Field(..., min_length=6, max_length=6)
    token: str | None = None

class ResetPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    code: str | None = Field(default=None, min_length=6, max_length=6)
    token: str | None = None
    new_password: str = Field(..., min_length=8, max_length=128)

class SigninRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)   # no minimum here: wrong/short passwords must give "Incorrect email or password", not a 422

class AuthResponse(BaseModel):
    ok: bool
    message: str
    user: dict | None = None
    access_token: str | None = None
    reset_token: str | None = None

class PredictionResponse(BaseModel):
    predicted_mental_health_score: float
    level: str
    model: str
    confidence: str
    component_predictions: dict[str, float]
    explanations: list[dict]
    guidance: dict
    input_notes: list[str] = []
    saved: bool = False
    record_id: str | None = None
    save_error: str | None = None
    created_at: str | None = None


def row_from(d: dict) -> pd.DataFrame:
    return pd.DataFrame([{"Age": d["age"], "Gender": d["gender"], "Country": d["country"], "Academic_Level": d["academic_level"], "Employment_Status": d["employment_status"],
                          "Most_Used_Platform": d["most_used_platform"], "Purpose_Of_Use": d["purpose_of_use"],
                          "Avg_Daily_Usage_Hours": d["avg_daily_usage_hours"], "Daily_Unlocks": d["daily_unlocks"],
                          "Study_Hours": d["study_hours"], "Physical_Activity_Hours": d["physical_activity_hours"],
                          "Sleep_Hours_Per_Night": d["sleep_hours_per_night"], "Stress_Level": d["stress_level"]}])


def band(score: float) -> str:
    return BAND_LABELS[0] if score < BAND_EDGES[1] else BAND_LABELS[1] if score < BAND_EDGES[2] else BAND_LABELS[2]


def component_predictions(row) -> dict:
    out = {}
    if hasattr(model, "estimators_"):
        for name, est in zip(getattr(model, "named_estimators_", {}).keys(), model.estimators_):
            try:
                out[name] = round(float(est.predict(row)[0]), 2)
            except Exception:
                pass
    return out or {"final_model": round(float(model.predict(row)[0]), 2)}


_CID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def client_id(x: str | None) -> str:
    return x if x and _CID.match(x) else "anonymous"


def _mail_503(e: Exception, default: str) -> HTTPException:
    """503 that tells the user the real reason an email failed (bad Gmail login, placeholder .env, no network...)."""
    log.error("Email sending failed: %s: %s", type(e).__name__, e)
    return HTTPException(503, str(e) if isinstance(e, auth.EmailError) else default)


@app.post("/auth/signup", response_model=AuthResponse)
def signup(d: SignupRequest):
    email = auth.normalize_email(d.email)
    if not auth.valid_email(email):
        raise HTTPException(422, "Enter a valid email address.")
    if not auth.email_domain_deliverable(email):
        raise HTTPException(422, "This email domain does not appear able to receive email. Check the address and try again.")
    if len(d.password) < 8 or not re.search(r"[A-Za-z]", d.password) or not re.search(r"\d", d.password):
        raise HTTPException(422, "Password must be at least 8 characters and contain a letter and a number.")
    if not db.db_online():
        raise HTTPException(503, "MongoDB is not reachable. Start MongoDB before creating an account.")
    users = db.get_users()
    existing = users.find_one({"email": email})
    now = pd.Timestamp.now(tz="UTC").to_pydatetime()
    if existing and existing.get("verified"):
        raise HTTPException(409, "An account with this email already exists. Please sign in.")
    user_doc = {"name": d.name.strip(), "email": email, "password_hash": auth.hash_password(d.password), "verified": False, "created_at": existing.get("created_at", now) if existing else now, "updated_at": now}
    if existing:
        users.replace_one({"_id": existing["_id"]}, {**user_doc, "_id": existing["_id"]})
        user_id = str(existing["_id"])
    else:
        user_id = str(users.insert_one(user_doc).inserted_id)
    code = auth.new_otp()
    link_token = auth.make_token(user_id, email, "email_verify", ttl_hours=1)
    try:
        auth.save_otp(email, "signup", code, {"user_id": user_id})
        auth.send_otp_email(email, code, "signup", link_token)
    except Exception as e:
        log.exception("Signup email failed")
        raise _mail_503(e, "Account was prepared, but the verification email could not be sent. Check SMTP settings in .env and try again.") from e
    return AuthResponse(ok=True, message="Verification code sent to your email.", user={"email": email, "name": d.name.strip()})

@app.post("/auth/verify-signup", response_model=AuthResponse)
def verify_signup(d: VerifyRequest):
    email = auth.normalize_email(d.email)
    payload = auth.read_token(d.token, "email_verify") if d.token else None
    otp = None if payload else auth.consume_otp(email, "signup", d.code)
    if not otp and not payload:
        raise HTTPException(400, "Invalid or expired verification code/link.")
    user_id = str((payload or otp).get("sub") or (payload or otp).get("user_id") or "")
    try:
        oid = db.ObjectId(user_id)
        user = db.get_users().find_one({"_id": oid, "email": email})
    except Exception:
        user = None
    if not user:
        raise HTTPException(404, "Account not found.")
    db.get_users().update_one({"_id": user["_id"]}, {"$set": {"verified": True, "verified_at": pd.Timestamp.now(tz="UTC").to_pydatetime()}})
    user["verified"] = True
    db.get_auth_otps().delete_many({"email": email, "purpose": "signup"})
    token = auth.create_session(str(user["_id"]), email)
    return AuthResponse(ok=True, message="Email verified. You are signed in.", user=db.public_user(user), access_token=token)

@app.post("/auth/signin", response_model=AuthResponse)
def signin(d: SigninRequest):
    email = auth.normalize_email(d.email)
    user = db.get_users().find_one({"email": email}) if db.db_online() else None
    if not user or not auth.verify_password(d.password, user.get("password_hash", "")):
        raise HTTPException(401, "Incorrect email or password.")
    if not user.get("verified"):
        code = auth.new_otp(); link = auth.make_token(str(user["_id"]), email, "email_verify", ttl_hours=1)
        try:
            auth.save_otp(email, "signup", code, {"user_id": str(user["_id"])})
            auth.send_otp_email(email, code, "signup", link)
        except Exception as e:
            raise _mail_503(e, "Your email is not verified and the verification email could not be sent. Check SMTP settings.") from e
        raise HTTPException(403, "Please verify your email first. A new verification code was sent.")
    token = auth.create_session(str(user["_id"]), email)
    return AuthResponse(ok=True, message="Signed in successfully.", user=db.public_user(user), access_token=token)

@app.post("/auth/forgot", response_model=AuthResponse)
def forgot(d: EmailRequest):
    email = auth.normalize_email(d.email)
    user = db.get_users().find_one({"email": email}) if db.db_online() else None
    # Do not reveal whether an email is registered.
    if user:
        code = auth.new_otp(); token = auth.make_token(str(user["_id"]), email, "reset", ttl_hours=1)
        try:
            auth.save_otp(email, "reset", code, {"user_id": str(user["_id"])})
            auth.send_otp_email(email, code, "reset", token)
        except Exception as e:
            raise _mail_503(e, "Password reset email could not be sent. Check SMTP settings in .env.") from e
    return AuthResponse(ok=True, message="If an account exists for that email, a reset code has been sent.")

@app.post("/auth/reset", response_model=AuthResponse)
def reset_password(d: ResetPasswordRequest):
    email = auth.normalize_email(d.email)
    payload = auth.read_token(d.token, "reset") if d.token else None
    otp = auth.consume_otp(email, "reset", d.code) if d.code else None
    if not payload and not otp:
        raise HTTPException(400, "Invalid or expired reset code/link.")
    user_id = str((payload or otp).get("sub") or (payload or otp).get("user_id") or "")
    try:
        oid = db.ObjectId(user_id); user = db.get_users().find_one({"_id": oid, "email": email})
    except Exception:
        user = None
    if not user:
        raise HTTPException(404, "Account not found.")
    db.get_users().update_one({"_id": user["_id"]}, {"$set": {"password_hash": auth.hash_password(d.new_password), "updated_at": pd.Timestamp.now(tz="UTC").to_pydatetime()}})
    return AuthResponse(ok=True, message="Password changed successfully. Please sign in.")

def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(401, "Authentication required. Please sign in.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Invalid authentication header. Please sign in again.")
    return token.strip()


def current_user(authorization: str | None) -> dict:
    token = _bearer_token(authorization)
    payload = auth.read_token(token, "session")
    if not payload or not auth.session_active(token):
        raise HTTPException(401, "Your session is invalid or expired. Please sign in again.")
    try:
        user = db.get_users().find_one({"_id": db.ObjectId(payload["sub"]), "email": auth.normalize_email(payload.get("email", "")), "verified": True})
    except Exception:
        user = None
    if not user:
        raise HTTPException(401, "Account not found or not verified. Please sign in again.")
    return user


@app.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    token = _bearer_token(authorization)
    if not auth.read_token(token, "session"):
        raise HTTPException(401, "Invalid session.")
    auth.revoke_session(token)
    return {"ok": True, "message": "Signed out successfully."}


@app.get("/auth/me")
def me(authorization: str | None = Header(default=None)):
    return db.public_user(current_user(authorization))

@app.post("/auth/resend", response_model=AuthResponse)
def resend(d: EmailRequest):
    email = auth.normalize_email(d.email)
    user = db.get_users().find_one({"email": email}) if db.db_online() else None
    if not user:
        return AuthResponse(ok=True, message="If an account exists, a new code has been sent.")
    purpose = "signup" if not user.get("verified") else "reset"
    code = auth.new_otp(); token_purpose = "email_verify" if purpose == "signup" else "reset"
    token = auth.make_token(str(user["_id"]), email, token_purpose, ttl_hours=1)
    try:
        auth.save_otp(email, purpose, code, {"user_id": str(user["_id"])})
        auth.send_otp_email(email, code, purpose, token)
    except Exception as e:
        raise _mail_503(e, "Email could not be sent. Check SMTP settings in .env.") from e
    return AuthResponse(ok=True, message="A new code has been sent.")

@app.get("/")
def home():
    return {"service": "MindPulse", "status": "online", "version": VERSION, "website": "/app", "docs": "/docs"}


@app.get("/options")
def options():
    """Form options + the ranges the model was trained on (the website builds its form from this)."""
    return {"countries": sorted(c for c in KNOWN.values() if c != "Other"), "genders": GENDERS, "academic_levels": LEVELS, "employment_statuses": EMPLOYMENT,
            "platforms": PLATFORMS, "purposes": PURPOSES, "stress_levels": STRESS, "academic_dataset": ACADEMIC_DATASET,
            "dataset_rows": len(DF), "academic_level_count": len(LEVELS), "employment_status_count": len(EMPLOYMENT),
            "trained_ranges": {k: [round(lo, 2), round(hi, 2)] for k, (lo, hi) in RANGES.items()}}


@app.post("/predict", response_model=PredictionResponse)
def predict(d: StudentData, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    real = d.model_dump()
    country, cnote = normalize_country(real["country"], KNOWN)
    model_in, notes = clip_to_training(real, RANGES)          # the MODEL gets clipped values ...
    model_in["country"] = country
    if cnote:
        notes.insert(0, cnote)
    row = row_from(model_in)
    score = round(float(max(0, min(10, model.predict(row)[0]))), 2)
    comps = component_predictions(row)
    spread = max(comps.values()) - min(comps.values()) if len(comps) > 1 else 0
    confidence = "High agreement" if spread < 0.35 else "Moderate agreement" if spread < 0.8 else "Low agreement"
    level = band(score)

    # ... but the GUIDANCE uses what the person really entered.
    first = rc.analyze(real, score)
    keys = [c["key"] for c in first["root_causes"]]
    gains = rc.model_gains(model, row, score, keys)
    guidance = rc.analyze(real, score, gains)
    guidance["projected_score"] = rc.projected_score(model, row, score, keys[:3]) if guidance["mode"] != "maintain" else None
    explanations = explain_prediction(model, row, DF, score)[:6]

    doc = {"user_id": str(user["_id"]), "client_id": str(user["_id"]), "predicted_score": score, "level": level,
           "primary_root_cause": guidance["primary_root_cause"], "mode": guidance["mode"], "pressure_index": guidance["pressure_index"],
           "inputs": real, "model_inputs": model_in,
           "result": {"model": MODEL_META.get("chosen_model", "MindPulse model"), "confidence": confidence, "component_predictions": comps},
           "guidance": guidance, "explanations": explanations, "notes": notes}
    record_id, save_error = db.save_prediction(doc)
    if db.MONGO_REQUIRED and record_id is None:
        raise HTTPException(503, save_error)
    return PredictionResponse(predicted_mental_health_score=score, level=level, model=MODEL_META.get("chosen_model", "MindPulse model"), confidence=confidence,
                              component_predictions=comps, explanations=explanations, guidance=guidance, input_notes=notes,
                              saved=record_id is not None, record_id=record_id, save_error=save_error,
                              created_at=pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M:%S") if record_id else None)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@app.get("/model-info")
def model_info():
    metrics, q = _read(REPORTS / "metrics.json"), _read(REPORTS / "data_quality.json")
    legacy = metrics.get("metrics", {})                       # format written by the old src/train.py
    rnd, strict, cv = metrics.get("random_test", {}), metrics.get("strict_unseen_profile_test", {}), metrics.get("cv", {})

    def pick(new, old):
        return new if new is not None else legacy.get(old, 0)

    training_rows = MODEL_META.get("training_rows", MODEL_META.get("rows", q.get("clean_rows", len(DF))))
    return {"chosen_model": metrics.get("chosen_model", MODEL_META.get("chosen_model", "MindPulse model")),
            "cv_r2": pick(cv.get("mean_r2"), "cv_r2"), "test_r2": pick(rnd.get("r2"), "test_r2"),
            "unseen_r2": pick(strict.get("r2"), "unseen_test_r2"), "test_mae": pick(rnd.get("mae"), "test_mae"),
            "unseen_band_accuracy": pick(strict.get("band_accuracy"), "unseen_band_accuracy"),
            "unseen_band_macro_f1": pick(strict.get("band_macro_f1"), "unseen_band_macro_f1"),
            "training_rows": training_rows, "dataset_rows": len(DF), "raw_rows": q.get("raw_rows", len(DF)), "feature_count": len(FEATURES),
            "academic_level_count": int(DF["Academic_Level"].nunique()), "target": TARGET, "task": "Regression + dataset-aligned 3-level wellness category", "guidance_version": rc.GUIDANCE_VERSION}


@app.get("/analytics")
def analytics():
    s = DF[TARGET]
    return {"rows": len(DF), "score_mean": round(float(s.mean()), 2), "score_median": round(float(s.median()), 2),
            "score_std": round(float(s.std()), 2),
            "bands": {"at_risk": int((s < 5.0).sum()), "moderate": int(((s >= 5.0) & (s < 7)).sum()), "healthy": int((s >= 7).sum())}}


def _db_503(e):
    raise HTTPException(503, "MongoDB is not reachable. Start MongoDB (see README) or check MONGO_URI.") from e


@app.get("/stats")
def stats():
    """Anonymous aggregate of every saved session, computed inside MongoDB."""
    try:
        return {"source": "mongodb", **db.stats()}
    except PyMongoError as e:
        _db_503(e)


@app.get("/history")
def history(limit: int = Query(50, ge=1, le=500), authorization: str | None = Header(default=None)):
    try:
        user = current_user(authorization)
        user_id = str(user["_id"])
        rows = db.list_user_predictions(user_id, limit)
        return {"count": db.count_user_predictions(user_id), "records": rows, "scope": "user"}
    except PyMongoError as e:
        _db_503(e)


@app.get("/history/{record_id}")
def history_item(record_id: str, authorization: str | None = Header(default=None)):
    try:
        user = current_user(authorization)
        rec = db.get_user_prediction(record_id, str(user["_id"]))
    except PyMongoError as e:
        _db_503(e)
    if not rec:
        raise HTTPException(404, "Record not found.")
    return rec


@app.delete("/history/{record_id}")
def delete_item(record_id: str, authorization: str | None = Header(default=None)):
    try:
        user = current_user(authorization)
        n = db.delete_user_prediction(record_id, str(user["_id"]))
    except PyMongoError as e:
        _db_503(e)
    if not n:
        raise HTTPException(404, "Record not found.")
    return {"deleted": n}


@app.delete("/history")
def clear_history(confirm: bool = Query(False), authorization: str | None = Header(default=None)):
    if not confirm:
        raise HTTPException(400, "Add ?confirm=true to delete history.")
    try:
        user = current_user(authorization)
        return {"deleted": db.clear_user_predictions(str(user["_id"]))}
    except PyMongoError as e:
        _db_503(e)


@app.get("/health")
def health():
    s = db.status()
    return {"api": "ok", "version": VERSION, "model_loaded": model is not None, "model_warning": MODEL_WARNING, "model_meta": MODEL_META or None,
            "mongodb": "connected" if s["online"] else "not connected", "database": s}


# The website itself: http://127.0.0.1:8000/app  (same origin as the API, so nothing to configure)
if (ROOT / "frontend").exists():
    app.mount("/app", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")