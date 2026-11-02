import sys, warnings
from pathlib import Path
from datetime import datetime, timezone

import pytest
import mongomock

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api.database as db
import api.auth as auth
import api.main as m

BASE = dict(
    age=21, gender="Male", country="India", academic_level="Undergraduate", employment_status="None (student only)",
    most_used_platform="Instagram", purpose_of_use="Entertainment",
    avg_daily_usage_hours=5, daily_unlocks=170, study_hours=3,
    physical_activity_hours=1.5, sleep_hours_per_night=7,
    stress_level="Medium",
)


@pytest.fixture(autouse=True)
def fake_mongo(monkeypatch):
    monkeypatch.setattr(db, "_client", mongomock.MongoClient(tz_aware=True))
    monkeypatch.setattr(db, "MONGO_REQUIRED", True)
    db.init_auth_db()


def make_user(name, email, password="Password123"):
    now = datetime.now(timezone.utc)
    users = db.get_users()
    doc = {
        "name": name, "email": email, "password_hash": auth.hash_password(password),
        "verified": True, "created_at": now, "updated_at": now,
    }
    return users.insert_one(doc).inserted_id


def login_token(user_id, email):
    return auth.create_session(str(user_id), email)


@pytest.fixture
def api():
    return TestClient(m.app)


def test_options_uses_standardized_academic_and_employment_categories(api):
    r = api.get("/options")
    assert r.status_code == 200
    body = r.json()
    assert body["dataset_rows"] == 25000
    assert body["academic_level_count"] == 9
    assert "India" in body["countries"]
    assert "Part-time job" in body["employment_statuses"]
    assert "Doctoral (PhD)" in body["academic_levels"]
    assert "Postgraduate (Master's)" in body["academic_levels"]
    assert "High School / Upper Secondary" in body["academic_levels"]
    assert "Communication" in body["purposes"]
    assert "Other" in body["genders"]


def test_model_was_trained_on_25000_rows(api):
    info = api.get("/model-info").json()
    assert info["training_rows"] == 25000
    assert info["dataset_rows"] == 25000
    assert info["academic_level_count"] == 9


def test_history_requires_authentication(api):
    assert api.get("/history").status_code == 401
    assert api.get("/auth/me").status_code == 401


def test_prediction_history_is_private_to_user(api):
    a = make_user("A", "a@example.com")
    b = make_user("B", "b@example.com")
    ta = login_token(a, "a@example.com")
    tb = login_token(b, "b@example.com")
    ha = {"Authorization": f"Bearer {ta}"}
    hb = {"Authorization": f"Bearer {tb}"}

    r = api.post("/predict", json=BASE, headers=ha)
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True and body["record_id"]

    mine = api.get("/history", headers=ha)
    other = api.get("/history", headers=hb)
    assert mine.status_code == 200 and mine.json()["count"] == 1
    assert other.status_code == 200 and other.json()["count"] == 0
    assert api.get(f"/history/{body['record_id']}", headers=hb).status_code == 404


def test_logout_revokes_session_and_clears_access(api):
    uid = make_user("Logout", "logout@example.com")
    token = login_token(uid, "logout@example.com")
    h = {"Authorization": f"Bearer {token}"}
    assert api.get("/auth/me", headers=h).status_code == 200
    assert api.post("/auth/logout", headers=h).status_code == 200
    assert api.get("/auth/me", headers=h).status_code == 401
    assert db.get_sessions().count_documents({"user_id": str(uid)}) == 0


def test_expired_or_invalid_session_is_rejected(api):
    assert api.get("/history", headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401


def test_case_insensitive_categories_are_accepted(api):
    uid = make_user("Case", "case@example.com")
    token = login_token(uid, "case@example.com")
    h = {"Authorization": f"Bearer {token}"}
    payload = {**BASE, "gender": "male", "academic_level": "undergraduate", "employment_status": "part-time", "stress_level": "very high", "most_used_platform": "tiktok"}
    assert api.post("/predict", json=payload, headers=h).status_code == 200


def test_invalid_category_is_rejected(api):
    uid = make_user("Invalid", "invalid@example.com")
    token = login_token(uid, "invalid@example.com")
    h = {"Authorization": f"Bearer {token}"}
    assert api.post("/predict", json={**BASE, "academic_level": "Not In Dataset"}, headers=h).status_code == 422
