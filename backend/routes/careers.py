"""Career page routes — public-facing job board + application endpoint."""
from __future__ import annotations

import os
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from backend.core.database import get_cursor, insert_candidate, add_candidate_to_position

logger = logging.getLogger(__name__)
router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data")))
CV_DIR = DATA_DIR / "cvs"
CV_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/positions")
async def list_career_positions():
    """Public endpoint — returns active positions for the careers page."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT slug, title, department, location, employment_type,
                   required_skills, nice_to_have_skills, jd_text, created_at
            FROM positions
            WHERE status = 'active'
            ORDER BY created_at DESC
        """)
        cols = [desc[0] for desc in cur.description]
        positions = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"positions": positions}


@router.post("/apply")
async def apply_to_position(
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    cover_letter: str = Form(""),
    position_slug: str = Form(...),
    file: UploadFile = File(...),
):
    """Public endpoint — submit a job application with CV."""
    # Validate file type
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are accepted")

    # Validate position exists and is active
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, title FROM positions WHERE slug = %s AND status = 'active'",
            (position_slug,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Position not found or no longer active")

    position_id, position_title = row

    # Read and validate file content
    content = await file.read()

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large ({len(content) // 1024 // 1024}MB). Max 10MB.")

    # Validate file content (not just extension)
    if content[:4] == b'%PDF':
        pass  # valid PDF
    elif content[:2] == b'PK':
        pass  # valid DOCX (ZIP-based)
    else:
        raise HTTPException(status_code=400, detail="Invalid file content — only PDF and DOCX accepted")

    # Save CV file
    file_id = str(uuid.uuid4())
    save_path = CV_DIR / f"{file_id}{ext}"
    save_path.write_bytes(content)

    try:
        # Create candidate in central repo
        candidate_id = insert_candidate({
            "name": name,
            "email": email,
            "phone": phone or None,
            "location": None,
            "linkedin_url": None,
            "current_role": None,
            "current_company": None,
            "total_experience_years": None,
            "seniority_level": None,
            "skills_technical": [],
            "skills_soft": [],
            "tools": [],
            "languages": [],
            "experience": "[]",
            "education": "[]",
            "certifications": "[]",
            "projects": "[]",
            "summary_short": cover_letter[:500] if cover_letter else None,
            "summary_detailed": None,
            "raw_text": None,
            "pdf_path": str(save_path),
            "file_type": ext.lstrip("."),
            "file_name": file.filename,
            "page_count": 0,
            "quality_score": 0,
            "tags": ["career_page_applicant"],
            "source": "career_page",
            "status": "active",
            "is_processed": False,
        })

        # Link candidate to position
        add_candidate_to_position(position_id, candidate_id, added_by="career_page")

        # Log activity
        from backend.core.database import log_audit
        try:
            log_audit(
                user_id=0,
                action="career_application",
                resource_type="candidate",
                resource_id=candidate_id,
                details={
                    "position_slug": position_slug,
                    "position_title": position_title,
                    "applicant_name": name,
                    "applicant_email": email,
                },
            )
        except Exception:
            logger.warning("Audit log failed for career application")

        # Create notification for hiring managers
        try:
            from backend.routes.notifications import create_notification
            # Notify all admin/recruiter users
            with get_cursor() as cur:
                cur.execute("SELECT id FROM users WHERE role IN ('admin', 'recruiter') AND is_active = TRUE")
                user_ids = [r[0] for r in cur.fetchall()]
            for uid in user_ids:
                create_notification(
                    user_id=uid,
                    type="new_application",
                    title=f"New application for {position_title}",
                    message=f"{name} applied via career page",
                    link=f"/positions/{position_slug}",
                )
        except Exception:
            logger.warning("Notification creation failed for career application")

        # Trigger background CV processing
        try:
            import asyncio
            from backend.routes.candidates import _process_cv_background
            asyncio.create_task(_process_cv_background(candidate_id, str(save_path), file.filename))
        except Exception:
            logger.warning("Background CV processing trigger failed")

        return {
            "success": True,
            "message": f"Application submitted successfully for {position_title}. We will review your profile and get back to you.",
            "candidate_id": candidate_id,
        }

    except Exception as e:
        logger.error(f"Career application failed: {e}")
        raise HTTPException(status_code=500, detail="Application submission failed. Please try again.")
