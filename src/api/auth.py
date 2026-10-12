"""
RailMind - Email OTP authentication (v2: audit log + admin login alerts)

Flow:
  POST /auth/request-otp  {email}                          -> emails a 6-digit code
  POST /auth/verify-otp   {email, code}                    -> existing user: token
                                                              new user: new_user=true + signup_token
  POST /auth/register     {signup_token, name, phone, role} -> token
  POST /auth/logout                                         -> records the sign-out
  GET  /auth/me                                             -> current user (+ is_admin)

Needs:  pip install pyjwt
.env:   JWT_SECRET, SMTP_*, ADMIN_EMAIL (see audit.py),
        optional ALLOWED_EMAIL_DOMAIN=gmail.com, optional DEV_PRINT_OTP=1
"""

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from src.api import audit
from src.api.mailer import MailError, mail_configured, send_mail

OTP_TTL_SEC = 300
OTP_RESEND_SEC = 30
OTP_MAX_ATTEMPTS = 5
SESSION_TTL_SEC = 60 * 60 * 12
SIGNUP_TTL_SEC = 60 * 15

DB_PATH = Path(os.getenv("AUTH_DB", "data/auth.db"))
ALLOWED_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "").strip().lower()

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    print("[auth] WARNING: JWT_SECRET not set in .env - logins reset on every restart.")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------- database
def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        " email TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT, role TEXT,"
        " created_at REAL NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS otps ("
        " email TEXT PRIMARY KEY, code_hash TEXT NOT NULL,"
        " expires_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,"
        " sent_at REAL NOT NULL)"
    )
    return con


# ---------------------------------------------------------------- helpers
def _norm_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if ALLOWED_DOMAIN and not email.endswith("@" + ALLOWED_DOMAIN):
        raise HTTPException(400, f"Only @{ALLOWED_DOMAIN} addresses are allowed.")
    return email


def _hash_code(email: str, code: str) -> str:
    return hmac.new(JWT_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _token(payload: dict, ttl: int) -> str:
    now = int(time.time())
    return jwt.encode({**payload, "iat": now, "exp": now + ttl}, JWT_SECRET, algorithm="HS256")


def _decode(token: str, purpose: str) -> dict:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired. Please sign in again.")
    if data.get("purpose") != purpose:
        raise HTTPException(401, "Invalid token.")
    return data


def verify_session(token: str) -> Optional[str]:
    """Non-raising check used by the security middleware. Returns the email or None."""
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return data["sub"] if data.get("purpose") == "session" else None


def is_admin(email: str) -> bool:
    return email.lower() in audit.ADMIN_EMAILS


def _send_otp_mail(to: str, code: str) -> None:
    dev = os.getenv("DEV_PRINT_OTP") == "1"
    if dev:
        print(f"[auth] OTP for {to}: {code}")
    if not mail_configured():
        if dev:
            return
        raise HTTPException(500, "Email is not configured on the server (SMTP_* in .env).")
    try:
        send_mail(
            to,
            "Your RailMind sign-in code",
            f"Your RailMind verification code is {code}.\n\n"
            f"It expires in {OTP_TTL_SEC // 60} minutes. If you didn't request it, ignore this email.",
        )
    except MailError as e:
        print(f"[auth] mail error: {e}")
        raise HTTPException(502, "Could not send the code email. Try again.")


# ---------------------------------------------------------------- schemas
class OtpRequest(BaseModel):
    email: str


class OtpVerify(BaseModel):
    email: str
    code: str = Field(..., min_length=6, max_length=6)


class RegisterRequest(BaseModel):
    signup_token: str
    name: str = Field(..., min_length=2, max_length=80)
    phone: Optional[str] = Field(None, max_length=20)
    role: Optional[str] = Field(None, max_length=40)


# ---------------------------------------------------------------- routes
@router.post("/request-otp")
def request_otp(body: OtpRequest, request: Request, bg: BackgroundTasks):
    email = _norm_email(body.email)
    ip, ua = audit.client_ip(request.scope), audit.user_agent(request.scope)
    now = time.time()
    with _db() as con:
        row = con.execute("SELECT sent_at FROM otps WHERE email=?", (email,)).fetchone()
        if row and now - row["sent_at"] < OTP_RESEND_SEC:
            raise HTTPException(429, "Please wait a few seconds before asking for another code.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        con.execute(
            "INSERT OR REPLACE INTO otps (email, code_hash, expires_at, attempts, sent_at)"
            " VALUES (?,?,?,0,?)",
            (email, _hash_code(email, code), now + OTP_TTL_SEC, now),
        )
    _send_otp_mail(email, code)
    bg.add_task(audit.log_event, ip, ua, email, "Login code requested")
    return {"sent": True, "expires_in": OTP_TTL_SEC}


@router.post("/verify-otp")
def verify_otp(body: OtpVerify, request: Request, bg: BackgroundTasks):
    email = _norm_email(body.email)
    ip, ua = audit.client_ip(request.scope), audit.user_agent(request.scope)
    now = time.time()
    with _db() as con:
        row = con.execute("SELECT * FROM otps WHERE email=?", (email,)).fetchone()
        if not row or row["expires_at"] < now:
            raise HTTPException(400, "Code expired. Request a new one.")
        if row["attempts"] >= OTP_MAX_ATTEMPTS:
            con.execute("UPDATE otps SET code_hash='', expires_at=0 WHERE email=?", (email,))
            con.commit()  # commit before raising, otherwise the 'with' block rolls it back
            raise HTTPException(429, "Too many wrong attempts. Request a new code.")
        if not hmac.compare_digest(row["code_hash"], _hash_code(email, body.code)):
            con.execute("UPDATE otps SET attempts = attempts + 1 WHERE email=?", (email,))
            con.commit()
            bg.add_task(audit.log_event, ip, ua, email, "Wrong code entered")
            raise HTTPException(400, "Wrong code.")
        # single use: invalidate but keep the row so the resend timer still applies
        con.execute("UPDATE otps SET code_hash='', expires_at=0 WHERE email=?", (email,))
        user = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

    if user:
        bg.add_task(audit.log_event, ip, ua, email, "Signed in")
        bg.add_task(audit.notify_admin_login, ip, ua, email, user["name"], False)
        return {
            "new_user": False,
            "token": _token({"purpose": "session", "sub": email}, SESSION_TTL_SEC),
            "user": {"email": email, "name": user["name"], "role": user["role"], "is_admin": is_admin(email)},
        }
    return {
        "new_user": True,
        "signup_token": _token({"purpose": "signup", "sub": email}, SIGNUP_TTL_SEC),
    }


@router.post("/register")
def register(body: RegisterRequest, request: Request, bg: BackgroundTasks):
    email = _decode(body.signup_token, "signup")["sub"]  # proves the email was OTP-verified
    ip, ua = audit.client_ip(request.scope), audit.user_agent(request.scope)
    name = body.name.strip()
    with _db() as con:
        if con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "Account already exists. Sign in instead.")
        con.execute(
            "INSERT INTO users (email, name, phone, role, created_at) VALUES (?,?,?,?,?)",
            (email, name, (body.phone or "").strip(), (body.role or "").strip(), time.time()),
        )
    bg.add_task(audit.log_event, ip, ua, email, "Signed up (new user)", f"name: {name}")
    bg.add_task(audit.notify_admin_login, ip, ua, email, name, True)
    return {
        "token": _token({"purpose": "session", "sub": email}, SESSION_TTL_SEC),
        "user": {"email": email, "name": name, "role": body.role, "is_admin": is_admin(email)},
    }


# ---------------------------------------------------------------- dependency
def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> dict:
    """Dependency for any route that needs the logged-in user."""
    if not creds:
        raise HTTPException(401, "Not signed in.")
    email = _decode(creds.credentials, "session")["sub"]
    with _db() as con:
        user = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user:
        raise HTTPException(401, "Account not found.")
    return {
        "email": user["email"], "name": user["name"], "phone": user["phone"],
        "role": user["role"], "is_admin": is_admin(user["email"]),
    }


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(403, "Admins only.")
    return user


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout")
def logout(request: Request, bg: BackgroundTasks, user: dict = Depends(get_current_user)):
    bg.add_task(audit.log_event, audit.client_ip(request.scope), audit.user_agent(request.scope), user["email"], "Signed out")
    return {"ok": True}