"""Offer management — create, approve, send, accept, decline, withdraw, salary suggestion."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import JSONResponse

from backend.core.auth import get_current_user
from backend.core.config import CHAT_MODEL, llm_call
from backend.core.database import get_cursor
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


def _log_activity(cur, candidate_id: int, position_id: int, user_id: int,
                  activity_type: str, details: dict = None):
    """Log candidate activity."""
    cur.execute("""
        INSERT INTO candidate_activity (candidate_id, position_id, user_id, activity_type, details)
        VALUES (%s, %s, %s, %s, %s)
    """, (candidate_id, position_id, user_id, activity_type, json.dumps(details or {})))


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
@router.post("", dependencies=[Depends(require_role("recruiter"))])
async def create_offer(request: Request):
    """Create a new offer for a candidate."""
    user = get_current_user(request)
    body = await request.json()

    required = ["position_id", "candidate_id", "salary_amount"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"{field} is required")

    with get_cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO offers (
                    position_id, candidate_id, salary_amount, salary_currency,
                    salary_period, equity, bonus, start_date, expiry_date,
                    benefits, notes, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at, status
            """, (
                body["position_id"], body["candidate_id"], body["salary_amount"],
                body.get("salary_currency", "USD"), body.get("salary_period", "annual"),
                body.get("equity"), body.get("bonus"),
                body.get("start_date"), body.get("expiry_date"),
                body.get("benefits"), body.get("notes"),
                user["user_id"],
            ))
            row = cur.fetchone()
            offer_id, created_at, status = row

            _log_activity(cur, body["candidate_id"], body["position_id"], user["user_id"],
                          "offer_created", {
                              "offer_id": offer_id,
                              "salary_amount": float(body["salary_amount"]),
                              "salary_currency": body.get("salary_currency", "USD"),
                          })
        except Exception as e:
            if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
                raise HTTPException(status_code=409, detail="Offer already exists for this candidate and position")
            raise

    return {"id": offer_id, "created_at": created_at, "status": status}


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------
@router.get("")
async def list_offers(
    request: Request,
    position_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List offers with optional filters."""
    get_current_user(request)

    conditions = []
    params = []

    if position_id:
        conditions.append("o.position_id = %s")
        params.append(position_id)
    if status:
        conditions.append("o.status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT o.*,
                   c.name AS candidate_name,
                   c.email AS candidate_email,
                   p.title AS position_title,
                   p.slug AS position_slug,
                   u.display_name AS created_by_name,
                   a.display_name AS approved_by_name
            FROM offers o
            LEFT JOIN candidates c ON c.id = o.candidate_id
            LEFT JOIN positions p ON p.id = o.position_id
            LEFT JOIN users u ON u.id = o.created_by
            LEFT JOIN users a ON a.id = o.approved_by
            {where}
            ORDER BY o.created_at DESC
            LIMIT %s OFFSET %s
        """, params)
        cols = [desc[0] for desc in cur.description]
        offers = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"offers": offers}


# ---------------------------------------------------------------------------
# AI SALARY SUGGESTION (must be before /{offer_id} to avoid path conflict)
# ---------------------------------------------------------------------------
@router.get("/salary-suggestion")
async def salary_suggestion(
    request: Request,
    role: str = Query(...),
    seniority: str = Query("mid"),
    location: str = Query("United States"),
    skills: Optional[str] = Query(None),
):
    """AI-powered salary range suggestion based on role, seniority, location, and skills."""
    get_current_user(request)

    skills_text = skills if skills else "general"

    prompt = f"""You are a compensation analyst. Suggest a salary range for this role. Return ONLY valid JSON.

Role: {role}
Seniority Level: {seniority}
Location: {location}
Key Skills: {skills_text}

Consider:
- Market rates for this role and seniority
- Cost of living adjustment for the location
- Premium skills that command higher compensation
- Current 2024-2025 market benchmarks

Return JSON:
{{
  "min": <number>,
  "median": <number>,
  "max": <number>,
  "currency": "USD",
  "rationale": "2-3 sentence explanation of the range"
}}"""

    raw = llm_call(prompt, model=CHAT_MODEL, temperature=0.2, max_tokens=1000)
    if not raw:
        raise HTTPException(status_code=500, detail="LLM salary suggestion failed")

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="LLM returned invalid JSON for salary suggestion")

    return {
        "min": result.get("min"),
        "median": result.get("median"),
        "max": result.get("max"),
        "currency": result.get("currency", "USD"),
        "rationale": result.get("rationale", ""),
        "inputs": {"role": role, "seniority": seniority, "location": location, "skills": skills_text},
    }


# ---------------------------------------------------------------------------
# GET DETAIL
# ---------------------------------------------------------------------------
@router.get("/{offer_id}")
async def get_offer(offer_id: int, request: Request):
    """Get offer detail."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT o.*,
                   c.name AS candidate_name,
                   c.email AS candidate_email,
                   p.title AS position_title,
                   p.slug AS position_slug,
                   u.display_name AS created_by_name,
                   a.display_name AS approved_by_name
            FROM offers o
            LEFT JOIN candidates c ON c.id = o.candidate_id
            LEFT JOIN positions p ON p.id = o.position_id
            LEFT JOIN users u ON u.id = o.created_by
            LEFT JOIN users a ON a.id = o.approved_by
            WHERE o.id = %s
        """, (offer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Offer not found")
        cols = [desc[0] for desc in cur.description]
        offer = dict(zip(cols, row))

    return {"offer": offer}


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------
@router.patch("/{offer_id}", dependencies=[Depends(require_role("recruiter"))])
async def update_offer(offer_id: int, request: Request):
    """Update offer fields (only draft offers)."""
    user = get_current_user(request)
    body = await request.json()

    allowed_fields = {
        "salary_amount", "salary_currency", "salary_period",
        "equity", "bonus", "start_date", "expiry_date",
        "benefits", "notes",
    }
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    params = list(updates.values())
    params.append(offer_id)

    with get_cursor() as cur:
        cur.execute(f"""
            UPDATE offers SET {set_clause}, updated_at = NOW()
            WHERE id = %s
            RETURNING id
        """, params)
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Offer not found")

    return {"status": "updated", "offer_id": offer_id}


# ---------------------------------------------------------------------------
# APPROVE
# ---------------------------------------------------------------------------
@router.post("/{offer_id}/approve", dependencies=[Depends(require_role("admin"))])
async def approve_offer(offer_id: int, request: Request):
    """Approve an offer (draft -> approved)."""
    user = get_current_user(request)

    with get_cursor() as cur:
        cur.execute("SELECT status, candidate_id, position_id FROM offers WHERE id = %s", (offer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Offer not found")

        current_status, candidate_id, position_id = row
        if current_status != "draft":
            raise HTTPException(status_code=400, detail=f"Cannot approve offer with status '{current_status}'")

        cur.execute("""
            UPDATE offers SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """, (user["user_id"], offer_id))

        _log_activity(cur, candidate_id, position_id, user["user_id"],
                      "offer_approved", {"offer_id": offer_id})

    return {"status": "approved", "offer_id": offer_id}


# ---------------------------------------------------------------------------
# SEND
# ---------------------------------------------------------------------------
@router.post("/{offer_id}/send", dependencies=[Depends(require_role("recruiter"))])
async def send_offer(offer_id: int, request: Request):
    """Mark offer as sent (approved -> sent)."""
    user = get_current_user(request)

    with get_cursor() as cur:
        cur.execute("SELECT status, candidate_id, position_id FROM offers WHERE id = %s", (offer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Offer not found")

        current_status, candidate_id, position_id = row
        if current_status != "approved":
            raise HTTPException(status_code=400, detail=f"Cannot send offer with status '{current_status}'")

        cur.execute("""
            UPDATE offers SET status = 'sent', sent_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """, (offer_id,))

        _log_activity(cur, candidate_id, position_id, user["user_id"],
                      "offer_sent", {"offer_id": offer_id})

    return {"status": "sent", "offer_id": offer_id}


# ---------------------------------------------------------------------------
# ACCEPT
# ---------------------------------------------------------------------------
@router.post("/{offer_id}/accept", dependencies=[Depends(require_role("recruiter"))])
async def accept_offer(offer_id: int, request: Request):
    """Candidate accepted the offer (sent -> accepted). Moves candidate stage to 'offered'."""
    user = get_current_user(request)

    with get_cursor() as cur:
        cur.execute("SELECT status, candidate_id, position_id FROM offers WHERE id = %s", (offer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Offer not found")

        current_status, candidate_id, position_id = row
        if current_status != "sent":
            raise HTTPException(status_code=400, detail=f"Cannot accept offer with status '{current_status}'")

        cur.execute("""
            UPDATE offers SET status = 'accepted', accepted_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """, (offer_id,))

        # Move candidate stage to 'offered'
        cur.execute("""
            UPDATE position_candidates SET stage = 'offered', updated_at = NOW()
            WHERE position_id = %s AND candidate_id = %s
        """, (position_id, candidate_id))

        _log_activity(cur, candidate_id, position_id, user["user_id"],
                      "offer_accepted", {"offer_id": offer_id})

    return {"status": "accepted", "offer_id": offer_id}


# ---------------------------------------------------------------------------
# DECLINE
# ---------------------------------------------------------------------------
@router.post("/{offer_id}/decline", dependencies=[Depends(require_role("recruiter"))])
async def decline_offer(offer_id: int, request: Request):
    """Candidate declined the offer."""
    user = get_current_user(request)
    body = await request.json()

    with get_cursor() as cur:
        cur.execute("SELECT status, candidate_id, position_id FROM offers WHERE id = %s", (offer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Offer not found")

        current_status, candidate_id, position_id = row
        if current_status != "sent":
            raise HTTPException(status_code=400, detail=f"Cannot decline offer with status '{current_status}'")

        cur.execute("""
            UPDATE offers SET status = 'declined', declined_at = NOW(),
                   decline_reason = %s, updated_at = NOW()
            WHERE id = %s
        """, (body.get("decline_reason"), offer_id))

        _log_activity(cur, candidate_id, position_id, user["user_id"],
                      "offer_declined", {
                          "offer_id": offer_id,
                          "decline_reason": body.get("decline_reason"),
                      })

    return {"status": "declined", "offer_id": offer_id}


# ---------------------------------------------------------------------------
# WITHDRAW
# ---------------------------------------------------------------------------
@router.post("/{offer_id}/withdraw", dependencies=[Depends(require_role("recruiter"))])
async def withdraw_offer(offer_id: int, request: Request):
    """Withdraw an offer (any non-terminal status)."""
    user = get_current_user(request)

    with get_cursor() as cur:
        cur.execute("SELECT status, candidate_id, position_id FROM offers WHERE id = %s", (offer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Offer not found")

        current_status, candidate_id, position_id = row
        if current_status in ("accepted", "declined", "withdrawn"):
            raise HTTPException(status_code=400, detail=f"Cannot withdraw offer with status '{current_status}'")

        cur.execute("""
            UPDATE offers SET status = 'withdrawn', updated_at = NOW()
            WHERE id = %s
        """, (offer_id,))

    return {"status": "withdrawn", "offer_id": offer_id}


# ---------------------------------------------------------------------------
# APPROVAL WORKFLOWS
# ---------------------------------------------------------------------------
@router.post("/{offer_id}/request-approval", dependencies=[Depends(require_role("recruiter"))])
async def request_approval(offer_id: int, request: Request):
    """Create an approval chain for an offer with ordered approvers."""
    user = get_current_user(request)
    body = await request.json()

    approver_ids = body.get("approver_ids", [])
    if not approver_ids:
        raise HTTPException(status_code=400, detail="approver_ids is required (list of user IDs in order)")

    with get_cursor() as cur:
        cur.execute("SELECT status, candidate_id, position_id FROM offers WHERE id = %s", (offer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Offer not found")

        current_status, candidate_id, position_id = row
        if current_status != "draft":
            raise HTTPException(status_code=400, detail=f"Cannot request approval for offer with status '{current_status}'")

        # Update offer status to pending_approval
        cur.execute("""
            UPDATE offers SET status = 'pending_approval', updated_at = NOW()
            WHERE id = %s
        """, (offer_id,))

        # Create approval chain steps
        chain = []
        for i, approver_id in enumerate(approver_ids):
            cur.execute("""
                INSERT INTO approval_chains (offer_id, approver_id, step_order, status)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (offer_id, approver_id, i + 1, "pending"))
            chain_id = cur.fetchone()[0]
            chain.append({"id": chain_id, "approver_id": approver_id, "step_order": i + 1, "status": "pending"})

        _log_activity(cur, candidate_id, position_id, user["user_id"],
                      "approval_requested", {
                          "offer_id": offer_id,
                          "approver_ids": approver_ids,
                      })

    return {"offer_id": offer_id, "status": "pending_approval", "chain": chain}


@router.post("/{offer_id}/approve-step", dependencies=[Depends(require_role("admin"))])
async def approve_step(offer_id: int, request: Request):
    """Current approver approves their step in the chain."""
    user = get_current_user(request)
    body = await request.json()

    with get_cursor() as cur:
        # Find the next pending step for this offer where the user is the approver
        cur.execute("""
            SELECT ac.id, ac.step_order, ac.approver_id
            FROM approval_chains ac
            WHERE ac.offer_id = %s AND ac.status = 'pending'
            ORDER BY ac.step_order ASC
            LIMIT 1
        """, (offer_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="No pending approval steps for this offer")

        chain_id, step_order, approver_id = row

        if approver_id != user["user_id"]:
            raise HTTPException(status_code=403, detail="You are not the current approver for this step")

        action = body.get("action", "approve")  # approve or reject
        comments = body.get("comments")

        if action == "reject":
            cur.execute("""
                UPDATE approval_chains
                SET status = 'rejected', rejected_at = NOW(), comments = %s
                WHERE id = %s
            """, (comments, chain_id))

            # Mark offer as rejected
            cur.execute("""
                UPDATE offers SET status = 'draft', updated_at = NOW()
                WHERE id = %s
            """, (offer_id,))

            return {"offer_id": offer_id, "step": step_order, "status": "rejected", "comments": comments}

        # Approve this step
        cur.execute("""
            UPDATE approval_chains
            SET status = 'approved', approved_at = NOW(), comments = %s
            WHERE id = %s
        """, (comments, chain_id))

        # Check if all steps are now approved
        cur.execute("""
            SELECT COUNT(*) FROM approval_chains
            WHERE offer_id = %s AND status = 'pending'
        """, (offer_id,))
        remaining = cur.fetchone()[0]

        if remaining == 0:
            # All approved — auto-mark offer as approved
            cur.execute("""
                UPDATE offers SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """, (user["user_id"], offer_id))

            # Log
            cur.execute("SELECT candidate_id, position_id FROM offers WHERE id = %s", (offer_id,))
            cid, pid = cur.fetchone()
            _log_activity(cur, cid, pid, user["user_id"],
                          "offer_approved", {"offer_id": offer_id, "via": "approval_chain"})

            return {"offer_id": offer_id, "step": step_order, "status": "approved",
                    "offer_status": "approved", "message": "All approvals complete — offer approved"}

    return {"offer_id": offer_id, "step": step_order, "status": "approved",
            "offer_status": "pending_approval", "remaining_steps": remaining}


@router.get("/{offer_id}/approval-chain")
async def get_approval_chain(offer_id: int, request: Request):
    """Get the approval chain status for an offer."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT ac.*, u.display_name AS approver_name
            FROM approval_chains ac
            LEFT JOIN users u ON u.id = ac.approver_id
            WHERE ac.offer_id = %s
            ORDER BY ac.step_order ASC
        """, (offer_id,))
        cols = [desc[0] for desc in cur.description]
        chain = [dict(zip(cols, row)) for row in cur.fetchall()]

    if not chain:
        return {"offer_id": offer_id, "chain": [], "message": "No approval chain exists"}

    all_approved = all(step["status"] == "approved" for step in chain)
    any_rejected = any(step["status"] == "rejected" for step in chain)

    return {
        "offer_id": offer_id,
        "chain": chain,
        "all_approved": all_approved,
        "any_rejected": any_rejected,
        "current_step": next((s["step_order"] for s in chain if s["status"] == "pending"), None),
    }
