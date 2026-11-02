"""Authentication helpers for MindPulse.

Uses MongoDB for users/OTP records, PBKDF2 password hashing from the Python
standard library, signed short-lived application tokens, and SMTP for email OTPs.
No third-party auth package is required.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

from api import database as db


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


AUTH_SECRET = _env("AUTH_SECRET", "")
TOKEN_TTL_HOURS = int(_env("AUTH_TOKEN_TTL_HOURS", "24") or "24")
OTP_TTL_MINUTES = int(_env("AUTH_OTP_TTL_MINUTES", "10") or "10")
PUBLIC_APP_URL = _env("PUBLIC_APP_URL", "http://127.0.0.1:8000/app").rstrip("/")

SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", "587") or "587")
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD").replace(" ", "")   # Google shows App Passwords in 4 groups with spaces
SMTP_FROM = _env("SMTP_FROM", SMTP_USER)

PBKDF2_ROUNDS = 210_000


def configured() -> bool:
    return bool(AUTH_SECRET)


def _secret() -> bytes:
    if not AUTH_SECRET:
        raise RuntimeError("AUTH_SECRET is not configured. Set it in .env before starting the API.")
    return AUTH_SECRET.encode("utf-8")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", email))



def email_domain_deliverable(email: str) -> bool:
    """Check that the email domain publishes mail routing (MX) or has a fallback address record.

    This cannot prove that a particular mailbox exists; OTP confirmation does that.
    dnspython is declared in requirements.txt so DNS errors fail closed before an OTP is sent.
    """
    if not valid_email(email):
        return False
    domain = email.rsplit("@", 1)[1].rstrip(".").lower()
    try:
        import dns.resolver
        try:
            answers = dns.resolver.resolve(domain, "MX", lifetime=4)
            return any(str(answer.exchange).strip(".") for answer in answers)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            # RFC fallback: if no MX exists, a domain A/AAAA record may receive mail.
            try:
                dns.resolver.resolve(domain, "A", lifetime=3)
                return True
            except Exception:
                try:
                    dns.resolver.resolve(domain, "AAAA", lifetime=3)
                    return True
                except Exception:
                    return False
    except Exception:
        return False

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, digest_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def make_token(user_id: str, email: str, purpose: str = "session", ttl_hours: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "email": email, "purpose": purpose, "iat": int(now.timestamp()),
               "exp": int((now + timedelta(hours=ttl_hours or TOKEN_TTL_HOURS)).timestamp()),
               "jti": secrets.token_hex(8)}
    raw = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), raw.encode(), hashlib.sha256).digest())
    return raw + "." + sig


def read_token(token: str, purpose: str = "session") -> dict[str, Any] | None:
    try:
        raw, sig = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), raw.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(raw).decode())
        if data.get("purpose") != purpose or int(data.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return data
    except Exception:
        return None


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hmac.new(_secret(), code.encode(), hashlib.sha256).hexdigest()


def save_otp(email: str, purpose: str, code: str, extra: dict | None = None) -> None:
    now = datetime.now(timezone.utc)
    col = db.get_auth_otps()
    col.delete_many({"email": email, "purpose": purpose})
    doc = {"email": email, "purpose": purpose, "code_hash": hash_otp(code),
           "expires_at": now + timedelta(minutes=OTP_TTL_MINUTES), "attempts": 0, "created_at": now}
    if extra:
        doc.update(extra)
    col.insert_one(doc)


def consume_otp(email: str, purpose: str, code: str) -> dict | None:
    col = db.get_auth_otps()
    d = col.find_one({"email": email, "purpose": purpose})
    if not d:
        return None
    now = datetime.now(timezone.utc)
    exp = d.get("expires_at")
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)   # tolerate naive datetimes from the driver
    if exp and exp < now:
        col.delete_one({"_id": d["_id"]})
        return None
    if int(d.get("attempts", 0)) >= 5:
        col.delete_one({"_id": d["_id"]})
        return None
    if not hmac.compare_digest(d.get("code_hash", ""), hash_otp(code.strip())):
        col.update_one({"_id": d["_id"]}, {"$inc": {"attempts": 1}})
        return None
    col.delete_one({"_id": d["_id"]})
    return d


class EmailError(RuntimeError):
    """An email problem whose message is safe and useful to show to the user."""


def email_config_problem() -> str | None:
    """None when the SMTP settings look usable, otherwise a plain-language explanation."""
    if not SMTP_USER or not SMTP_PASSWORD or not SMTP_FROM:
        return "Email is not configured. Set SMTP_USER, SMTP_PASSWORD and SMTP_FROM in .env, then restart the API."
    if "your-gmail" in SMTP_USER.lower() or SMTP_PASSWORD.lower().startswith("your-"):
        return ("The email settings in .env are still the example placeholders. Put your real Gmail address and "
                "Gmail App Password in .env, then restart the API.")
    return None


def send_email(to_email: str, subject: str, text: str, html: str) -> None:
    problem = email_config_problem()
    if problem:
        raise EmailError(problem)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise EmailError("Gmail rejected the login. Use a 16-character Gmail App Password (2-Step Verification must be ON) "
                         "and the same Gmail address in SMTP_USER.") from e
    except (smtplib.SMTPException, OSError) as e:
        raise EmailError(f"Could not send the email through {SMTP_HOST}:{SMTP_PORT} ({type(e).__name__}). "
                         "Check your internet connection, firewall and SMTP settings.") from e


def send_otp_email(to_email: str, code: str, purpose: str, link_token: str | None = None) -> None:
    if purpose == "signup":
        title = "Verify your MindPulse account"
        action = "verify your email address"
        link_label = "Verify email"
        link = f"{PUBLIC_APP_URL}?verify={link_token}" if link_token else None
    else:
        title = "Reset your MindPulse password"
        action = "reset your password"
        link_label = "Open password reset"
        link = f"{PUBLIC_APP_URL}?reset={link_token}" if link_token else None
    link_html = f'<p><a href="{link}">{link_label}</a></p>' if link else ""
    text = f"MindPulse\n\nYour verification code is {code}. It expires in {OTP_TTL_MINUTES} minutes.\n\nUse this code to {action}."
    if link:
        text += f"\n\nYou can also open this link: {link}"
    html = f"""<div style='font-family:Arial,sans-serif;max-width:560px;margin:auto;padding:28px;color:#102033'>
      <h2 style='margin-bottom:8px'>MindPulse</h2><p>{title}</p>
      <p>Your one-time code is:</p><div style='font-size:30px;font-weight:700;letter-spacing:8px;padding:16px 0'>{code}</div>
      <p>This code expires in {OTP_TTL_MINUTES} minutes.</p>{link_html}
      <p style='color:#6b7a8c;font-size:13px'>If you did not request this, you can ignore this email.</p></div>"""
    send_email(to_email, title, text, html)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: str, email: str) -> str:
    token = make_token(user_id, email, "session")
    payload = read_token(token, "session")
    expires_at = datetime.fromtimestamp(int(payload["exp"]), timezone.utc)
    db.get_sessions().insert_one({"user_id": user_id, "email": email, "token_hash": token_hash(token), "created_at": datetime.now(timezone.utc), "expires_at": expires_at})
    return token


def session_active(token: str) -> bool:
    if not token:
        return False
    try:
        payload = read_token(token, "session")
        if not payload:
            return False
        d = db.get_sessions().find_one({"token_hash": token_hash(token)})
        return bool(d and d.get("user_id") == payload.get("sub") and d.get("expires_at") and d["expires_at"] > datetime.now(timezone.utc))
    except Exception:
        return False


def revoke_session(token: str) -> None:
    if token:
        db.get_sessions().delete_one({"token_hash": token_hash(token)})