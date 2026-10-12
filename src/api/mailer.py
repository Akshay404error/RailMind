"""
RailMind - shared mail sender (Gmail SMTP). Used by login codes, login alerts
and activity PDFs.

.env: SMTP_HOST, SMTP_PORT (587 or 465), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
"""

import os
import smtplib
from email.message import EmailMessage
from typing import Iterable, Optional, Union

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class MailError(Exception):
    pass


def mail_configured() -> bool:
    return all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send_mail(
    to: Union[Iterable[str], str],
    subject: str,
    body: str,
    attachments: Optional[list[tuple[str, bytes, str]]] = None,
) -> None:
    """attachments: list of (filename, bytes, "maintype/subtype"), e.g. ("a.pdf", data, "application/pdf")."""
    if not mail_configured():
        raise MailError("Email is not configured (SMTP_* in .env).")
    recipients = [to] if isinstance(to, str) else list(to)

    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or os.environ["SMTP_USER"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    for name, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)

    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    password = os.environ["SMTP_PASSWORD"].replace(" ", "")
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        with server:
            server.login(os.environ["SMTP_USER"], password)
            server.send_message(msg)
    except Exception as e:
        raise MailError(str(e)) from e