"""Duplicate detection — find, scan, and merge duplicate candidates."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request, HTTPException
from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


def _find_duplicates_for(candidate_id: int) -> dict:
    """Find potential duplicates for a given candidate."""
    with get_cursor() as cur:
        # Get the candidate
        cur.execute(
            "SELECT id, name, email, phone FROM candidates WHERE id = %s AND status = 'active'",
            (candidate_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"email": [], "phone": [], "name": []}

        cols = [desc[0] for desc in cur.description]
        candidate = dict(zip(cols, row))
        results = {"email": [], "phone": [], "name": []}

        # Exact email match
        if candidate.get("email"):
            cur.execute(
                "SELECT id, name, email, phone FROM candidates WHERE email = %s AND id != %s AND status = 'active'",
                (candidate["email"], candidate_id),
            )
            ecols = [desc[0] for desc in cur.description]
            results["email"] = [dict(zip(ecols, r)) for r in cur.fetchall()]

        # Exact phone match
        if candidate.get("phone"):
            cur.execute(
                "SELECT id, name, email, phone FROM candidates WHERE phone = %s AND id != %s AND status = 'active'",
                (candidate["phone"], candidate_id),
            )
            pcols = [desc[0] for desc in cur.description]
            results["phone"] = [dict(zip(pcols, r)) for r in cur.fetchall()]

        # Fuzzy name match via pg_trgm
        if candidate.get("name"):
            try:
                cur.execute(
                    "SELECT id, name, email, phone, similarity(name, %s) AS sim "
                    "FROM candidates WHERE similarity(name, %s) > 0.6 AND id != %s AND status = 'active' "
                    "ORDER BY sim DESC",
                    (candidate["name"], candidate["name"], candidate_id),
                )
                ncols = [desc[0] for desc in cur.description]
                results["name"] = [dict(zip(ncols, r)) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"pg_trgm similarity query failed (extension may not be installed): {e}")
                results["name"] = []

        return results


@router.get("/check/{candidate_id}")
async def find_duplicates(candidate_id: int, request: Request):
    """Find potential duplicates for a specific candidate. GET /api/duplicates/check/{id}"""
    get_current_user(request)
    results = _find_duplicates_for(candidate_id)

    # Deduplicate across match types
    seen = set()
    all_dupes = []
    for match_type in ("email", "phone", "name"):
        for d in results[match_type]:
            if d["id"] not in seen:
                seen.add(d["id"])
                all_dupes.append({**d, "match_type": match_type})

    return {"candidate_id": candidate_id, "duplicates": all_dupes, "details": results}


@router.post("/scan", dependencies=[Depends(require_role("admin"))])
async def scan_all_duplicates(request: Request):
    """Scan all active candidates for duplicates. Returns groups."""
    get_current_user(request)

    with get_cursor() as cur:
        groups = []

        # Email duplicates
        cur.execute("""
            SELECT email, array_agg(id ORDER BY id) AS ids, array_agg(name ORDER BY id) AS names
            FROM candidates
            WHERE email IS NOT NULL AND email != '' AND status = 'active'
            GROUP BY email
            HAVING COUNT(*) > 1
        """)
        ecols = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            r = dict(zip(ecols, row))
            groups.append({
                "match_type": "email",
                "match_value": r["email"],
                "candidate_ids": r["ids"],
                "candidate_names": r["names"],
            })

        # Phone duplicates
        cur.execute("""
            SELECT phone, array_agg(id ORDER BY id) AS ids, array_agg(name ORDER BY id) AS names
            FROM candidates
            WHERE phone IS NOT NULL AND phone != '' AND status = 'active'
            GROUP BY phone
            HAVING COUNT(*) > 1
        """)
        pcols = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            r = dict(zip(pcols, row))
            groups.append({
                "match_type": "phone",
                "match_value": r["phone"],
                "candidate_ids": r["ids"],
                "candidate_names": r["names"],
            })

    return {"groups": groups, "total_groups": len(groups)}


@router.post("/merge", dependencies=[Depends(require_role("admin"))])
async def merge_candidates(request: Request):
    """Merge two candidates: move all linked data from merge_id to keep_id, then archive merge_id."""
    user = get_current_user(request)
    body = await request.json()
    keep_id = body.get("keep_id")
    merge_id = body.get("merge_id")

    if not keep_id or not merge_id:
        raise HTTPException(status_code=400, detail="keep_id and merge_id are required")
    if keep_id == merge_id:
        raise HTTPException(status_code=400, detail="Cannot merge a candidate with itself")

    with get_cursor() as cur:
        # Verify both exist
        cur.execute("SELECT id FROM candidates WHERE id IN (%s, %s) AND status = 'active'", (keep_id, merge_id))
        found = [r[0] for r in cur.fetchall()]
        if keep_id not in found:
            raise HTTPException(status_code=404, detail=f"Candidate {keep_id} not found or not active")
        if merge_id not in found:
            raise HTTPException(status_code=404, detail=f"Candidate {merge_id} not found or not active")

        # Move position_candidates (skip if already linked to same position)
        cur.execute("""
            UPDATE position_candidates SET candidate_id = %s
            WHERE candidate_id = %s
            AND position_id NOT IN (SELECT position_id FROM position_candidates WHERE candidate_id = %s)
        """, (keep_id, merge_id, keep_id))

        # Move notes
        cur.execute(
            "UPDATE candidate_notes SET candidate_id = %s WHERE candidate_id = %s",
            (keep_id, merge_id),
        )

        # Move activity
        cur.execute(
            "UPDATE candidate_activity SET candidate_id = %s WHERE candidate_id = %s",
            (keep_id, merge_id),
        )

        # Move tags
        try:
            cur.execute("""
                UPDATE candidate_tags SET candidate_id = %s
                WHERE candidate_id = %s
                AND tag NOT IN (SELECT tag FROM candidate_tags WHERE candidate_id = %s)
            """, (keep_id, merge_id, keep_id))
        except Exception:
            pass  # table may not exist yet

        # Move interviews
        try:
            cur.execute(
                "UPDATE interviews SET candidate_id = %s WHERE candidate_id = %s",
                (keep_id, merge_id),
            )
        except Exception:
            pass

        # Archive the merged candidate
        cur.execute(
            "UPDATE candidates SET status = 'archived', updated_at = NOW() WHERE id = %s",
            (merge_id,),
        )

        # Log activity
        cur.execute("""
            INSERT INTO candidate_activity (candidate_id, event_type, description, user_id)
            VALUES (%s, 'merged', %s, %s)
        """, (keep_id, f"Merged with candidate #{merge_id}", user.get("user_id")))

    return {
        "message": f"Candidate {merge_id} merged into {keep_id}",
        "keep_id": keep_id,
        "merge_id": merge_id,
    }
