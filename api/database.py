"""MongoDB layer: real persistence for predictions, root causes and recommendations.

Configuration (environment variables, or a .env file in the project folder):
    MONGO_URI          mongodb://localhost:27017            (or your MongoDB Atlas connection string)
    MONGO_DB           mental_health_db
    MONGO_COLLECTION   predictions
    MONGO_REQUIRED     false   -> true makes /predict fail with 503 instead of answering without saving
    HISTORY_SCOPE      client  -> each browser sees only its own history ("all" shows every record)

Document schema (schema_version 3), one document per prediction:
    schema_version, created_at (UTC datetime), client_id (anonymous browser id)
    predicted_score, level, primary_root_cause, mode, pressure_index      <- top-level, indexed / aggregated
    inputs        {age, gender, country, ..., stress_level}                <- what the student entered
    model_inputs  {country, ...}                                           <- what the model actually received
    result        {model, confidence, component_predictions}
    guidance      {mode, headline, summary, root_causes[], recommendations[], ...}
    explanations  [ {feature, impact, direction} ]
    notes         [ plain-language data notes ]
Older flat documents (schema 1) are still read correctly.
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone

try:
    from pymongo import MongoClient, DESCENDING, ASCENDING
    from pymongo.errors import PyMongoError
    from bson import ObjectId
    from bson.errors import InvalidId
    PYMONGO_AVAILABLE = True
except ImportError:                      # the API still answers predictions without pymongo
    MongoClient = None
    DESCENDING, ASCENDING = -1, 1
    PYMONGO_AVAILABLE = False
    ObjectId = None

    class PyMongoError(Exception):
        pass

    class InvalidId(Exception):
        pass

log = logging.getLogger("mindpulse.db")


def _load_dotenv() -> None:
    """Tiny .env reader so students do not have to set environment variables by hand."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "mental_health_db")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "predictions")
MONGO_REQUIRED = os.getenv("MONGO_REQUIRED", "false").lower() in ("1", "true", "yes")
HISTORY_SCOPE = os.getenv("HISTORY_SCOPE", "client").lower()
SCHEMA_VERSION = 3

_client = None
last_error: str | None = None


def get_collection():
    """The predictions collection (connects on first use; 2.5 s timeout so the API never hangs)."""
    global _client
    if not PYMONGO_AVAILABLE:
        raise PyMongoError("pymongo is not installed (pip install pymongo)")
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2500, tz_aware=True)
    return _client[MONGO_DB][MONGO_COLLECTION]




def get_users():
    return get_collection().database["users"]

def get_login_otps():
    return get_collection().database["login_otps"]

# api/auth.py calls get_auth_otps(); keep both names pointing at the same collection.
get_auth_otps = get_login_otps

def get_sessions():
    return get_collection().database["sessions"]

def init_auth_db() -> None:
    users = get_users(); otps = get_login_otps()
    sessions = get_sessions()
    users.create_index("email", unique=True, name="users_email_unique")
    otps.create_index("expires_at", expireAfterSeconds=0, name="otp_ttl")
    otps.create_index([("email", ASCENDING), ("purpose", ASCENDING)], name="otp_lookup")
    sessions.create_index("token_hash", unique=True, name="session_token_unique")
    sessions.create_index("expires_at", expireAfterSeconds=0, name="session_ttl")
    sessions.create_index([("user_id", ASCENDING), ("expires_at", DESCENDING)], name="session_user")

def public_user(d: dict) -> dict:
    return {"id": str(d.get("_id")), "name": d.get("name", ""), "email": d.get("email", ""),
            "verified": bool(d.get("verified", False)), "created_at": d.get("created_at").astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if hasattr(d.get("created_at"), "astimezone") else str(d.get("created_at", ""))}


def init_db() -> dict:
    """Ping the server and create indexes. Safe to call repeatedly. Never raises."""
    global last_error
    try:
        col = get_collection()
        col.database.client.admin.command("ping")
        col.create_index([("created_at", DESCENDING)], name="created_at_desc")
        col.create_index([("client_id", ASCENDING), ("created_at", DESCENDING)], name="client_recent")
        col.create_index([("predicted_score", ASCENDING)], name="score")
        col.create_index([("primary_root_cause", ASCENDING), ("level", ASCENDING)], name="cause_level")
        last_error = None
        legacy = col.count_documents({"client_id": {"$exists": False}})
        if legacy:
            log.warning("%d older records have no client_id and are hidden while HISTORY_SCOPE=client "
                        "(set HISTORY_SCOPE=all to show them).", legacy)
        return status()
    except PyMongoError as e:
        last_error = str(e).split(",")[0][:200]
        log.warning("MongoDB not reachable at %s: %s", _safe_uri(), last_error)
        return status()


def _safe_uri() -> str:
    """URI without credentials, for logs and the health endpoint."""
    uri = MONGO_URI
    if "@" in uri:
        scheme, rest = uri.split("://", 1) if "://" in uri else ("mongodb", uri)
        uri = f"{scheme}://***@{rest.split('@', 1)[1]}"
    return uri


def status() -> dict:
    """Live database status for /health."""
    out = {"online": False, "uri": _safe_uri(), "database": MONGO_DB, "collection": MONGO_COLLECTION,
           "required": MONGO_REQUIRED, "history_scope": HISTORY_SCOPE, "records": None, "error": last_error}
    if not PYMONGO_AVAILABLE:
        out["error"] = "pymongo is not installed"
        return out
    try:
        col = get_collection()
        col.database.client.admin.command("ping")
        out.update(online=True, records=col.estimated_document_count(), error=None)
    except PyMongoError as e:
        out["error"] = str(e).split(",")[0][:200]
    return out


def db_online() -> bool:
    return status()["online"]


def save_prediction(doc: dict) -> tuple[str | None, str | None]:
    """Insert one prediction. Returns (record_id, None) or (None, reason). Never raises."""
    global last_error
    try:
        doc = {**doc, "schema_version": SCHEMA_VERSION, "created_at": datetime.now(timezone.utc)}
        rid = str(get_collection().insert_one(doc).inserted_id)
        last_error = None
        return rid, None
    except PyMongoError as e:
        last_error = str(e).split(",")[0][:200]
        log.error("Could not save prediction: %s", last_error)
        return None, "Database is not reachable, so this result was not saved."


def _scope(client_id: str | None) -> dict:
    return {} if HISTORY_SCOPE == "all" else {"client_id": client_id or "anonymous"}


def _public(d: dict) -> dict:
    """Mongo document -> JSON-safe dict the frontend can use. Works for schema 1 and schema 2."""
    d = dict(d)
    d["id"] = str(d.pop("_id"))
    d.pop("client_id", None)
    d.pop("user_id", None)
    ts = d.get("created_at")
    d["created_at"] = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "astimezone") else str(ts or "")
    if "inputs" not in d:                                   # schema 1 (flat) -> nested view
        keys = ["age", "gender", "country", "academic_level", "most_used_platform", "purpose_of_use", "avg_daily_usage_hours",
                "daily_unlocks", "study_hours", "physical_activity_hours", "sleep_hours_per_night", "stress_level"]
        d["inputs"] = {k: d.get(k) for k in keys}
    if "guidance" not in d and d.get("root_cause"):
        old = d["root_cause"]
        d["primary_root_cause"] = d.get("primary_root_cause") or None
        d["legacy_root_cause"] = old.get("dominant_factor")
    return d


def list_predictions(client_id: str | None, limit: int = 50) -> list[dict]:
    """Newest first. Raises PyMongoError if MongoDB is unreachable."""
    cur = get_collection().find(_scope(client_id)).sort("created_at", DESCENDING).limit(limit)
    return [_public(d) for d in cur]


def get_prediction(record_id: str, client_id: str | None) -> dict | None:
    try:
        oid = ObjectId(record_id)
    except (InvalidId, TypeError):
        return None
    d = get_collection().find_one({"_id": oid, **_scope(client_id)})
    return _public(d) if d else None


def delete_prediction(record_id: str, client_id: str | None) -> int:
    try:
        oid = ObjectId(record_id)
    except (InvalidId, TypeError):
        return 0
    return get_collection().delete_one({"_id": oid, **_scope(client_id)}).deleted_count


def clear_predictions(client_id: str | None) -> int:
    return get_collection().delete_many(_scope(client_id)).deleted_count


def stats() -> dict:
    """Anonymous, aggregated view of ALL saved sessions (computed inside MongoDB with $group)."""
    col = get_collection()
    tot = list(col.aggregate([{"$group": {"_id": None, "n": {"$sum": 1}, "avg": {"$avg": "$predicted_score"}, "last": {"$max": "$created_at"}}}]))
    bands = {r["_id"]: r["n"] for r in col.aggregate([{"$group": {"_id": "$level", "n": {"$sum": 1}}}])}
    pairs = col.aggregate([
        {"$match": {"primary_root_cause": {"$type": "string"}}},
        {"$group": {"_id": {"level": "$level", "cause": "$primary_root_cause"}, "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}])
    by_level: dict = {}
    overall: dict = {}
    for r in pairs:
        lvl, cause, n = r["_id"]["level"], r["_id"]["cause"], r["n"]
        by_level.setdefault(lvl, []).append({"key": cause, "count": n})
        overall[cause] = overall.get(cause, 0) + n
    t = tot[0] if tot else {}
    last = t.get("last")
    return {"total_sessions": t.get("n", 0), "average_score": round(t["avg"], 2) if t.get("avg") is not None else None,
            "last_saved": last.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if hasattr(last, "astimezone") else None,
            "levels": bands, "causes_overall": sorted([{"key": k, "count": v} for k, v in overall.items()], key=lambda x: -x["count"]),
            "causes_by_level": by_level}

# User-scoped prediction helpers. Kept separate from the legacy browser-scoped
# functions so old MongoDB records remain readable without granting cross-user access.
def list_user_predictions(user_id: str, limit: int = 50) -> list[dict]:
    cur = get_collection().find({"user_id": user_id}).sort("created_at", DESCENDING).limit(limit)
    return [_public(d) for d in cur]

def get_user_prediction(record_id: str, user_id: str) -> dict | None:
    try:
        oid = ObjectId(record_id)
    except (InvalidId, TypeError):
        return None
    d = get_collection().find_one({"_id": oid, "user_id": user_id})
    return _public(d) if d else None

def delete_user_prediction(record_id: str, user_id: str) -> int:
    try:
        oid = ObjectId(record_id)
    except (InvalidId, TypeError):
        return 0
    return get_collection().delete_one({"_id": oid, "user_id": user_id}).deleted_count

def clear_user_predictions(user_id: str) -> int:
    return get_collection().delete_many({"user_id": user_id}).deleted_count

def count_user_predictions(user_id: str) -> int:
    """Count only records owned by the authenticated user."""
    return get_collection().count_documents({"user_id": user_id})
