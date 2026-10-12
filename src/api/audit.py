"""
RailMind - audit trail

Records who signed in / what they did, with IP address and approximate location,
and emails the admin when someone signs in.

.env:
  ADMIN_EMAIL=akshay2005air@gmail.com      # receives login alerts + activity PDFs
  ADMIN_EMAILS=a@x.com,b@y.com             # optional extra people allowed to open /admin
  TRUSTED_PROXY=1                          # only if behind nginx/Cloudflare (reads X-Forwarded-For)

Location comes from the free https://ipwho.is service (city level, approximate -
it shows the ISP's area, not a street address). On localhost the IP is 127.0.0.1,
so the server's own public IP is looked up instead and marked as a dev machine.
"""

import ipaddress
import json
import os
import secrets
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Optional

from src.api.mailer import MailError, mail_configured, send_mail

DB_PATH = Path(os.getenv("AUTH_DB", "data/auth.db"))
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "akshay2005air@gmail.com").strip().lower()
ADMIN_EMAILS = {ADMIN_EMAIL} | {
    e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
}

# Secret used so the PDF route's internal call to /report/html is not logged twice.
INTERNAL_TOKEN = secrets.token_hex(16)


# ---------------------------------------------------------------- db
def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, email TEXT,"
        " action TEXT NOT NULL, detail TEXT, ip TEXT, location TEXT, isp TEXT,"
        " user_agent TEXT, status INTEGER)"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    return con


def get_meta(key: str) -> Optional[str]:
    with _db() as con:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))


# ---------------------------------------------------------------- client info
def client_ip(scope) -> str:
    """Works with an ASGI scope (pass request.scope inside a route)."""
    if os.getenv("TRUSTED_PROXY") == "1":
        for k, v in scope.get("headers", []):
            if k == b"x-forwarded-for":
                return v.decode().split(",")[0].strip()
    c = scope.get("client")
    return c[0] if c else "unknown"


def user_agent(scope) -> str:
    for k, v in scope.get("headers", []):
        if k == b"user-agent":
            return v.decode(errors="replace")[:200]
    return ""


_geo_cache: dict[str, tuple[float, dict]] = {}


def lookup(ip: str) -> dict:
    """Returns {'location': str, 'isp': str, 'public_ip': str}. Never raises."""
    now = time.time()
    hit = _geo_cache.get(ip)
    if hit and now - hit[0] < 3600:
        return hit[1]

    try:
        a = ipaddress.ip_address(ip)
        local = a.is_private or a.is_loopback or a.is_link_local
    except ValueError:
        local = True

    result = {"location": "Unknown", "isp": "", "public_ip": ip}
    try:
        url = "https://ipwho.is/" + ("" if local else ip)  # empty = this server's own public IP
        req = urllib.request.Request(url, headers={"User-Agent": "RailMind"})
        with urllib.request.urlopen(req, timeout=4) as r:
            d = json.load(r)
        if d.get("success"):
            place = ", ".join(x for x in (d.get("city"), d.get("region"), d.get("country")) if x)
            result = {
                "location": place or "Unknown",
                "isp": (d.get("connection") or {}).get("isp", ""),
                "public_ip": d.get("ip", ip),
            }
            if local:
                result["location"] += f" (dev machine, public IP {result['public_ip']})"
    except Exception:
        if local:
            result["location"] = "Local network"
    _geo_cache[ip] = (now, result)
    return result


# ---------------------------------------------------------------- logging
def log_event(
    ip: str, ua: str, email: Optional[str], action: str,
    detail: str = "", status: Optional[int] = None,
) -> None:
    """Safe to call from background threads. Never raises."""
    try:
        geo = lookup(ip)
        with _db() as con:
            con.execute(
                "INSERT INTO events (ts, email, action, detail, ip, location, isp, user_agent, status)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (time.time(), email, action, detail, ip, geo["location"], geo["isp"], ua, status),
            )
    except Exception as e:
        print(f"[audit] could not log event: {e}")


def query_events(since_ts: float, limit: Optional[int] = None, newest_first: bool = True) -> list[dict]:
    sql = "SELECT * FROM events WHERE ts >= ? ORDER BY ts " + ("DESC" if newest_first else "ASC")
    args: list = [since_ts]
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    with _db() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


# ---------------------------------------------------------------- admin login alert
def notify_admin_login(ip: str, ua: str, email: str, name: str, is_new: bool) -> None:
    """Emails the admin about a successful sign-in. Never raises."""
    if not mail_configured():
        return
    try:
        geo = lookup(ip)
        when = time.strftime("%d %b %Y, %H:%M:%S")
        kind = "NEW USER signed up" if is_new else "User signed in"
        body = (
            f"{kind} on RailMind\n\n"
            f"User:      {name} <{email}>\n"
            f"Time:      {when}\n"
            f"IP:        {ip}\n"
            f"Location:  {geo['location']}\n"
            f"ISP:       {geo['isp'] or 'unknown'}\n"
            f"Device:    {ua or 'unknown'}\n\n"
            "Location is approximate (based on IP address)."
        )
        send_mail(ADMIN_EMAIL, f"[RailMind] {kind}: {email}", body)
    except MailError as e:
        print(f"[audit] login alert not sent: {e}")
    except Exception as e:
        print(f"[audit] login alert error: {e}")