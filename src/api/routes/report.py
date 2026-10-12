"""
RailMind - API Routes: Report + Mail

  GET  /report/html   -> live HTML report (always built from current data files)
  POST /report/email  -> builds the same report and emails it over SMTP

Optional what-if: pass train_number + section_index + delay_min and the report
includes the conflicts that disruption would cause.

Priority (Premium / Express / Passenger) is read from
data/synthetic/train_priorities.json  ({"12004": 1, ...} or names).
Trains missing from that file are shown as "Passenger".

SMTP settings come from environment variables (.env):
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
"""

import html
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.api.models.schemas import ReportEmailRequest, ReportEmailResponse
from src.api.priorities import PRIORITY_NAMES, load_priorities
from src.simulator.schedule_simulator import ScheduleSimulator

router = APIRouter(prefix="/report", tags=["report"])

PRIORITY_COLORS = {"Premium": "#c0392b", "Express": "#e67e22", "Passenger": "#2980b9"}


def _pname(prio: dict, train: str) -> str:
    return PRIORITY_NAMES.get(prio.get(train), "Passenger")


def _fmt(m: float) -> str:
    m = int(round(m))
    return f"D{m // 1440} {m % 1440 // 60:02d}:{m % 60:02d}"


def build_report_html(train_number: Optional[str] = None,
                      section_index: Optional[int] = None,
                      delay_min: Optional[float] = None) -> str:
    sim = ScheduleSimulator()
    prio = load_priorities()
    baseline = sim.check_conflicts()

    # per-train and per-section delay stats from the optimizer output
    train_delay, sec_delay, sec_count = {}, {}, {}
    for t, stops in sim.train_schedules.items():
        train_delay[t] = sum(s["delay_min"] for s in stops)
        for s in stops:
            i = s["section_index"]
            sec_delay[i] = sec_delay.get(i, 0) + s["delay_min"]
            sec_count[i] = sec_count.get(i, 0) + 1

    total_delay = sum(train_delay.values())
    delayed = sum(1 for d in train_delay.values() if d > 0)
    by_prio = {}
    for t, d in train_delay.items():
        p = _pname(prio, t)
        by_prio[p] = by_prio.get(p, 0) + d

    def badge(t):
        p = _pname(prio, t)
        c = PRIORITY_COLORS.get(p, "#7f8c8d")
        return f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:10px;font-size:12px">{html.escape(p)}</span>'

    top = sorted(train_delay.items(), key=lambda x: -x[1])[:10]
    top_rows = "".join(
        f"<tr><td>{html.escape(t)}</td><td>{badge(t)}</td><td>{d:.0f}</td></tr>" for t, d in top
    )
    sec_rows = "".join(
        f"<tr><td>{html.escape(sim.sections[i]['from_station'])} &rarr; {html.escape(sim.sections[i]['to_station'])}</td>"
        f"<td>{sec_count[i]}</td><td>{sec_delay[i]:.0f}</td></tr>"
        for i in sorted(sec_delay)
    )
    prio_rows = "".join(
        f"<tr><td>{badge_name}</td><td>{v:.0f}</td></tr>"
        for badge_name, v in sorted(by_prio.items(), key=lambda x: -x[1])
    )

    disruption_html = ""
    if train_number is not None and section_index is not None and delay_min:
        try:
            new = sim.inject_delay(train_number, section_index, delay_min)
        except ValueError as e:
            disruption_html = f"<h2>What-if disruption</h2><p style='color:#c0392b'>{html.escape(str(e))}</p>"
        else:
            rows = "".join(
                f"<tr><td>{html.escape(c.section_name)}</td><td>{html.escape(c.train_a)}</td>"
                f"<td>{html.escape(c.train_b)}</td></tr>" for c in new
            )
            verdict = ("Schedule absorbs this delay safely." if not new
                       else f"{len(new)} new conflict(s) created.")
            disruption_html = (
                f"<h2>What-if disruption</h2>"
                f"<p>Train <b>{html.escape(train_number)}</b> delayed <b>{delay_min:g} min</b> "
                f"entering section {section_index}. {verdict}</p>"
                + (f"<table><tr><th>Section</th><th>Train A</th><th>Train B</th></tr>{rows}</table>" if new else "")
            )

    status = ("<span style='color:#27ae60'>CONFLICT-FREE</span>" if not baseline
              else f"<span style='color:#c0392b'>{len(baseline)} CONFLICTS</span>")

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>RailMind Report</title>
<style>
body{{font-family:Arial,sans-serif;max-width:820px;margin:24px auto;color:#222}}
table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left;font-size:14px}}
th{{background:#f2f4f6}} h1{{margin-bottom:0}} .sub{{color:#777;margin-top:2px}}
.kpi{{display:inline-block;margin:0 24px 12px 0}} .kpi b{{font-size:22px;display:block}}
</style></head><body>
<h1>RailMind Corridor Report</h1>
<p class="sub">Generated {datetime.now().strftime('%d %b %Y, %H:%M')}</p>
<div><div class="kpi"><b>{len(sim.entries)}</b>trains</div>
<div class="kpi"><b>{len(sim.sections)}</b>block sections</div>
<div class="kpi"><b>{total_delay:.0f}</b>total delay (min)</div>
<div class="kpi"><b>{delayed}</b>trains delayed</div>
<div class="kpi"><b>{status}</b>baseline check</div></div>
{disruption_html}
<h2>Delay by priority</h2><table><tr><th>Priority</th><th>Delay (min)</th></tr>{prio_rows}</table>
<h2>Top 10 delayed trains</h2><table><tr><th>Train</th><th>Priority</th><th>Delay (min)</th></tr>{top_rows}</table>
<h2>Section summary</h2><table><tr><th>Section</th><th>Train entries</th><th>Delay (min)</th></tr>{sec_rows}</table>
<p class="sub">Times shown as D&lt;day&gt; HH:MM from schedule origin. Source: optimized_schedule.json, independently re-verified by the simulator.</p>
</body></html>"""


@router.get("/html", response_class=HTMLResponse)
def report_html(train_number: Optional[str] = Query(None),
                section_index: Optional[int] = Query(None),
                delay_min: Optional[float] = Query(None, gt=0)):
    return HTMLResponse(build_report_html(train_number, section_index, delay_min))


@router.post("/email", response_model=ReportEmailResponse)
def report_email(req: ReportEmailRequest):
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("SMTP_FROM", user)
    if not (host and user and password):
        raise HTTPException(status_code=500,
                            detail="SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env")

    body = build_report_html(req.train_number, req.section_index, req.delay_min)
    msg = EmailMessage()
    msg["Subject"] = req.subject or "RailMind Corridor Report"
    msg["From"] = sender
    msg["To"] = ", ".join(req.to)
    msg.set_content("Open this email in an HTML-capable client to view the RailMind report.")
    msg.add_alternative(body, subtype="html")
    msg.add_attachment(body.encode("utf-8"), maintype="text", subtype="html",
                       filename="railmind_report.html")
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mail send failed: {e}")
    return ReportEmailResponse(sent=True, recipients=req.to)