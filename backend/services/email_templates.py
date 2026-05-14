"""Inline-HTML email templates. Each returns {subject, html, text}."""
from __future__ import annotations

import html as _h

_WRAP_OPEN = (
    '<div style="font-family:Arial,Helvetica,sans-serif;color:#222;'
    'max-width:560px;margin:0 auto;padding:24px;background:#ffffff;'
    'border:1px solid #e5e5e5;">'
)
_WRAP_CLOSE = (
    '<hr style="border:none;border-top:1px solid #eee;margin:24px 0;">'
    '<p style="font-size:12px;color:#888;margin:0;">Sent by PULSE HR</p>'
    '</div>'
)


def _wrap(body_html: str) -> str:
    return _WRAP_OPEN + body_html + _WRAP_CLOSE


def interview_invite(candidate_name: str, position_title: str, link: str) -> dict:
    cn = _h.escape(candidate_name or "Candidate")
    pt = _h.escape(position_title or "the role")
    lk = _h.escape(link or "")
    subject = f"Interview Invitation — {position_title}"
    html = _wrap(
        f'<h2 style="margin:0 0 12px;color:#007518;">Interview Invitation</h2>'
        f'<p>Hi {cn},</p>'
        f'<p>We would like to invite you to interview for the <strong>{pt}</strong> position.</p>'
        f'<p style="margin:20px 0;">'
        f'<a href="{lk}" style="background:#00fc40;color:#222;padding:12px 20px;'
        f'text-decoration:none;font-weight:bold;display:inline-block;">Join Interview</a>'
        f'</p>'
        f'<p style="font-size:13px;color:#555;">Link: {lk}</p>'
        f'<p>Best regards,<br>The Hiring Team</p>'
    )
    text = (
        f"Hi {candidate_name},\n\n"
        f"We would like to invite you to interview for the {position_title} position.\n"
        f"Link: {link}\n\nBest regards,\nThe Hiring Team"
    )
    return {"subject": subject, "html": html, "text": text}


def application_received(candidate_name: str, position_title: str) -> dict:
    cn = _h.escape(candidate_name or "Candidate")
    pt = _h.escape(position_title or "the role")
    subject = f"Application Received — {position_title}"
    html = _wrap(
        f'<h2 style="margin:0 0 12px;color:#007518;">Application Received</h2>'
        f'<p>Hi {cn},</p>'
        f'<p>Thank you for applying to the <strong>{pt}</strong> position. '
        f'We have received your application and our team will review it shortly.</p>'
        f'<p>If your profile matches, we will reach out with next steps.</p>'
        f'<p>Best regards,<br>The Hiring Team</p>'
    )
    text = (
        f"Hi {candidate_name},\n\n"
        f"Thank you for applying to the {position_title} position. "
        f"We have received your application and our team will review it shortly.\n\n"
        f"Best regards,\nThe Hiring Team"
    )
    return {"subject": subject, "html": html, "text": text}


def rejection(candidate_name: str, position_title: str) -> dict:
    cn = _h.escape(candidate_name or "Candidate")
    pt = _h.escape(position_title or "the role")
    subject = f"Update on your application — {position_title}"
    html = _wrap(
        f'<h2 style="margin:0 0 12px;color:#383832;">Application Update</h2>'
        f'<p>Hi {cn},</p>'
        f'<p>Thank you for taking the time to apply for the <strong>{pt}</strong> position '
        f'and for your interest in joining our team.</p>'
        f'<p>After careful review, we have decided to move forward with other candidates '
        f'whose experience more closely matches our current needs. This was not an easy '
        f'decision and we appreciate the effort you put into your application.</p>'
        f'<p>We will keep your profile on file and encourage you to apply for future roles.</p>'
        f'<p>Wishing you the best,<br>The Hiring Team</p>'
    )
    text = (
        f"Hi {candidate_name},\n\n"
        f"Thank you for applying for the {position_title} position. "
        f"After careful review, we have decided to move forward with other candidates. "
        f"We appreciate your interest and wish you the best.\n\n"
        f"The Hiring Team"
    )
    return {"subject": subject, "html": html, "text": text}
