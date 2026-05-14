"""Email routes — send, bulk-send, log, preview, AI compose."""
from __future__ import annotations

import os
import json
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import JSONResponse

from backend.core.auth import get_current_user
from backend.core.config import CHAT_MODEL, llm_call
from backend.core.database import get_cursor
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# SMTP helper
# ---------------------------------------------------------------------------
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email via SMTP. Returns status dict."""
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        return {"status": "skipped", "reason": "SMTP not configured"}

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = to
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            if smtp_port == 587:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [to], msg.as_string())

        return {"status": "sent"}
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return {"status": "failed", "reason": str(e)}


def _fill_template(template: str, variables: dict) -> str:
    """Replace {var} placeholders in template with variable values."""
    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", str(value))
    return result


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------
@router.post("/send", dependencies=[Depends(require_role("recruiter"))])
async def send_single_email(request: Request):
    """Send a single email and log it."""
    user = get_current_user(request)
    body = await request.json()

    candidate_id = body.get("candidate_id")
    recipient_email = body.get("recipient_email")
    subject = body.get("subject")
    email_body = body.get("body")

    if not recipient_email or not subject or not email_body:
        raise HTTPException(status_code=400, detail="recipient_email, subject, and body are required")

    result = send_email(recipient_email, subject, email_body)

    # Log to database
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO email_log (
                candidate_id, position_id, template_id,
                recipient_email, subject, body,
                status, sent_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            candidate_id, body.get("position_id"), body.get("template_id"),
            recipient_email, subject, email_body,
            result["status"], user["user_id"],
        ))
        log_id = cur.fetchone()[0]

    return {"id": log_id, **result}


@router.post("/bulk-send", dependencies=[Depends(require_role("recruiter"))])
async def bulk_send_emails(request: Request):
    """Bulk send emails to multiple candidates."""
    user = get_current_user(request)
    body = await request.json()

    candidate_ids = body.get("candidate_ids", [])
    template_id = body.get("template_id")
    subject = body.get("subject")
    body_template = body.get("body_template")

    if not candidate_ids or not subject or not body_template:
        raise HTTPException(status_code=400, detail="candidate_ids, subject, and body_template are required")

    results = []
    with get_cursor() as cur:
        # Fetch candidate info
        cur.execute("""
            SELECT id, name, email, "current_role", "current_company"
            FROM candidates
            WHERE id = ANY(%s) AND email IS NOT NULL
        """, (candidate_ids,))
        cols = [desc[0] for desc in cur.description]
        candidates = [dict(zip(cols, row)) for row in cur.fetchall()]

        for cand in candidates:
            variables = {
                "name": cand.get("name", ""),
                "role": cand.get("current_role", ""),
                "company": cand.get("current_company", ""),
            }
            filled_body = _fill_template(body_template, variables)
            filled_subject = _fill_template(subject, variables)

            result = send_email(cand["email"], filled_subject, filled_body)

            cur.execute("""
                INSERT INTO email_log (
                    candidate_id, template_id,
                    recipient_email, subject, body,
                    status, sent_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                cand["id"], template_id,
                cand["email"], filled_subject, filled_body,
                result["status"], user["user_id"],
            ))
            log_id = cur.fetchone()[0]
            results.append({"candidate_id": cand["id"], "log_id": log_id, **result})

    return {"results": results, "total": len(results)}


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------
@router.get("/log")
async def list_email_log(
    request: Request,
    candidate_id: Optional[int] = Query(None),
    position_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List sent emails with optional filters."""
    get_current_user(request)

    conditions = []
    params = []
    if candidate_id:
        conditions.append("el.candidate_id = %s")
        params.append(candidate_id)
    if position_id:
        conditions.append("el.position_id = %s")
        params.append(position_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT el.*, u.display_name AS sender_name
            FROM email_log el
            LEFT JOIN users u ON u.id = el.sent_by
            {where}
            ORDER BY el.created_at DESC
            LIMIT %s OFFSET %s
        """, params)
        cols = [desc[0] for desc in cur.description]
        emails = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"emails": emails}


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------
@router.post("/preview", dependencies=[Depends(require_role("recruiter"))])
async def preview_template(request: Request):
    """Preview a template with variables filled in."""
    get_current_user(request)
    body = await request.json()

    template_id = body.get("template_id")
    variables = body.get("variables", {})

    if template_id:
        with get_cursor() as cur:
            cur.execute("SELECT content, name FROM templates WHERE id = %s", (template_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Template not found")
            template_content = row[0]
            template_name = row[1]
    else:
        template_content = body.get("body", "")
        template_name = "custom"

    filled = _fill_template(template_content, variables)

    return {"preview": filled, "template_name": template_name}


# ---------------------------------------------------------------------------
# AI Rejection Email Composer
# ---------------------------------------------------------------------------
@router.post("/compose-rejection", dependencies=[Depends(require_role("recruiter"))])
async def compose_rejection(request: Request):
    """AI-compose a personalized, empathetic rejection email."""
    user = get_current_user(request)
    body = await request.json()

    candidate_id = body.get("candidate_id")
    position_id = body.get("position_id")
    stage = body.get("stage", "interview")
    feedback_notes = body.get("feedback_notes", "")

    if not candidate_id or not position_id:
        raise HTTPException(status_code=400, detail="candidate_id and position_id are required")

    # Fetch candidate and position info
    with get_cursor() as cur:
        cur.execute("SELECT name, email FROM candidates WHERE id = %s", (candidate_id,))
        cand_row = cur.fetchone()
        if not cand_row:
            raise HTTPException(status_code=404, detail="Candidate not found")
        candidate_name, candidate_email = cand_row

        cur.execute("SELECT title, department FROM positions WHERE id = %s", (position_id,))
        pos_row = cur.fetchone()
        if not pos_row:
            raise HTTPException(status_code=404, detail="Position not found")
        position_title, department = pos_row

        # Fetch any interview scorecards for context
        scorecard_summary = ""
        try:
            cur.execute("""
                SELECT sc.strengths, sc.concerns, sc.summary
                FROM interview_scorecards sc
                JOIN interviews i ON i.id = sc.interview_id
                WHERE i.candidate_id = %s AND i.position_id = %s
                ORDER BY sc.created_at DESC LIMIT 3
            """, (candidate_id, position_id))
            scorecards = cur.fetchall()
            if scorecards:
                parts = []
                for s, c, sm in scorecards:
                    if s: parts.append(f"Strengths: {s}")
                    if c: parts.append(f"Concerns: {c}")
                    if sm: parts.append(f"Summary: {sm}")
                scorecard_summary = "\n".join(parts)
        except Exception:
            pass

    prompt = f"""Write a personalized, empathetic rejection email for a job candidate.

Candidate Name: {candidate_name}
Position: {position_title}
Department: {department or 'N/A'}
Stage Reached: {stage}
Feedback Notes: {feedback_notes or 'None provided'}
Interview Feedback: {scorecard_summary or 'None available'}

Guidelines:
- Be warm, respectful, and specific — avoid generic language
- Reference something positive about the candidate's application
- If there's feedback, subtly reference it without being harsh
- Encourage them to apply for future roles
- Keep it concise (3-4 paragraphs)

Return ONLY valid JSON:
{{"subject": "string", "body": "string (HTML formatted)"}}"""

    raw = llm_call(prompt, model=CHAT_MODEL, temperature=0.4, max_tokens=2000)
    if not raw:
        raise HTTPException(status_code=500, detail="LLM composition failed")

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="LLM returned invalid JSON")

    return {
        "subject": result.get("subject", f"Update on your application — {position_title}"),
        "body": result.get("body", ""),
        "candidate_name": candidate_name,
        "candidate_email": candidate_email,
    }


# ---------------------------------------------------------------------------
# AI Offer Email Composer
# ---------------------------------------------------------------------------
@router.post("/compose-offer", dependencies=[Depends(require_role("recruiter"))])
async def compose_offer(request: Request):
    """AI-compose a warm, exciting offer email."""
    user = get_current_user(request)
    body = await request.json()

    candidate_id = body.get("candidate_id")
    position_id = body.get("position_id")
    salary = body.get("salary")
    start_date = body.get("start_date")

    if not candidate_id or not position_id:
        raise HTTPException(status_code=400, detail="candidate_id and position_id are required")

    with get_cursor() as cur:
        cur.execute("SELECT name, email FROM candidates WHERE id = %s", (candidate_id,))
        cand_row = cur.fetchone()
        if not cand_row:
            raise HTTPException(status_code=404, detail="Candidate not found")
        candidate_name, candidate_email = cand_row

        cur.execute("SELECT title, department FROM positions WHERE id = %s", (position_id,))
        pos_row = cur.fetchone()
        if not pos_row:
            raise HTTPException(status_code=404, detail="Position not found")
        position_title, department = pos_row

    prompt = f"""Write a warm, exciting job offer email.

Candidate Name: {candidate_name}
Position: {position_title}
Department: {department or 'N/A'}
Salary: {salary or 'To be discussed'}
Start Date: {start_date or 'To be confirmed'}

Guidelines:
- Express genuine excitement about the candidate joining the team
- Mention the role and what makes it special
- Include salary and start date if provided
- Keep it professional but enthusiastic
- Include next steps (formal offer letter, onboarding)
- 3-4 paragraphs

Return ONLY valid JSON:
{{"subject": "string", "body": "string (HTML formatted)"}}"""

    raw = llm_call(prompt, model=CHAT_MODEL, temperature=0.4, max_tokens=2000)
    if not raw:
        raise HTTPException(status_code=500, detail="LLM composition failed")

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="LLM returned invalid JSON")

    return {
        "subject": result.get("subject", f"Offer: {position_title}"),
        "body": result.get("body", ""),
        "candidate_name": candidate_name,
        "candidate_email": candidate_email,
    }


# ---------------------------------------------------------------------------
# Email Sequences
# ---------------------------------------------------------------------------
@router.get("/sequences")
async def list_sequences(
    request: Request,
    position_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List email sequences."""
    get_current_user(request)

    conditions = []
    params = []
    if position_id is not None:
        conditions.append("es.position_id = %s")
        params.append(position_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT es.*, u.display_name AS created_by_name,
                   p.title AS position_title
            FROM email_sequences es
            LEFT JOIN users u ON u.id = es.created_by
            LEFT JOIN positions p ON p.id = es.position_id
            {where}
            ORDER BY es.created_at DESC
            LIMIT %s OFFSET %s
        """, params)
        cols = [desc[0] for desc in cur.description]
        sequences = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"sequences": sequences}


@router.post("/sequences", dependencies=[Depends(require_role("admin"))])
async def create_sequence(request: Request):
    """Create an email sequence with steps."""
    user = get_current_user(request)
    body = await request.json()

    name = body.get("name")
    steps = body.get("steps", [])
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not steps:
        raise HTTPException(status_code=400, detail="steps are required (at least one)")

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO email_sequences (name, position_id, steps, created_by)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
        """, (
            name, body.get("position_id"),
            json.dumps(steps), user["user_id"],
        ))
        row = cur.fetchone()

    return {"id": row[0], "created_at": row[1]}


@router.post("/sequences/{sequence_id}/enroll", dependencies=[Depends(require_role("recruiter"))])
async def enroll_candidates(sequence_id: int, request: Request):
    """Enroll candidates into an email sequence."""
    user = get_current_user(request)
    body = await request.json()

    candidate_ids = body.get("candidate_ids", [])
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids is required")

    with get_cursor() as cur:
        # Verify sequence exists and get first step delay
        cur.execute("SELECT steps, is_active FROM email_sequences WHERE id = %s", (sequence_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sequence not found")
        steps, is_active = row
        if not is_active:
            raise HTTPException(status_code=400, detail="Sequence is not active")

        steps_list = steps if isinstance(steps, list) else json.loads(steps)
        first_delay = steps_list[0].get("delay_days", 0) if steps_list else 0

        enrolled = []
        for cid in candidate_ids:
            try:
                cur.execute("""
                    INSERT INTO email_sequence_enrollments (
                        sequence_id, candidate_id, current_step, status,
                        next_send_at
                    ) VALUES (%s, %s, 0, 'active', NOW() + INTERVAL '%s days')
                    RETURNING id
                """, (sequence_id, cid, first_delay))
                eid = cur.fetchone()[0]
                enrolled.append({"candidate_id": cid, "enrollment_id": eid})
            except Exception as e:
                if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                    enrolled.append({"candidate_id": cid, "status": "already_enrolled"})
                else:
                    enrolled.append({"candidate_id": cid, "status": "error", "reason": str(e)})

    return {"enrolled": enrolled, "total": len(enrolled)}


@router.post("/sequences/{sequence_id}/pause", dependencies=[Depends(require_role("admin"))])
async def pause_enrollment(sequence_id: int, request: Request):
    """Pause a candidate's enrollment in a sequence."""
    get_current_user(request)
    body = await request.json()

    candidate_id = body.get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=400, detail="candidate_id is required")

    action = body.get("action", "pause")  # pause or resume

    with get_cursor() as cur:
        if action == "pause":
            cur.execute("""
                UPDATE email_sequence_enrollments
                SET status = 'paused'
                WHERE sequence_id = %s AND candidate_id = %s AND status = 'active'
                RETURNING id
            """, (sequence_id, candidate_id))
        else:
            cur.execute("""
                UPDATE email_sequence_enrollments
                SET status = 'active'
                WHERE sequence_id = %s AND candidate_id = %s AND status = 'paused'
                RETURNING id
            """, (sequence_id, candidate_id))

        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Enrollment not found or already in target status")

    return {"status": action + "d", "enrollment_id": row[0]}


@router.post("/sequences/process", dependencies=[Depends(require_role("admin"))])
async def process_sequences(request: Request):
    """Process pending sequence emails -- send due emails and advance steps."""
    get_current_user(request)

    results = []
    with get_cursor() as cur:
        # Find enrollments with due emails
        cur.execute("""
            SELECT ese.id, ese.sequence_id, ese.candidate_id, ese.current_step,
                   es.steps,
                   c.email, c.name, c."current_role", c."current_company"
            FROM email_sequence_enrollments ese
            JOIN email_sequences es ON es.id = ese.sequence_id
            JOIN candidates c ON c.id = ese.candidate_id
            WHERE ese.status = 'active'
              AND ese.next_send_at <= NOW()
              AND es.is_active = TRUE
        """)
        cols = [desc[0] for desc in cur.description]
        pending = [dict(zip(cols, row)) for row in cur.fetchall()]

        for enrollment in pending:
            steps_data = enrollment["steps"]
            steps_list = steps_data if isinstance(steps_data, list) else json.loads(steps_data)
            step_idx = enrollment["current_step"]

            if step_idx >= len(steps_list):
                # Sequence complete
                cur.execute("""
                    UPDATE email_sequence_enrollments
                    SET status = 'completed', completed_at = NOW()
                    WHERE id = %s
                """, (enrollment["id"],))
                results.append({
                    "enrollment_id": enrollment["id"],
                    "status": "completed",
                })
                continue

            step = steps_list[step_idx]
            variables = {
                "name": enrollment.get("name", ""),
                "role": enrollment.get("current_role", ""),
                "company": enrollment.get("current_company", ""),
            }

            subject = _fill_template(step.get("subject", ""), variables)
            body_text = _fill_template(step.get("body_template", ""), variables)

            # Send
            email_result = send_email(enrollment["email"], subject, body_text)

            # Log
            cur.execute("""
                INSERT INTO email_log (
                    candidate_id, recipient_email, subject, body, status
                ) VALUES (%s, %s, %s, %s, %s)
            """, (
                enrollment["candidate_id"], enrollment["email"],
                subject, body_text, email_result.get("status", "unknown"),
            ))

            # Advance step
            next_step = step_idx + 1
            if next_step >= len(steps_list):
                cur.execute("""
                    UPDATE email_sequence_enrollments
                    SET current_step = %s, status = 'completed', completed_at = NOW()
                    WHERE id = %s
                """, (next_step, enrollment["id"]))
            else:
                next_delay = steps_list[next_step].get("delay_days", 1)
                cur.execute("""
                    UPDATE email_sequence_enrollments
                    SET current_step = %s, next_send_at = NOW() + INTERVAL '%s days'
                    WHERE id = %s
                """, (next_step, next_delay, enrollment["id"]))

            results.append({
                "enrollment_id": enrollment["id"],
                "candidate_id": enrollment["candidate_id"],
                "step": step_idx,
                "email_status": email_result.get("status"),
            })

    return {"processed": len(results), "results": results}
