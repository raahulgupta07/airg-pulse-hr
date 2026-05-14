"""Email QA + status routes."""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.services import email_service, email_templates

router = APIRouter()


class SendTestBody(BaseModel):
    to: str
    template: str
    candidate_name: str | None = "Test Candidate"
    position_title: str | None = "Sample Position"
    link: str | None = "https://example.com/interview"


@router.get("/status")
async def email_status(request: Request):
    get_current_user(request)
    return email_service.status()


@router.post("/send-test")
async def send_test(body: SendTestBody, request: Request):
    user = get_current_user(request)
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="admin or superadmin only")

    name = body.candidate_name or "Test Candidate"
    pos = body.position_title or "Sample Position"
    tpl = (body.template or "").strip().lower()

    if tpl == "interview_invite":
        payload = email_templates.interview_invite(name, pos, body.link or "")
    elif tpl == "application_received":
        payload = email_templates.application_received(name, pos)
    elif tpl == "rejection":
        payload = email_templates.rejection(name, pos)
    else:
        raise HTTPException(
            status_code=400,
            detail="template must be one of: interview_invite, application_received, rejection",
        )

    if not email_service.is_configured():
        raise HTTPException(status_code=503, detail="SMTP not configured")

    ok = email_service.send_email(
        to=body.to,
        subject=payload["subject"],
        html=payload["html"],
        text=payload["text"],
    )
    return {"sent": ok, "to": body.to, "template": tpl, "subject": payload["subject"]}
