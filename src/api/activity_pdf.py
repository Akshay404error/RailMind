"""
RailMind - activity report PDF (who signed in, from where, and what they did).
Needs: pip install reportlab
"""

import io
import time
from collections import Counter
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MAX_ROWS = 500
NAVY = colors.HexColor("#13315c")
SIGNIN_ACTIONS = {"Signed in", "Signed up (new user)"}


def _t(ts: float) -> str:
    return time.strftime("%d %b %H:%M:%S", time.localtime(ts))


def build_activity_pdf(events: list[dict], period_label: str) -> bytes:
    """events: rows from audit.query_events (any order)."""
    events = sorted(events, key=lambda e: e["ts"])
    base = getSampleStyleSheet()
    s_title = ParagraphStyle("t", parent=base["Title"], fontSize=20, textColor=colors.HexColor("#0b2545"), spaceAfter=2)
    s_sub = ParagraphStyle("s", parent=base["Normal"], fontSize=10, textColor=colors.HexColor("#475569"), spaceAfter=10)
    s_h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=6, textColor=NAVY)
    s_cell = ParagraphStyle("c", parent=base["Normal"], fontSize=8, leading=10)
    s_head = ParagraphStyle("hd", parent=s_cell, textColor=colors.white, fontName="Helvetica-Bold")

    page = landscape(A4)
    width = page[0] - 28 * mm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=16 * mm, title="RailMind Activity Report", author="RailMind",
    )

    def table(header, rows, weights):
        total = sum(weights)
        data = [[Paragraph(h, s_head) for h in header]]
        data += [[Paragraph(escape(str(c or "")), s_cell) for c in r] for r in rows]
        t = Table(data, colWidths=[width * w / total for w in weights], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    users = Counter(e["email"] or "(not signed in)" for e in events)
    signins = [e for e in events if e["action"] in SIGNIN_ACTIONS]
    failed = [e for e in events if e["action"] == "Wrong code entered"]

    story = [
        Paragraph("RailMind Activity Report", s_title),
        Paragraph(f"{escape(period_label)} &nbsp;|&nbsp; generated {time.strftime('%d %b %Y, %H:%M')}", s_sub),
        table(
            ["Events", "Active users", "Sign-ins", "Wrong-code attempts"],
            [[len(events), len(users), len(signins), len(failed)]],
            [1, 1, 1, 1],
        ),
    ]

    story.append(Paragraph("Sign-ins (who, where, from which IP)", s_h2))
    if signins:
        story.append(table(
            ["Time", "User", "Event", "IP address", "Location", "ISP"],
            [[_t(e["ts"]), e["email"], e["action"], e["ip"], e["location"], e["isp"]] for e in signins],
            [1.1, 2.2, 1.4, 1.3, 3.0, 1.8],
        ))
    else:
        story.append(Paragraph("No sign-ins in this period.", s_cell))

    story.append(Paragraph("Activity per user", s_h2))
    per_user = []
    for email, n in users.most_common():
        mine = [e for e in events if (e["email"] or "(not signed in)") == email]
        ips = sorted({e["ip"] for e in mine if e["ip"]})
        per_user.append([email, n, ", ".join(ips)])
    story.append(table(["User", "Events", "IP addresses used"], per_user or [["-", 0, ""]], [3, 1, 4]))

    story.append(Paragraph("Full activity log", s_h2))
    shown = events[-MAX_ROWS:]
    if len(events) > MAX_ROWS:
        story.append(Paragraph(f"Showing the latest {MAX_ROWS} of {len(events)} events.", s_cell))
    if shown:
        story.append(table(
            ["Time", "User", "Activity", "Details", "IP address", "Location"],
            [[_t(e["ts"]), e["email"] or "-", e["action"], e["detail"], e["ip"], e["location"]] for e in shown],
            [1.1, 2.1, 1.8, 3.0, 1.2, 2.4],
        ))
    else:
        story.append(Paragraph("No activity in this period.", s_cell))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Locations are approximate and come from the IP address.", s_cell))

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(14 * mm, 8 * mm, "RailMind - confidential")
        canvas.drawRightString(page[0] - 14 * mm, 8 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()