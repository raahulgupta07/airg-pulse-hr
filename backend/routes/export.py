"""Export routes — CSV downloads and hiring reports."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse

from backend.core.auth import get_current_user
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()


def generate_csv(rows, headers, filename="export.csv"):
    """Generate a streaming CSV response."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Export all candidates as CSV
# ---------------------------------------------------------------------------
@router.get("/candidates/csv")
async def export_candidates_csv(request: Request):
    """Export all candidates as CSV."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT name, email, current_role, current_company,
                   total_experience_years, skills_technical,
                   quality_score, source, created_at
            FROM candidates
            WHERE status = 'active'
            ORDER BY created_at DESC
        """)
        rows = []
        for row in cur.fetchall():
            name, email, role, company, exp, skills, quality, source, created = row
            skills_str = ", ".join(skills) if isinstance(skills, list) else (skills or "")
            rows.append([
                name or "", email or "", role or "", company or "",
                exp or 0, skills_str, quality or 0, source or "",
                created.isoformat() if created else "",
            ])

    headers = [
        "Name", "Email", "Role", "Company", "Experience (years)",
        "Skills", "Quality Score", "Source", "Created At",
    ]
    return generate_csv(rows, headers, "candidates_export.csv")


# ---------------------------------------------------------------------------
# Export position candidates as CSV
# ---------------------------------------------------------------------------
@router.get("/positions/{slug}/csv")
async def export_position_candidates_csv(slug: str, request: Request):
    """Export candidates for a specific position as CSV."""
    get_current_user(request)

    with get_cursor() as cur:
        # Get position
        cur.execute("SELECT id, title FROM positions WHERE slug = %s", (slug,))
        pos = cur.fetchone()
        if not pos:
            raise HTTPException(status_code=404, detail="Position not found")
        position_id, position_title = pos

        cur.execute("""
            SELECT c.name, pc.match_score_composite, pc.stage,
                   pc.skills_matched, pc.skills_missing
            FROM position_candidates pc
            JOIN candidates c ON c.id = pc.candidate_id
            WHERE pc.position_id = %s
            ORDER BY pc.match_score_composite DESC NULLS LAST
        """, (position_id,))

        rows = []
        for row in cur.fetchall():
            name, score, stage, matched, missing = row
            matched_str = ", ".join(matched) if isinstance(matched, list) else (matched or "")
            missing_str = ", ".join(missing) if isinstance(missing, list) else (missing or "")
            rows.append([
                name or "", round(score or 0, 1), stage or "",
                matched_str, missing_str,
            ])

    headers = ["Name", "Match Score", "Stage", "Skills Matched", "Skills Missing"]
    safe_slug = slug.replace("/", "_")
    return generate_csv(rows, headers, f"position_{safe_slug}_candidates.csv")


# ---------------------------------------------------------------------------
# Generate hiring report for a position
# ---------------------------------------------------------------------------
@router.get("/positions/{slug}/report")
async def export_position_report(slug: str, request: Request):
    """Generate a markdown hiring report for a position."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT id, title, department, location, status, created_at,
                   required_skills, nice_to_have_skills
            FROM positions WHERE slug = %s
        """, (slug,))
        pos = cur.fetchone()
        if not pos:
            raise HTTPException(status_code=404, detail="Position not found")

        pos_id, title, dept, loc, status, created, req_skills, nice_skills = pos

        # Pipeline counts
        cur.execute("""
            SELECT stage, COUNT(*) FROM position_candidates
            WHERE position_id = %s GROUP BY stage ORDER BY stage
        """, (pos_id,))
        pipeline = {row[0]: row[1] for row in cur.fetchall()}

        # Total candidates
        cur.execute(
            "SELECT COUNT(*) FROM position_candidates WHERE position_id = %s",
            (pos_id,),
        )
        total = cur.fetchone()[0]

        # Top candidates
        cur.execute("""
            SELECT c.name, c.current_role, c.current_company,
                   pc.match_score_composite, pc.stage
            FROM position_candidates pc
            JOIN candidates c ON c.id = pc.candidate_id
            WHERE pc.position_id = %s
            ORDER BY pc.match_score_composite DESC NULLS LAST
            LIMIT 10
        """, (pos_id,))
        cols = [desc[0] for desc in cur.description]
        top_candidates = [dict(zip(cols, row)) for row in cur.fetchall()]

        # Avg score
        cur.execute("""
            SELECT ROUND(AVG(match_score_composite)::numeric, 1)
            FROM position_candidates WHERE position_id = %s
        """, (pos_id,))
        avg_score = cur.fetchone()[0]

    # Build report
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = f"""# Hiring Report: {title}

**Generated:** {now}
**Department:** {dept or 'N/A'}
**Location:** {loc or 'N/A'}
**Status:** {status}
**Open Since:** {created.strftime('%Y-%m-%d') if created else 'N/A'}

---

## Pipeline Summary

| Stage | Count |
|-------|-------|
"""
    stages_order = ["uploaded", "screened", "shortlisted", "interview_scheduled",
                    "interviewed", "offered", "hired"]
    for s in stages_order:
        count = pipeline.get(s, 0)
        if count > 0:
            report += f"| {s.replace('_', ' ').title()} | {count} |\n"

    report += f"\n**Total Candidates:** {total}\n"
    report += f"**Average Match Score:** {avg_score or 'N/A'}%\n"

    # Required skills
    if req_skills:
        skills_list = req_skills if isinstance(req_skills, list) else []
        report += f"\n**Required Skills:** {', '.join(skills_list)}\n"

    # Top candidates
    report += "\n---\n\n## Top Candidates\n\n"
    report += "| Rank | Name | Role | Company | Match Score | Stage |\n"
    report += "|------|------|------|---------|-------------|-------|\n"
    for i, c in enumerate(top_candidates, 1):
        report += (
            f"| {i} | {c['name'] or 'N/A'} | {c['current_role'] or 'N/A'} | "
            f"{c['current_company'] or 'N/A'} | "
            f"{round(c['match_score_composite'] or 0, 1)}% | {c['stage'] or 'N/A'} |\n"
        )

    report += "\n---\n\n*Report generated by HIRE AI Platform*\n"

    return PlainTextResponse(
        content=report,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=hiring_report_{slug}.md"},
    )


# ---------------------------------------------------------------------------
# Export analytics data as CSV
# ---------------------------------------------------------------------------
@router.get("/analytics/csv")
async def export_analytics_csv(request: Request):
    """Export analytics overview data as CSV."""
    get_current_user(request)

    with get_cursor() as cur:
        # Positions summary with metrics
        cur.execute("""
            SELECT
                p.title, p.department, p.status, p.location,
                COUNT(pc.id) AS candidate_count,
                ROUND(AVG(pc.match_score_composite)::numeric, 1) AS avg_match,
                COUNT(DISTINCT i.id) AS interview_count,
                EXTRACT(DAY FROM NOW() - p.created_at)::int AS days_open,
                SUM(CASE WHEN pc.stage = 'hired' THEN 1 ELSE 0 END) AS hires
            FROM positions p
            LEFT JOIN position_candidates pc ON pc.position_id = p.id
            LEFT JOIN interviews i ON i.position_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """)

        rows = []
        for row in cur.fetchall():
            title, dept, status, loc, cands, avg_m, intv, days, hires = row
            rows.append([
                title or "", dept or "", status or "", loc or "",
                cands or 0, avg_m or 0, intv or 0, days or 0, hires or 0,
            ])

    headers = [
        "Position", "Department", "Status", "Location",
        "Candidates", "Avg Match Score", "Interviews", "Days Open", "Hires",
    ]
    return generate_csv(rows, headers, "analytics_export.csv")


# ---------------------------------------------------------------------------
# Comprehensive hiring report (10 sections, Markdown)
# ---------------------------------------------------------------------------
@router.get("/positions/{slug}/hiring-report")
async def hiring_report(slug: str, request: Request):
    get_current_user(request)
    from backend.core.database import get_position, get_position_candidates, get_pipeline_counts

    position = get_position(slug)
    if not position:
        raise HTTPException(404, "Position not found")

    candidates = get_position_candidates(position["id"], limit=50)
    pipeline = get_pipeline_counts(position["id"])

    # Get interviews
    with get_cursor() as cur:
        cur.execute("""
            SELECT i.*, c.name as candidate_name
            FROM interviews i
            JOIN candidates c ON c.id = i.candidate_id
            WHERE i.position_id = %s
            ORDER BY i.scheduled_at
        """, (position["id"],))
        cols = [d[0] for d in cur.description]
        interviews = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Get notes
    with get_cursor() as cur:
        cur.execute("""
            SELECT n.*, c.name as candidate_name, u.display_name as author
            FROM candidate_notes n
            JOIN candidates c ON c.id = n.candidate_id
            LEFT JOIN users u ON u.id = n.user_id
            WHERE n.position_id = %s
            ORDER BY n.created_at DESC
        """, (position["id"],))
        cols = [d[0] for d in cur.description]
        notes = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Get offers
    with get_cursor() as cur:
        cur.execute("""
            SELECT o.*, c.name as candidate_name
            FROM offers o
            JOIN candidates c ON c.id = o.candidate_id
            WHERE o.position_id = %s
            ORDER BY o.created_at DESC
        """, (position["id"],))
        cols = [d[0] for d in cur.description]
        offers_data = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Build the report
    now = datetime.now()
    created = position.get("created_at")
    days_open = (now - created).days if created else 0
    total = len(candidates)
    active = [c for c in candidates if c.get("stage") != "rejected"]
    req_skills = position.get("required_skills") or []

    report = f"""# HIRING REPORT
## {position['title']} — {position.get('department', 'N/A')} — {position.get('location', 'N/A')}
Generated: {now.strftime('%B %d, %Y')}

---

## 1. EXECUTIVE SUMMARY

| Metric | Value |
|---|---|
| Position opened | {str(created)[:10] if created else 'N/A'} |
| Days open | {days_open} |
| Total applicants | {total} |
| Qualified (>50%) | {len([c for c in candidates if (c.get('match_score_composite') or 0) >= 50])} |
| Shortlisted | {pipeline.get('shortlisted', 0)} |
| Interviewed | {pipeline.get('interviewed', 0) + pipeline.get('interview_scheduled', 0)} |
| Offers sent | {len(offers_data)} |
| Average match | {round(sum(c.get('match_score_composite', 0) for c in candidates) / max(total, 1), 1)}% |

"""

    # Top recommendation
    if candidates:
        top = candidates[0]
        report += f"**RECOMMENDATION:** {top.get('name', '?')} ({round(top.get('match_score_composite', 0))}% match)"
        if top.get('stage') == 'offered':
            report += " — offer sent, awaiting response.\n"
        else:
            report += f" — currently {top.get('stage', '?')}.\n"
        if len(candidates) > 1:
            backup = candidates[1]
            report += f"**BACKUP:** {backup.get('name', '?')} ({round(backup.get('match_score_composite', 0))}%)"
            if backup.get('skills_missing'):
                report += f" — gaps: {', '.join(backup['skills_missing'][:3])}\n"
            else:
                report += "\n"

    # Section 2: Requirements
    report += f"""
---

## 2. POSITION REQUIREMENTS

**Required Skills:** {', '.join(req_skills or ['None specified'])}
**Nice to Have:** {', '.join(position.get('nice_to_have_skills', []) or ['None'])}
**Min Experience:** {position.get('min_experience_years', 0)} years
**Education:** {position.get('education_level', 'Not specified')}

**Scoring Weights:**
- Skills: {position.get('weight_skills', 40)}%
- Experience: {position.get('weight_experience', 25)}%
- Education: {position.get('weight_education', 10)}%
- Certifications: {position.get('weight_certifications', 10)}%
- Industry: {position.get('weight_industry', 15)}%

"""

    # Section 3: Candidate Ranking
    report += "---\n\n## 3. CANDIDATE RANKING\n\n"
    for i, c in enumerate(candidates):
        score = round(c.get('match_score_composite', 0))
        bar = '\u2588' * (score // 5) + '\u2591' * (20 - score // 5)
        stage = (c.get('stage') or '?').upper()
        report += f"### #{i+1} {c.get('name', '?')} — {score}% {bar}\n"
        report += f"**{c.get('current_role', 'N/A')}** \u00b7 {c.get('total_experience_years', 0)}yr \u00b7 **{stage}**\n\n"
        report += f"| Dimension | Score |\n|---|---|\n"
        report += f"| Skills | {round(c.get('match_score_skills', 0))}% |\n"
        report += f"| Experience | {round(c.get('match_score_experience', 0))}% |\n"
        report += f"| Education | {round(c.get('match_score_education', 0))}% |\n"
        report += f"| Industry | {round(c.get('match_score_industry', 0))}% |\n\n"
        if c.get('skills_matched'):
            report += f"**Matched:** {', '.join(c['skills_matched'])}\n"
        if c.get('skills_missing'):
            report += f"**Missing:** {', '.join(c['skills_missing'])}\n"
        report += "\n"

    # Section 4: Skills Coverage
    if req_skills and active:
        report += "---\n\n## 4. SKILLS COVERAGE ANALYSIS\n\n"
        report += "| Skill | " + " | ".join(c.get('name', '?').split(' ')[0] for c in active[:5]) + " | Coverage |\n"
        report += "|---" * (len(active[:5]) + 2) + "|\n"
        for skill in req_skills:
            row = f"| {skill} |"
            matched = 0
            for c in active[:5]:
                has = skill.lower() in [s.lower() for s in (c.get('skills_matched') or [])]
                row += " \u2713 |" if has else " \u2717 |"
                if has:
                    matched += 1
            pct = round(matched / len(active[:5]) * 100) if active[:5] else 0
            row += f" {matched}/{len(active[:5])} ({pct}%) |"
            report += row + "\n"

        gaps = [s for s in req_skills if not any(s.lower() in [x.lower() for x in (c.get('skills_matched') or [])] for c in active)]
        if gaps:
            report += f"\n**GAP ALERT:** No active candidate has: {', '.join(gaps)}\n"
        report += "\n"

    # Section 5: Pipeline
    report += "---\n\n## 5. PIPELINE ANALYTICS\n\n"
    stages_order = ['uploaded', 'screened', 'shortlisted', 'interview_scheduled', 'interviewed', 'offered', 'hired', 'rejected']
    for stage in stages_order:
        count = pipeline.get(stage, 0)
        if count > 0:
            pct = round(count / max(total, 1) * 100)
            report += f"- **{stage.replace('_', ' ').title()}:** {count} ({pct}%)\n"
    report += f"\n**Overall conversion:** {round((pipeline.get('offered', 0) + pipeline.get('hired', 0)) / max(total, 1) * 100)}% (offers from applicants)\n\n"

    # Section 6: Interviews
    report += "---\n\n## 6. INTERVIEW SUMMARY\n\n"
    if interviews:
        for iv in interviews:
            scheduled = iv.get('scheduled_at')
            date_str = str(scheduled)[:10] if scheduled else 'TBD'
            report += f"- **{iv.get('candidate_name', '?')}** — {iv.get('interview_type', '?')} — {date_str} — **{(iv.get('status') or '?').upper()}**\n"
            if iv.get('notes'):
                report += f"  Feedback: {iv['notes']}\n"
    else:
        report += "No interviews recorded.\n"
    report += "\n"

    # Section 7: Offers
    report += "---\n\n## 7. COMPENSATION & OFFERS\n\n"
    if offers_data:
        for o in offers_data:
            report += f"### {o.get('candidate_name', '?')}\n"
            report += f"- Salary: {o.get('salary_currency', 'USD')} {int(o.get('salary_amount', 0)):,} / {o.get('salary_period', 'annual')}\n"
            if o.get('equity'):
                report += f"- Equity: {o['equity']}\n"
            if o.get('bonus'):
                report += f"- Bonus: {o['bonus']}\n"
            if o.get('start_date'):
                report += f"- Start: {str(o['start_date'])[:10]}\n"
            if o.get('benefits'):
                report += f"- Benefits: {o['benefits']}\n"
            report += f"- Status: **{(o.get('status') or '?').upper()}**\n\n"
    else:
        report += "No offers yet.\n\n"

    # Section 8: Notes
    report += "---\n\n## 8. TEAM NOTES & FEEDBACK\n\n"
    if notes:
        for n in notes:
            report += f"- **{n.get('candidate_name', '?')}** ({n.get('note_type', 'note')}): {n.get('content', '')[:200]}\n"
            report += f"  — {n.get('author', 'Unknown')}, {str(n.get('created_at', ''))[:10]}\n\n"
    else:
        report += "No notes recorded.\n\n"

    # Section 9: Risk Assessment
    report += "---\n\n## 9. RISK ASSESSMENT\n\n"
    risks = []
    if len(active) < 3:
        risks.append("\u26a0 Small candidate pool — consider sourcing more candidates")
    single_skill = [s for s in req_skills if sum(1 for c in active if s.lower() in [x.lower() for x in (c.get('skills_matched') or [])]) <= 1]
    if single_skill:
        risks.append(f"\u26a0 Single point of failure: {', '.join(single_skill[:3])} covered by \u22641 candidate")
    if not offers_data:
        risks.append("\u26a0 No offers sent yet")
    if pipeline.get('hired', 0) == 0:
        risks.append("\u26a0 No accepted hire yet")
    if days_open > 30:
        risks.append(f"\u26a0 Position open for {days_open} days — consider expanding search")
    if not risks:
        risks.append("\u2713 No major risks identified")
    for r in risks:
        report += f"- {r}\n"
    report += "\n"

    # Section 10: Actions
    report += "---\n\n## 10. RECOMMENDED ACTIONS\n\n"
    actions = []
    pending_offers = [o for o in offers_data if o.get('status') == 'sent']
    if pending_offers:
        for o in pending_offers:
            actions.append(f"Follow up with {o.get('candidate_name', '?')} on offer response")
    scheduled = [iv for iv in interviews if iv.get('status') == 'scheduled']
    if scheduled:
        for iv in scheduled:
            actions.append(f"Complete {iv.get('candidate_name', '?')} {iv.get('interview_type', '')} interview")
    shortlisted_no_interview = [c for c in candidates if c.get('stage') == 'shortlisted']
    for c in shortlisted_no_interview:
        actions.append(f"Schedule interview for {c.get('name', '?')} (shortlisted, {round(c.get('match_score_composite', 0))}% match)")
    if not actions:
        actions.append("Continue monitoring pipeline")
    for i, a in enumerate(actions):
        report += f"{i+1}. {a}\n"

    report += f"\n---\n\n*Generated by HIRE \u00b7 {now.strftime('%B %d, %Y %H:%M')}*\n"

    return {"report": report, "position": position["title"], "generated_at": now.isoformat()}
