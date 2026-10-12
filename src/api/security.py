"""
RailMind - security + activity layer. One call wires everything:

    from src.api.security import install
    install(app)          # put this AFTER your include_router(...) lines

It adds:
  * login required for every route except /auth/*, /docs, /redoc, /openapi.json, /health
  * activity log (user, action, IP, location) for simulations, reports and admin actions
  * CORS for the dashboard (REMOVE any CORS block you already have in main.py)
  * /auth/*, /report/pdf and /admin/* routes
  * a daily activity-PDF email to the admin

.env:
  ADMIN_EMAIL=akshay2005air@gmail.com
  ACTIVITY_REPORT_HOUR=20        # local server hour for the daily PDF (0-23). 
  CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
"""

import asyncio
import json
import os
import threading
import time
from datetime import datetime
from typing import Callable
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from src.api import audit
from src.api.activity_pdf import build_activity_pdf
from src.api.auth import require_admin, router as auth_router, verify_session
from src.api.mailer import MailError, mail_configured, send_mail
from src.api.routes.report_pdf import router as report_pdf_router

PUBLIC_PREFIXES = ("/auth", "/docs", "/redoc", "/openapi.json", "/health")


# ------------------------------------------------------------ what gets logged
def _json(body: bytes) -> dict:
    try:
        d = json.loads(body.decode() or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _report_detail(q: dict, body: bytes) -> str:
    parts = [f"{k}={q[k]}" for k in ("train_number", "section_index", "delay_min") if q.get(k)]
    return ", ".join(parts) or "live data, no disruption"


def _disruption_detail(q: dict, body: bytes) -> str:
    b = _json(body)
    return f"train {b.get('train_number')}, section {b.get('section_index')}, +{b.get('delay_min')} min"


def _email_detail(q: dict, body: bytes) -> str:
    b = _json(body)
    to = b.get("to")
    return "to: " + (", ".join(to) if isinstance(to, list) else str(to))


def _hours_detail(q: dict, body: bytes) -> str:
    return f"last {q.get('hours', '24')} hours"


# (method, path) -> (activity name, function building the detail text)
ACTIONS: dict[tuple[str, str], tuple[str, Callable[[dict, bytes], str]]] = {
    ("POST", "/simulate/disruption"): ("Ran disruption simulation", _disruption_detail),
    ("GET", "/simulate/baseline"): ("Checked baseline conflicts", lambda q, b: ""),
    ("GET", "/report/html"): ("Viewed HTML report", _report_detail),
    ("GET", "/report/pdf"): ("Downloaded PDF report", _report_detail),
    ("POST", "/report/email"): ("Emailed report", _email_detail),
    ("GET", "/admin/activity.pdf"): ("Downloaded activity PDF", _hours_detail),
    ("POST", "/admin/activity/email"): ("Emailed activity PDF to admin", _hours_detail),
}


# ------------------------------------------------------------ middleware
class SecurityMiddleware:
    """Pure ASGI middleware: enforces login and records activity without breaking request bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method, path = scope["method"], scope["path"]
        if method == "OPTIONS" or path.startswith(PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)

        headers = {k.decode().lower(): v.decode(errors="replace") for k, v in scope["headers"]}
        auth = headers.get("authorization", "")
        email = verify_session(auth[7:]) if auth.lower().startswith("bearer ") else None
        if not email:
            resp = JSONResponse({"detail": "Not signed in."}, status_code=401)
            return await resp(scope, receive, send)

        action = ACTIONS.get((method, path))
        internal = headers.get("x-railmind-internal") == audit.INTERNAL_TOKEN
        if not action or internal:
            return await self.app(scope, receive, send)

        body = bytearray()
        status = {"code": None}

        async def recv():
            msg = await receive()
            if msg["type"] == "http.request" and len(body) < 8192:
                body.extend(msg.get("body", b""))
            return msg

        async def snd(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, recv, snd)
        finally:
            q = dict(parse_qsl(scope.get("query_string", b"").decode()))
            name, make_detail = action
            detail = make_detail(q, bytes(body))
            if status["code"] and status["code"] >= 400:
                detail = (detail + f" [failed: HTTP {status['code']}]").strip()
            loop = asyncio.get_running_loop()
            loop.run_in_executor(
                None, audit.log_event,
                audit.client_ip(scope), audit.user_agent(scope), email, name, detail, status["code"],
            )


# ------------------------------------------------------------ activity PDF + admin routes
def send_activity_report(hours: int = 24) -> int:
    """Builds the activity PDF and emails it to the admin. Returns the number of events included."""
    since = time.time() - hours * 3600
    events = audit.query_events(since)
    label = f"Last {hours} hours (until {time.strftime('%d %b %Y, %H:%M')})"
    pdf = build_activity_pdf(events, label)
    send_mail(
        audit.ADMIN_EMAIL,
        f"[RailMind] Activity report - {time.strftime('%d %b %Y')}",
        f"Attached: RailMind activity for the {label.lower()}.\n{len(events)} events recorded.",
        attachments=[(f"railmind_activity_{datetime.now():%Y%m%d_%H%M}.pdf", pdf, "application/pdf")],
    )
    return len(events)


admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@admin_router.get("/activity")
def activity(hours: int = 24, limit: int = 100):
    hours = max(1, min(hours, 24 * 90))
    return {"events": audit.query_events(time.time() - hours * 3600, limit=max(1, min(limit, 500)))}


@admin_router.get("/activity.pdf")
def activity_pdf(hours: int = 24):
    hours = max(1, min(hours, 24 * 90))
    events = audit.query_events(time.time() - hours * 3600)
    pdf = build_activity_pdf(events, f"Last {hours} hours")
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="railmind_activity_{datetime.now():%Y%m%d_%H%M}.pdf"'},
    )


@admin_router.post("/activity/email")
def activity_email(hours: int = 24):
    hours = max(1, min(hours, 24 * 90))
    if not mail_configured():
        raise HTTPException(500, "Email is not configured (SMTP_* in .env).")
    try:
        n = send_activity_report(hours)
    except MailError as e:
        raise HTTPException(502, f"Mail send failed: {e}")
    return {"sent": True, "to": audit.ADMIN_EMAIL, "events": n}


# ------------------------------------------------------------ daily digest
_next_try = 0.0


def _maybe_send_daily() -> None:
    global _next_try
    now = datetime.now()
    if now.hour < int(os.getenv("ACTIVITY_REPORT_HOUR", "20")):
        return
    today = now.strftime("%Y-%m-%d")
    if audit.get_meta("last_digest") == today or time.time() < _next_try:
        return
    if not audit.query_events(time.time() - 24 * 3600, limit=1):
        audit.set_meta("last_digest", today)  # nothing happened, nothing to send
        return
    try:
        n = send_activity_report(24)
        audit.set_meta("last_digest", today)
        print(f"[activity] daily PDF sent to {audit.ADMIN_EMAIL} ({n} events)")
    except Exception as e:
        _next_try = time.time() + 1800  # retry in 30 min
        print(f"[activity] daily PDF failed: {e}")


_scheduler_started = False


def start_scheduler() -> None:
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def loop():
        while True:
            try:
                _maybe_send_daily()
            except Exception as e:
                print(f"[activity] scheduler error: {e}")
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="activity-digest").start()


# ------------------------------------------------------------ one-call setup
def install(app) -> None:
    from starlette.middleware.cors import CORSMiddleware

    origins = [o.strip() for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

    app.add_middleware(SecurityMiddleware)
    # added last = outermost, so even the 401 replies carry CORS headers
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    app.include_router(auth_router)
    app.include_router(report_pdf_router)
    app.include_router(admin_router)
    start_scheduler()  # plain background thread: no dependence on FastAPI startup-hook APIs