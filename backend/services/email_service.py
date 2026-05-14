"""SMTP email sender. Env-driven; safe no-op when unconfigured."""
from __future__ import annotations

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_S = 10


def _config() -> dict | None:
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    user = os.getenv("SMTP_USER")
    pw = os.getenv("SMTP_PASS")
    sender = os.getenv("SMTP_FROM") or user
    if not (host and port and sender):
        return None
    try:
        port_i = int(port)
    except ValueError:
        return None
    return {
        "host": host,
        "port": port_i,
        "user": user,
        "pass": pw,
        "from": sender,
        "tls": (os.getenv("SMTP_TLS", "true").lower() in ("1", "true", "yes")),
    }


def is_configured() -> bool:
    return _config() is not None


def status() -> dict:
    cfg = _config()
    if not cfg:
        return {"configured": False}
    return {
        "configured": True,
        "host": cfg["host"],
        "port": cfg["port"],
        "from": cfg["from"],
        "tls": cfg["tls"],
        "user_set": bool(cfg["user"]),
    }


def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    cfg = _config()
    if not cfg:
        logger.warning("[email] SMTP not configured; skipping send to %s", to)
        return False
    if not to:
        logger.warning("[email] empty recipient; skipping")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = to
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if cfg["port"] == 465:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=SMTP_TIMEOUT_S) as s:
                if cfg["user"] and cfg["pass"]:
                    s.login(cfg["user"], cfg["pass"])
                s.sendmail(cfg["from"], [to], msg.as_string())
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=SMTP_TIMEOUT_S) as s:
                s.ehlo()
                if cfg["tls"]:
                    s.starttls()
                    s.ehlo()
                if cfg["user"] and cfg["pass"]:
                    s.login(cfg["user"], cfg["pass"])
                s.sendmail(cfg["from"], [to], msg.as_string())
        logger.info("[email] sent to=%s subject=%r", to, subject)
        return True
    except Exception as e:
        logger.warning("[email] send failed to=%s err=%s", to, e)
        return False
