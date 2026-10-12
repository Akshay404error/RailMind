"""
RailMind - PDF report

GET /report/pdf  -> same content as GET /report/html, delivered as a PDF.
Accepts the same query params (train_number, section_index, delay_min).

It reads the HTML your existing /report/html endpoint produces and re-draws the
headings, paragraphs, lists and tables with reportlab, so it always matches the
HTML report and needs no changes to report.py.

Needs:  pip install reportlab
"""

import io
import re
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.api import audit

router = APIRouter(prefix="/report", tags=["report"])


# ------------------------------------------------------------ HTML -> blocks
def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


class _Extract(HTMLParser):
    SKIP = {"style", "script", "title", "head"}
    BLOCK = {"h1", "h2", "h3", "h4", "p", "li", "div"}

    def __init__(self):
        super().__init__()
        self.blocks = []      # ("h1"|"h2"|"h3"|"p"|"li", text) or ("table", rows)
        self.buf = []
        self.tag = "p"
        self.rows = None
        self.row = None
        self.cell = None
        self.skip = 0

    def _flush(self):
        text = _clean("".join(self.buf))
        if text:
            self.blocks.append((self.tag, text))
        self.buf = []
        self.tag = "p"

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "table":
            self._flush()
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "br":
            (self.cell if self.cell is not None else self.buf).append(" ")
        elif tag in self.BLOCK and self.cell is None:
            self._flush()
            self.tag = "p" if tag == "div" else tag

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.cell is not None:
            self.row.append(_clean("".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.rows is not None:
            if self.rows:
                self.blocks.append(("table", self.rows))
            self.rows = None
        elif tag in self.BLOCK and self.cell is None:
            self._flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.rows is None:
            self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


# ------------------------------------------------------------ blocks -> PDF
def html_to_pdf(html: str, title: str = "RailMind Report") -> bytes:
    """Reusable: also call this from report.py's email endpoint to attach a PDF."""
    parser = _Extract()
    parser.feed(html)
    parser.close()

    base = getSampleStyleSheet()
    s_h1 = ParagraphStyle("h1", parent=base["Title"], fontSize=20, spaceAfter=4, textColor=colors.HexColor("#0b2545"))
    s_h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#13315c"))
    s_h3 = ParagraphStyle("h3", parent=base["Heading3"], fontSize=11, spaceBefore=10, spaceAfter=4)
    s_p = ParagraphStyle("p", parent=base["Normal"], fontSize=10, leading=14, spaceAfter=4)
    s_li = ParagraphStyle("li", parent=s_p, leftIndent=12, bulletIndent=2)
    s_cell = ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11)
    s_head = ParagraphStyle("head", parent=s_cell, textColor=colors.white, fontName="Helvetica-Bold")
    styles = {"h1": s_h1, "h2": s_h2, "h3": s_h3, "h4": s_h3, "p": s_p}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title=title, author="RailMind",
    )
    width = A4[0] - 32 * mm
    story = []

    for kind, content in parser.blocks:
        if kind == "table":
            ncols = max(len(r) for r in content)
            rows = [r + [""] * (ncols - len(r)) for r in content]
            data = [
                [Paragraph(escape(c), s_head if i == 0 else s_cell) for c in r]
                for i, r in enumerate(rows)
            ]
            t = Table(data, colWidths=[width / ncols] * ncols, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#13315c")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story += [t, Spacer(1, 8)]
        elif kind == "li":
            story.append(Paragraph(escape(content), s_li, bulletText="\u2022"))
        else:
            story.append(Paragraph(escape(content), styles.get(kind, s_p)))

    if not story:
        story.append(Paragraph("The report was empty.", s_p))

    stamp = datetime.now().strftime("%d %b %Y, %H:%M")

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(16 * mm, 9 * mm, f"RailMind report - generated {stamp}")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ------------------------------------------------------------ route
@router.get("/pdf")
def report_pdf(request: Request):
    """Fetches this server's own /report/html (forwarding the login token) and converts it."""
    url = str(request.base_url).rstrip("/") + "/report/html"
    if request.url.query:
        url += "?" + request.url.query
    req = urllib.request.Request(url)
    if request.headers.get("authorization"):
        req.add_header("Authorization", request.headers["authorization"])
    req.add_header("X-RailMind-Internal", audit.INTERNAL_TOKEN)  # keeps the activity log clean
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, f"Could not build the report ({e.reason}).")
    except Exception as e:
        raise HTTPException(502, f"Could not build the report: {e}")

    pdf = html_to_pdf(html)
    name = f"railmind_report_{datetime.now():%Y%m%d_%H%M}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )