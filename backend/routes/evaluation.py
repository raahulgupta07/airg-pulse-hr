"""Evaluation routes — rubrics, flags, consensus, votes, calibration, stack ranking."""
from __future__ import annotations

import json
import logging
import math
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Request, HTTPException, Query

from backend.core.auth import get_current_user
from backend.core.database import get_cursor, get_position, get_candidate
from backend.core.permissions import require_role, ensure_owner_or_min
from backend.core.config import llm_call, LITE_MODEL, is_ai_available

logger = logging.getLogger(__name__)
router = APIRouter()


# ===========================================================================
# SCORECARD TEMPLATES
# ===========================================================================

ROLE_TYPE_KEYWORDS = {
    "engineering": ["engineer", "developer", "software", "sre", "devops", "backend", "frontend", "fullstack", "architect", "data engineer", "ml engineer", "platform"],
    "sales": ["sales", "account executive", "business development", "bdr", "sdr", "revenue"],
    "design": ["designer", "ux", "ui", "product design", "graphic", "visual", "creative"],
    "product": ["product manager", "product owner", "program manager", "pm"],
    "marketing": ["marketing", "growth", "content", "brand", "demand gen", "seo", "social media"],
}


def match_template_to_position(position: dict) -> str:
    """Determine the best scorecard template role_type for a position based on title/department."""
    title = (position.get("title") or "").lower()
    dept = (position.get("department") or "").lower()
    combined = f"{title} {dept}"

    for role_type, keywords in ROLE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return role_type
    return "general"


@router.get("/templates")
async def list_templates(request: Request):
    """List all scorecard templates."""
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute("SELECT * FROM scorecard_templates ORDER BY is_default DESC, name")
        cols = [d[0] for d in cur.description]
        templates = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"templates": templates}


@router.get("/templates/{role_type}")
async def get_template(role_type: str, request: Request):
    """Get template for a specific role type."""
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute("SELECT * FROM scorecard_templates WHERE role_type = %s LIMIT 1", (role_type,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT * FROM scorecard_templates WHERE role_type = 'general' LIMIT 1")
            row = cur.fetchone()
        if not row:
            return {"template": None}
        cols = [d[0] for d in cur.description]
        return {"template": dict(zip(cols, row))}


# ===========================================================================
# EVALUATION RUBRICS
# ===========================================================================

@router.get("/positions/{slug}/rubrics")
async def get_rubrics(slug: str, request: Request):
    """Get evaluation rubrics for a position."""
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")

    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM evaluation_rubrics WHERE position_id = %s ORDER BY category, dimension
        """, (position["id"],))
        cols = [d[0] for d in cur.description]
        rubrics = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Also get matched template
    role_type = match_template_to_position(position)

    return {"rubrics": rubrics, "matched_role_type": role_type}


@router.put("/positions/{slug}/rubrics")
async def update_rubrics(slug: str, request: Request):
    """Update rubrics for a position."""
    user = get_current_user(request)
    body = await request.json()

    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)

    rubrics = body.get("rubrics", [])

    with get_cursor() as cur:
        # Delete existing and re-insert
        cur.execute("DELETE FROM evaluation_rubrics WHERE position_id = %s", (position["id"],))
        for r in rubrics:
            cur.execute("""
                INSERT INTO evaluation_rubrics (position_id, dimension, description,
                    score_1_label, score_2_label, score_3_label, score_4_label, score_5_label,
                    weight, category)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                position["id"], r.get("dimension"), r.get("description"),
                r.get("score_1_label", "Poor"), r.get("score_2_label", "Below Average"),
                r.get("score_3_label", "Adequate"), r.get("score_4_label", "Good"),
                r.get("score_5_label", "Excellent"),
                r.get("weight", 1.0), r.get("category", "technical"),
            ))

    return {"status": "updated", "count": len(rubrics)}


def auto_generate_rubrics(position_id: int, jd_text: str):
    """Auto-generate evaluation rubrics from JD text. Called internally after JD save."""
    if not jd_text:
        return

    with get_cursor() as cur:
        # Get position info
        cur.execute("SELECT title, department FROM positions WHERE id = %s", (position_id,))
        row = cur.fetchone()
        if not row:
            return
        title, department = row

        # Get matching template
        position = {"title": title, "department": department}
        role_type = match_template_to_position(position)

        # Get template dimensions
        cur.execute("SELECT id, dimensions FROM scorecard_templates WHERE role_type = %s LIMIT 1", (role_type,))
        tmpl_row = cur.fetchone()
        if not tmpl_row:
            cur.execute("SELECT id, dimensions FROM scorecard_templates WHERE role_type = 'general' LIMIT 1")
            tmpl_row = cur.fetchone()

        if not tmpl_row:
            return

        template_id, dimensions = tmpl_row
        if isinstance(dimensions, str):
            dimensions = json.loads(dimensions)

        # Delete existing auto-generated rubrics
        cur.execute("DELETE FROM evaluation_rubrics WHERE position_id = %s", (position_id,))

        # Insert rubrics from template
        for dim in dimensions:
            cur.execute("""
                INSERT INTO evaluation_rubrics (position_id, dimension, description,
                    weight, category, source_template_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                position_id, dim["dimension"], dim.get("description", ""),
                dim.get("weight", 1.0), dim.get("category", "technical"),
                template_id,
            ))

    logger.info(f"Auto-generated {len(dimensions)} rubrics for position {position_id} (template: {role_type})")


# ===========================================================================
# AI RED/GREEN/AMBER FLAGS
# ===========================================================================

def generate_flags(position_id: int, candidate_id: int, candidate: dict, position: dict):
    """Auto-generate evaluation flags for a candidate-position pair. Deterministic rules."""
    flags = []

    # Parse experience if string
    experience = candidate.get("experience", [])
    if isinstance(experience, str):
        try:
            experience = json.loads(experience)
        except (json.JSONDecodeError, TypeError):
            experience = []

    cv_years = candidate.get("total_experience_years") or 0
    min_years = position.get("min_experience_years") or 0
    required_skills = position.get("required_skills") or []
    cv_skills = [s.lower() for s in (candidate.get("skills_technical") or [])]
    required_lower = [s.lower() for s in required_skills]

    # --- RED FLAGS ---

    # Job hopping: more than 2 stints under 12 months
    short_stints = 0
    for exp in experience:
        dur = exp.get("duration_months")
        if dur and dur < 12:
            short_stints += 1
    if short_stints >= 3:
        flags.append({"flag_type": "red", "category": "job_hopping", "title": "Frequent Job Changes", "description": f"{short_stints} positions held less than 12 months"})
    elif short_stints == 2:
        flags.append({"flag_type": "amber", "category": "job_hopping", "title": "Some Short Tenures", "description": f"{short_stints} positions held less than 12 months"})

    # Employment gaps > 6 months
    if len(experience) >= 2:
        for i in range(len(experience) - 1):
            end_date = experience[i].get("end_date")
            start_date = experience[i + 1].get("start_date")
            if end_date and start_date:
                try:
                    end_parts = end_date.split("-")
                    start_parts = start_date.split("-")
                    if len(end_parts) >= 2 and len(start_parts) >= 2:
                        end_months = int(end_parts[0]) * 12 + int(end_parts[1])
                        start_months = int(start_parts[0]) * 12 + int(start_parts[1])
                        gap = start_months - end_months
                        if gap > 12:
                            flags.append({"flag_type": "red", "category": "gap", "title": "Large Employment Gap", "description": f"{gap} month gap detected"})
                        elif gap > 6:
                            flags.append({"flag_type": "amber", "category": "gap", "title": "Employment Gap", "description": f"{gap} month gap detected"})
                except (ValueError, IndexError):
                    pass

    # Underqualified
    if min_years > 0 and cv_years < min_years * 0.5:
        flags.append({"flag_type": "red", "category": "underqualified", "title": "Significantly Underqualified", "description": f"{cv_years}yr experience vs {min_years}yr required"})
    elif min_years > 0 and cv_years < min_years * 0.7:
        flags.append({"flag_type": "amber", "category": "underqualified", "title": "Below Experience Requirement", "description": f"{cv_years}yr experience vs {min_years}yr required"})

    # Missing critical skills
    if required_lower:
        matched = set(cv_skills) & set(required_lower)
        missing_pct = 1 - (len(matched) / len(required_lower))
        if missing_pct > 0.5:
            flags.append({"flag_type": "red", "category": "missing_skills", "title": "Missing Majority of Required Skills", "description": f"Only {len(matched)}/{len(required_lower)} required skills matched"})
        elif missing_pct > 0.3:
            flags.append({"flag_type": "amber", "category": "missing_skills", "title": "Some Required Skills Missing", "description": f"{len(matched)}/{len(required_lower)} required skills matched"})

    # Overqualified
    if min_years > 0 and cv_years > min_years * 2.5:
        flags.append({"flag_type": "amber", "category": "overqualified", "title": "Potentially Overqualified", "description": f"{cv_years}yr experience vs {min_years}yr required — may expect higher compensation"})

    # --- GREEN FLAGS ---

    # All required skills matched
    if required_lower and set(cv_skills) >= set(required_lower):
        flags.append({"flag_type": "green", "category": "skills_match", "title": "All Required Skills Matched", "description": f"All {len(required_lower)} required skills present"})

    # Exceeds experience
    if min_years > 0 and cv_years >= min_years * 1.3 and cv_years <= min_years * 2.5:
        flags.append({"flag_type": "green", "category": "experience_fit", "title": "Strong Experience Fit", "description": f"{cv_years}yr experience exceeds {min_years}yr requirement"})

    # High quality score
    quality = candidate.get("quality_score") or 0
    if quality >= 80:
        flags.append({"flag_type": "green", "category": "quality", "title": "High Quality CV", "description": f"CV quality score: {quality}/100"})

    # Save flags to database
    with get_cursor() as cur:
        # Delete existing auto flags for this pair
        cur.execute("DELETE FROM candidate_flags WHERE position_id = %s AND candidate_id = %s AND auto_generated = TRUE", (position_id, candidate_id))

        for f in flags:
            cur.execute("""
                INSERT INTO candidate_flags (position_id, candidate_id, flag_type, category, title, description, auto_generated)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            """, (position_id, candidate_id, f["flag_type"], f["category"], f["title"], f.get("description")))

    return flags


@router.get("/positions/{slug}/flags")
async def get_position_flags(slug: str, request: Request):
    """Get all flags for all candidates in a position, keyed by candidate_id."""
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")

    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM candidate_flags WHERE position_id = %s ORDER BY candidate_id, flag_type
        """, (position["id"],))
        cols = [d[0] for d in cur.description]
        all_flags = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Group by candidate_id
    flags_by_candidate = {}
    for f in all_flags:
        cid = f["candidate_id"]
        if cid not in flags_by_candidate:
            flags_by_candidate[cid] = []
        flags_by_candidate[cid].append(f)

    return {"flags": flags_by_candidate}


@router.get("/candidates/{candidate_id}/flags")
async def get_candidate_flags(candidate_id: int, request: Request):
    """Get all flags for a candidate across all positions."""
    get_current_user(request)
    with get_cursor() as cur:
        cur.execute("""
            SELECT cf.*, p.title as position_title
            FROM candidate_flags cf
            JOIN positions p ON p.id = cf.position_id
            WHERE cf.candidate_id = %s
            ORDER BY cf.position_id, cf.flag_type
        """, (candidate_id,))
        cols = [d[0] for d in cur.description]
        flags = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"flags": flags}


# ===========================================================================
# CULTURE / VALUES SCORING
# ===========================================================================

def score_culture(candidate: dict, position: dict) -> int:
    """Score cultural alignment based on position's culture_values keywords."""
    culture_values = position.get("culture_values") or []
    if isinstance(culture_values, str):
        try:
            culture_values = json.loads(culture_values)
        except (json.JSONDecodeError, TypeError):
            culture_values = []

    if not culture_values:
        return 70  # neutral default

    # Build search text from candidate
    search_parts = []
    search_parts.append(candidate.get("summary_short") or "")
    search_parts.append(candidate.get("summary_detailed") or "")
    search_parts.append(" ".join(candidate.get("skills_soft") or []))

    experience = candidate.get("experience") or []
    if isinstance(experience, str):
        try:
            experience = json.loads(experience)
        except (json.JSONDecodeError, TypeError):
            experience = []
    for exp in experience:
        search_parts.append(exp.get("description") or "")
        search_parts.append(exp.get("role") or "")

    search_text = " ".join(search_parts).lower()

    total_weight = 0
    matched_weight = 0

    for val in culture_values:
        keywords = val.get("keywords") or []
        weight = val.get("weight", 1.0)
        total_weight += weight

        for kw in keywords:
            if kw.lower() in search_text:
                matched_weight += weight
                break  # one match per value is enough

    if total_weight == 0:
        return 70

    score = round((matched_weight / total_weight) * 100)
    return min(100, max(0, score))


@router.put("/positions/{slug}/culture-values")
async def update_culture_values(slug: str, request: Request):
    """Update culture values for a position."""
    user = get_current_user(request)
    body = await request.json()

    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")
    ensure_owner_or_min(user, position.get("hiring_manager_id"), "admin", request)

    values = body.get("culture_values", [])

    with get_cursor() as cur:
        cur.execute("UPDATE positions SET culture_values = %s WHERE slug = %s",
                     (json.dumps(values), slug))

    return {"status": "updated", "count": len(values)}


# ===========================================================================
# CONSENSUS SCORING
# ===========================================================================

def recompute_consensus(position_id: int, candidate_id: int):
    """Recompute evaluation consensus after a scorecard is submitted."""
    with get_cursor() as cur:
        # Get all scorecards for this candidate-position via interviews
        cur.execute("""
            SELECT sc.overall_score, sc.recommendation, sc.interviewer_id,
                   u.display_name as interviewer_name
            FROM interview_scorecards sc
            JOIN interviews i ON i.id = sc.interview_id
            LEFT JOIN users u ON u.id = sc.interviewer_id
            WHERE i.position_id = %s AND i.candidate_id = %s AND sc.overall_score IS NOT NULL
        """, (position_id, candidate_id))
        scorecards = cur.fetchall()

        if not scorecards:
            return

        scores = [float(sc[0]) for sc in scorecards]
        recommendations = [sc[1] for sc in scorecards if sc[1]]

        avg_overall = sum(scores) / len(scores)
        evaluator_count = len(scores)

        # Calculate std deviation
        if len(scores) > 1:
            mean = avg_overall
            variance = sum((s - mean) ** 2 for s in scores) / len(scores)
            std_dev = math.sqrt(variance)
        else:
            std_dev = 0

        # Determine agreement level
        if std_dev < 0.5:
            agreement = "strong_agree"
        elif std_dev < 1.0:
            agreement = "agree"
        elif std_dev < 1.5:
            agreement = "mixed"
        else:
            agreement = "disagree"

        # Lone dissent: one evaluator >1.5 points away from mean
        lone_dissent = False
        if len(scores) >= 3:
            for s in scores:
                if abs(s - avg_overall) > 1.5:
                    lone_dissent = True
                    break

        # Recommendation distribution
        rec_dist = {}
        for rec in recommendations:
            rec_dist[rec] = rec_dist.get(rec, 0) + 1

        # Get per-dimension averages
        cur.execute("""
            SELECT ss.dimension, AVG(ss.score) as avg_score
            FROM scorecard_scores ss
            JOIN interview_scorecards sc ON sc.id = ss.scorecard_id
            JOIN interviews i ON i.id = sc.interview_id
            WHERE i.position_id = %s AND i.candidate_id = %s
            GROUP BY ss.dimension
        """, (position_id, candidate_id))
        dim_avgs = {}
        for row in cur.fetchall():
            dim_avgs[row[0]] = round(float(row[1]), 2)

        # Upsert consensus
        cur.execute("""
            INSERT INTO evaluation_consensus (position_id, candidate_id, avg_overall,
                avg_per_dimension, evaluator_count, agreement_level, lone_dissent_flag,
                recommendation_distribution, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (position_id, candidate_id) DO UPDATE SET
                avg_overall = EXCLUDED.avg_overall,
                avg_per_dimension = EXCLUDED.avg_per_dimension,
                evaluator_count = EXCLUDED.evaluator_count,
                agreement_level = EXCLUDED.agreement_level,
                lone_dissent_flag = EXCLUDED.lone_dissent_flag,
                recommendation_distribution = EXCLUDED.recommendation_distribution,
                updated_at = NOW()
        """, (
            position_id, candidate_id, round(avg_overall, 2),
            json.dumps(dim_avgs), evaluator_count, agreement,
            lone_dissent, json.dumps(rec_dist),
        ))

    logger.info(f"Consensus updated: pos={position_id} cand={candidate_id} avg={avg_overall:.1f} agreement={agreement}")


@router.get("/positions/{slug}/consensus")
async def get_position_consensus(slug: str, request: Request):
    """Get consensus data for all candidates in a position."""
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")

    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM evaluation_consensus WHERE position_id = %s
        """, (position["id"],))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    consensus = {}
    for r in rows:
        consensus[r["candidate_id"]] = r

    return {"consensus": consensus}


# ===========================================================================
# HIRING COMMITTEE VOTES
# ===========================================================================

@router.get("/positions/{slug}/votes")
async def get_position_votes(slug: str, request: Request):
    """Get vote distribution for all candidates in a position."""
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")

    with get_cursor() as cur:
        cur.execute("""
            SELECT i.candidate_id, sc.recommendation, COUNT(*) as cnt
            FROM interview_scorecards sc
            JOIN interviews i ON i.id = sc.interview_id
            WHERE i.position_id = %s AND sc.recommendation IS NOT NULL
            GROUP BY i.candidate_id, sc.recommendation
        """, (position["id"],))
        rows = cur.fetchall()

    votes = {}
    for candidate_id, recommendation, count in rows:
        if candidate_id not in votes:
            votes[candidate_id] = {"strong_hire": 0, "hire": 0, "no_hire": 0, "strong_no_hire": 0}
        if recommendation in votes[candidate_id]:
            votes[candidate_id][recommendation] = count

    return {"votes": votes}


# ===========================================================================
# STACK RANKING
# ===========================================================================

@router.get("/positions/{slug}/stack-rank")
async def get_stack_rank(slug: str, request: Request):
    """Get stack-ranked candidates: composite(60%) + consensus(30%) + flag penalty(10%)."""
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")

    pid = position["id"]

    with get_cursor() as cur:
        # Get candidates with scores
        cur.execute("""
            SELECT pc.candidate_id, c.name, pc.match_score_composite,
                   pc.stage, pc.match_score_culture
            FROM position_candidates pc
            JOIN candidates c ON c.id = pc.candidate_id
            WHERE pc.position_id = %s AND pc.stage != 'rejected'
            ORDER BY pc.match_score_composite DESC NULLS LAST
        """, (pid,))
        candidates = cur.fetchall()

        # Get consensus data
        cur.execute("SELECT candidate_id, avg_overall FROM evaluation_consensus WHERE position_id = %s", (pid,))
        consensus_map = {row[0]: float(row[1]) if row[1] else None for row in cur.fetchall()}

        # Get flag counts
        cur.execute("""
            SELECT candidate_id, flag_type, COUNT(*) FROM candidate_flags
            WHERE position_id = %s GROUP BY candidate_id, flag_type
        """, (pid,))
        flag_counts = {}
        for cid, ftype, cnt in cur.fetchall():
            if cid not in flag_counts:
                flag_counts[cid] = {"red": 0, "amber": 0, "green": 0}
            flag_counts[cid][ftype] = cnt

    # Compute final scores
    rankings = []
    for cid, name, composite, stage, culture in candidates:
        composite = float(composite) if composite else 0
        consensus_avg = consensus_map.get(cid)

        # Consensus contribution (scaled to 0-100: score/5 * 100)
        consensus_score = (consensus_avg / 5.0 * 100) if consensus_avg else composite  # fallback to composite

        # Flag penalty: red=-5 each, amber=-2 each, green=+1 each
        fc = flag_counts.get(cid, {"red": 0, "amber": 0, "green": 0})
        flag_penalty = fc["red"] * 5 + fc["amber"] * 2 - fc["green"] * 1

        # Final: composite(60%) + consensus(30%) + flag adjustment(10% range, capped)
        flag_adj = max(-10, min(5, -flag_penalty))  # cap at -10 to +5
        final_score = composite * 0.6 + consensus_score * 0.3 + (50 + flag_adj) * 0.1

        rankings.append({
            "candidate_id": cid,
            "name": name,
            "composite": composite,
            "consensus_avg": round(consensus_avg, 2) if consensus_avg else None,
            "culture_score": float(culture) if culture else None,
            "flag_counts": fc,
            "flag_penalty": round(flag_penalty, 1),
            "final_score": round(final_score, 1),
            "stage": stage,
        })

    # Sort by final score
    rankings.sort(key=lambda x: x["final_score"], reverse=True)

    # Assign ranks
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    return {"rankings": rankings}


# ===========================================================================
# CALIBRATION REPORT
# ===========================================================================

@router.get("/positions/{slug}/calibration")
async def get_position_calibration(slug: str, request: Request):
    """Get interviewer calibration data for a position."""
    get_current_user(request)
    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")

    with get_cursor() as cur:
        # Per-interviewer stats
        cur.execute("""
            SELECT sc.interviewer_id,
                   COALESCE(u.display_name, 'Unknown') as interviewer_name,
                   AVG(sc.overall_score) as avg_score,
                   STDDEV(sc.overall_score) as std_dev,
                   COUNT(*) as scorecard_count,
                   MIN(sc.overall_score) as min_score,
                   MAX(sc.overall_score) as max_score
            FROM interview_scorecards sc
            JOIN interviews i ON i.id = sc.interview_id
            LEFT JOIN users u ON u.id = sc.interviewer_id
            WHERE i.position_id = %s AND sc.overall_score IS NOT NULL
            GROUP BY sc.interviewer_id, u.display_name
            HAVING COUNT(*) >= 1
            ORDER BY AVG(sc.overall_score) DESC
        """, (position["id"],))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        # Position-wide average for harshness index
        cur.execute("""
            SELECT AVG(sc.overall_score) FROM interview_scorecards sc
            JOIN interviews i ON i.id = sc.interview_id
            WHERE i.position_id = %s AND sc.overall_score IS NOT NULL
        """, (position["id"],))
        position_avg = cur.fetchone()[0]

    interviewers = []
    for r in rows:
        avg = float(r["avg_score"]) if r["avg_score"] else 0
        harshness = round(avg / float(position_avg), 2) if position_avg and float(position_avg) > 0 else 1.0

        interviewers.append({
            "interviewer_id": r["interviewer_id"],
            "interviewer_name": r["interviewer_name"],
            "avg_score": round(avg, 2),
            "std_dev": round(float(r["std_dev"]), 2) if r["std_dev"] else 0,
            "scorecard_count": r["scorecard_count"],
            "min_score": float(r["min_score"]) if r["min_score"] else None,
            "max_score": float(r["max_score"]) if r["max_score"] else None,
            "harshness_index": harshness,
        })

    return {"interviewers": interviewers, "position_avg": round(float(position_avg), 2) if position_avg else None}


@router.get("/calibration")
async def get_org_calibration(request: Request):
    """Get org-wide interviewer calibration data."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT sc.interviewer_id,
                   COALESCE(u.display_name, 'Unknown') as interviewer_name,
                   AVG(sc.overall_score) as avg_score,
                   STDDEV(sc.overall_score) as std_dev,
                   COUNT(*) as scorecard_count
            FROM interview_scorecards sc
            LEFT JOIN users u ON u.id = sc.interviewer_id
            WHERE sc.overall_score IS NOT NULL
            GROUP BY sc.interviewer_id, u.display_name
            HAVING COUNT(*) >= 1
            ORDER BY AVG(sc.overall_score) DESC
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        cur.execute("SELECT AVG(overall_score) FROM interview_scorecards WHERE overall_score IS NOT NULL")
        org_avg = cur.fetchone()[0]

    interviewers = []
    for r in rows:
        avg = float(r["avg_score"]) if r["avg_score"] else 0
        harshness = round(avg / float(org_avg), 2) if org_avg and float(org_avg) > 0 else 1.0
        interviewers.append({
            "interviewer_id": r["interviewer_id"],
            "interviewer_name": r["interviewer_name"],
            "avg_score": round(avg, 2),
            "std_dev": round(float(r["std_dev"]), 2) if r["std_dev"] else 0,
            "scorecard_count": r["scorecard_count"],
            "harshness_index": harshness,
        })

    return {"interviewers": interviewers, "org_avg": round(float(org_avg), 2) if org_avg else None}


@router.get("/flag-distribution")
async def get_flag_distribution(request: Request):
    """Get org-wide flag distribution counts."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT flag_type, category, COUNT(*) as cnt
            FROM candidate_flags
            GROUP BY flag_type, category
            ORDER BY flag_type, cnt DESC
        """)
        rows = cur.fetchall()

    distribution = {"red": {}, "amber": {}, "green": {}}
    totals = {"red": 0, "amber": 0, "green": 0}
    for ftype, category, cnt in rows:
        if ftype in distribution:
            distribution[ftype][category] = cnt
            totals[ftype] += cnt

    return {"distribution": distribution, "totals": totals}
