"""CV Pipeline — 12-step processing pipeline for uploaded CVs (with per-step trace)."""
from __future__ import annotations

import os
import glob
import json
import asyncio
import logging
import time
import uuid
from pathlib import Path

from backend.core.cv_parser import (
    classify_file, extract_pdf, extract_docx,
    extract_image_ocr, extract_scanned_pdf, generate_screenshots,
    verify_critical_fields,
)
from backend.core.cv_extractor import (
    extract_structured_data, enrich_candidate,
    generate_qa_pairs, compute_quality_score,
)
from backend.core.config import (
    embed_text, CHAT_MODEL, LITE_MODEL, EMBEDDING_MODELS,
)
from backend.core.database import (
    get_cursor, insert_embedding, insert_qa_pair,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data")))
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Pricing (copied from scripts/vision_bench.py PRICES, plus embeddings)
# ---------------------------------------------------------------------------
PRICES = {
    "google/gemini-3-flash-preview":         (0.30, 2.50),
    "google/gemini-3.1-flash-lite-preview":  (0.10, 0.40),
    "google/gemini-3-pro-preview":           (1.25, 10.00),
    "google/gemini-3.1-pro-preview":         (1.25, 10.00),
    "openai/gpt-5.4-mini":                   (0.15, 0.60),
    "openai/gpt-5.4":                        (1.25, 10.00),
    "anthropic/claude-haiku-4.5":            (0.80, 4.00),
    "anthropic/claude-sonnet-4.6":           (3.00, 15.00),
    "anthropic/claude-opus-4.7":             (15.00, 75.00),
    "anthropic/claude-3.7-sonnet":           (3.00, 15.00),
    "mistralai/pixtral-large-latest":        (2.00, 6.00),
    "mistralai/pixtral-large-2411":          (2.00, 6.00),
    # Embedding (input only, output 0)
    "google/gemini-embedding-001":     (0.025, 0.0),
    "openai/text-embedding-3-large":         (0.13, 0.0),
    "openai/text-embedding-3-small":         (0.02, 0.0),
}


def _calc_cost(model: str | None, in_tok: int | None, out_tok: int | None) -> float | None:
    if not model or model not in PRICES:
        return None
    pin, pout = PRICES[model]
    in_ = in_tok or 0
    out_ = out_tok or 0
    return round((in_ * pin + out_ * pout) / 1_000_000.0, 6)


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------
PIPELINE_TRACE_MAX_PER_CANDIDATE = 50


def _trace_prune(cur, candidate_id: int, keep: int = PIPELINE_TRACE_MAX_PER_CANDIDATE) -> None:
    """Cap pipeline_trace rows per candidate to the most recent `keep` entries."""
    try:
        cur.execute("""
            DELETE FROM pipeline_trace
             WHERE candidate_id = %s
               AND id NOT IN (
                 SELECT id FROM pipeline_trace
                  WHERE candidate_id = %s
                  ORDER BY started_at DESC NULLS LAST, id DESC
                  LIMIT %s
               )
        """, (candidate_id, candidate_id, keep))
    except Exception as e:
        logger.debug(f"trace_prune failed (candidate={candidate_id}): {e}")


def _trace_start(candidate_id: int, run_id: str, ingest_id: int | None,
                 step_order: int, step_name: str, model: str | None = None,
                 details: dict | None = None) -> int | None:
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO pipeline_trace
                  (candidate_id, ingest_id, run_id, step_order, step_name, model, status, details, started_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'running', %s, NOW())
                RETURNING id
            """, (candidate_id, ingest_id, run_id, step_order, step_name, model,
                  json.dumps(details) if details else None))
            new_id = cur.fetchone()[0]
            # Cap retained trace rows per candidate (keep last 50)
            _trace_prune(cur, candidate_id)
            return new_id
    except Exception as e:
        logger.warning(f"trace_start failed for {step_name}: {e}")
        return None


def _trace_finish(trace_id: int | None, status: str = "done",
                  latency_ms: int | None = None,
                  model: str | None = None,
                  input_tokens: int | None = None,
                  output_tokens: int | None = None,
                  cost_usd: float | None = None,
                  details: dict | None = None,
                  error_msg: str | None = None):
    if not trace_id:
        return
    try:
        if cost_usd is None and model:
            cost_usd = _calc_cost(model, input_tokens, output_tokens)
        # merge model update if provided
        with get_cursor() as cur:
            cur.execute("""
                UPDATE pipeline_trace SET
                    status = %s,
                    latency_ms = %s,
                    model = COALESCE(%s, model),
                    input_tokens = %s,
                    output_tokens = %s,
                    cost_usd = %s,
                    details = COALESCE(%s::jsonb, details),
                    error_msg = %s,
                    finished_at = NOW()
                WHERE id = %s
            """, (status, latency_ms, model, input_tokens, output_tokens,
                  cost_usd,
                  json.dumps(details) if details else None,
                  error_msg, trace_id))
    except Exception as e:
        logger.warning(f"trace_finish failed: {e}")


def _est_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


VISION_VERIFIER_MODEL = os.getenv("VISION_VERIFIER_MODEL", "anthropic/claude-opus-4.7")
EMBED_MODEL = EMBEDDING_MODELS[0] if EMBEDDING_MODELS else "google/gemini-embedding-001"


async def process_cv(candidate_id: int, file_path: str, ingest_id: int | None = None,
                     run_id: str | None = None) -> dict:
    """
    Run the full 12-step CV processing pipeline.

    Steps:
      1. CLASSIFY     — Detect file type (PDF/DOCX/Image)
      2. EXTRACT      — Extract raw text
      2.5 VERIFY      — Vision-verify critical fields (handwritten only)
      3. SCREENSHOTS  — Generate page images
      4. STRUCTURE    — LLM extracts structured fields
      5. ENRICH       — Fill gaps
      6. SAVE         — Store structured data
      7. KNOWLEDGE    — Generate Q&A pairs
      8. HYPE_EMBED   — Embed Q&A questions
      9. CONTEXT_EMBED — Embed full CV with contextual headers
     10. QUALITY      — Score completeness
     11. TAG          — Auto-tag
     12. AUTO_MATCH   — Match to open positions
    """
    start = time.time()
    steps_done = []
    run_id = run_id or str(uuid.uuid4())

    # Pipeline Agent heartbeat
    try:
        from backend.agents.registry import heartbeat as _hb_pipe, cycle_done as _cd_pipe
        _hb_pipe("pipeline", status="running", action=f"processing CV #{candidate_id}")
    except Exception:
        _hb_pipe = _cd_pipe = lambda *a, **kw: None  # noqa

    # Cleanup old temp files (older than 1 hour)
    for old_file in glob.glob("/tmp/hire_page_*"):
        try:
            if os.path.getmtime(old_file) < time.time() - 3600:
                os.remove(old_file)
        except Exception:
            pass

    raw_text = ""
    page_count = 0
    result = {}
    enriched: dict = {}
    qa_pairs: list = []
    quality = 0
    structured: dict = {}
    verified_critical: dict = {}

    try:
        # ── Step 1: CLASSIFY ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 1, "CLASSIFY", model=None)
        t0 = time.time()
        try:
            file_type = classify_file(file_path)
            steps_done.append(("classify", file_type))
            logger.info(f"[CV {candidate_id}] Step 1 CLASSIFY: {file_type}")
            if file_type == "unknown":
                _trace_finish(t_id, status="error",
                              latency_ms=int((time.time()-t0)*1000),
                              error_msg=f"Unsupported file type: {Path(file_path).suffix}")
                raise ValueError(f"Unsupported file type: {Path(file_path).suffix}")
            _trace_finish(t_id, status="done",
                          latency_ms=int((time.time()-t0)*1000),
                          details={"file_type": file_type})
        except Exception as e:
            if t_id:
                _trace_finish(t_id, status="error",
                              latency_ms=int((time.time()-t0)*1000),
                              error_msg=str(e))
            raise

        # ── Step 2: EXTRACT ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 2, "EXTRACT")
        t0 = time.time()
        extract_model = None
        try:
            if file_type == "pdf":
                result = extract_pdf(file_path)
                if result.get("is_scanned"):
                    logger.info(f"[CV {candidate_id}] Scanned PDF detected, using OCR")
                    result = extract_scanned_pdf(file_path)
            elif file_type == "docx":
                result = extract_docx(file_path)
            elif file_type == "image":
                result = extract_image_ocr(file_path)
            elif file_type == "txt":
                # Plain-text CV: read directly, no OCR/extraction needed
                try:
                    with open(file_path, "r", encoding="utf-8") as _fh:
                        _content = _fh.read()
                except UnicodeDecodeError:
                    with open(file_path, "r", encoding="latin-1") as _fh:
                        _content = _fh.read()
                result = {
                    "text": _content,
                    "pages": [_content],
                    "page_count": 1,
                    "is_scanned": False,
                    "extraction_method": "plain-text",
                }
            else:
                result = {"text": "", "pages": [], "page_count": 0, "is_scanned": False}

            raw_text = result.get("text", "")
            page_count = result.get("page_count", 0)
            method = result.get("extraction_method") or result.get("method") or ""
            if "vision" in method.lower():
                extract_model = os.getenv("CHAT_MODEL", CHAT_MODEL)
            elif "paddle" in method.lower():
                extract_model = "paddleocr"
            elif "tesseract" in method.lower():
                extract_model = "tesseract"
            elif "pymupdf" in method.lower() or file_type == "pdf":
                extract_model = "pymupdf"
            elif file_type == "docx":
                extract_model = "python-docx"

            steps_done.append(("extract", f"{len(raw_text)} chars, {page_count} pages"))
            logger.info(f"[CV {candidate_id}] Step 2 EXTRACT: {len(raw_text)} chars [{method}]")

            details = {
                "extraction_method": method,
                "chars": len(raw_text),
                "page_count": page_count,
                "has_handwritten": result.get("has_handwritten", False),
            }
            if len(raw_text) < 50:
                _trace_finish(t_id, status="error", model=extract_model,
                              latency_ms=int((time.time()-t0)*1000),
                              details=details,
                              error_msg="Insufficient text extracted from CV")
                raise ValueError("Insufficient text extracted from CV")

            # estimate tokens for vision LLM only
            in_tok = out_tok = None
            if extract_model and extract_model in PRICES:
                out_tok = _est_tokens(raw_text)
                in_tok = 1500  # rough vision input
                details["token_estimate"] = True
            _trace_finish(t_id, status="done", model=extract_model,
                          latency_ms=int((time.time()-t0)*1000),
                          input_tokens=in_tok, output_tokens=out_tok,
                          details=details)
        except Exception as e:
            if t_id:
                _trace_finish(t_id, status="error", model=extract_model,
                              latency_ms=int((time.time()-t0)*1000),
                              error_msg=str(e))
            raise

        # ── Step 2.5: VERIFY ──
        t_id_v = _trace_start(candidate_id, run_id, ingest_id, 25, "VERIFY",
                              model=VISION_VERIFIER_MODEL)
        t0 = time.time()
        try:
            should_verify = (
                os.getenv("ENABLE_VISION_VERIFIER", "false").lower() == "true"
                and (
                    file_type == "image"
                    or result.get("has_handwritten") is True
                    or str(result.get("extraction_method", "")).startswith("vision_llm")
                )
            )
            if should_verify:
                try:
                    verified_critical = verify_critical_fields(file_path)
                    overrides = list(verified_critical.keys()) if verified_critical else []
                    if verified_critical:
                        logger.info(f"[CV {candidate_id}] Step 2.5 VERIFY: {overrides}")
                    in_tok = 1500
                    out_tok = _est_tokens(json.dumps(verified_critical or {}))
                    _trace_finish(t_id_v, status="done", model=VISION_VERIFIER_MODEL,
                                  latency_ms=int((time.time()-t0)*1000),
                                  input_tokens=in_tok, output_tokens=out_tok,
                                  details={"fields_overridden": overrides, "token_estimate": True})
                except Exception as e:
                    logger.warning(f"[CV {candidate_id}] Verifier failed: {e}")
                    _trace_finish(t_id_v, status="error", model=VISION_VERIFIER_MODEL,
                                  latency_ms=int((time.time()-t0)*1000),
                                  error_msg=str(e))
            else:
                _trace_finish(t_id_v, status="skipped",
                              latency_ms=int((time.time()-t0)*1000),
                              details={"reason": "not handwritten / verifier disabled"})
        except Exception as e:
            _trace_finish(t_id_v, status="error",
                          latency_ms=int((time.time()-t0)*1000),
                          error_msg=str(e))

        # ── Step 3: SCREENSHOTS ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 3, "SCREENSHOTS", model="pymupdf")
        t0 = time.time()
        try:
            screenshots = generate_screenshots(file_path, candidate_id, str(SCREENSHOT_DIR))
            steps_done.append(("screenshots", f"{len(screenshots)} images"))
            for ss in screenshots:
                with get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO candidate_screenshots (candidate_id, page, img_index, path, width, height)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (candidate_id, ss["page"], ss["img_index"], ss["path"], ss["width"], ss["height"]))
            logger.info(f"[CV {candidate_id}] Step 3 SCREENSHOTS: {len(screenshots)}")
            _trace_finish(t_id, status="done", latency_ms=int((time.time()-t0)*1000),
                          details={"n_screenshots": len(screenshots)})
        except Exception as e:
            _trace_finish(t_id, status="error",
                          latency_ms=int((time.time()-t0)*1000),
                          error_msg=str(e))
            raise

        # ── Step 4: STRUCTURE ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 4, "STRUCTURE", model=CHAT_MODEL)
        t0 = time.time()
        try:
            # Run in thread to avoid blocking event loop — lets 8 pipelines run truly in parallel
            structured = await asyncio.to_thread(extract_structured_data, raw_text)
            if verified_critical:
                for src_key, dst_key in [("name", "name"), ("phone", "phone"), ("email", "email")]:
                    v = verified_critical.get(src_key)
                    if v and (not structured.get(dst_key) or len(str(v)) > 2):
                        structured[dst_key] = v
                # Demographic / form-only fields — copy through whenever the verifier saw them
                for demo_key in ("national_id", "dob", "gender", "marital_status",
                                 "nationality", "religion", "height", "weight", "father_name"):
                    v = verified_critical.get(demo_key)
                    if v:
                        structured[demo_key] = v
            steps_done.append(("structure", f"name={structured.get('name')}"))
            logger.info(f"[CV {candidate_id}] Step 4 STRUCTURE: {structured.get('name')}")
            in_tok = _est_tokens(raw_text)
            out_tok = _est_tokens(json.dumps(structured))
            _trace_finish(t_id, status="done", model=CHAT_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          input_tokens=in_tok, output_tokens=out_tok,
                          details={"name": structured.get("name"),
                                   "skills": len(structured.get("skills_technical", [])),
                                   "token_estimate": True})
        except Exception as e:
            _trace_finish(t_id, status="error", model=CHAT_MODEL,
                          latency_ms=int((time.time()-t0)*1000), error_msg=str(e))
            raise

        # ── Step 5: ENRICH ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 5, "ENRICH", model=LITE_MODEL)
        t0 = time.time()
        try:
            enriched = await asyncio.to_thread(enrich_candidate, structured)
            steps_done.append(("enrich", f"seniority={enriched.get('seniority_level')}"))
            in_tok = _est_tokens(json.dumps(structured))
            out_tok = _est_tokens(json.dumps(enriched))
            _trace_finish(t_id, status="done", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          input_tokens=in_tok, output_tokens=out_tok,
                          details={"seniority": enriched.get("seniority_level"),
                                   "tags": enriched.get("tags"),
                                   "token_estimate": True})
        except Exception as e:
            _trace_finish(t_id, status="error", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000), error_msg=str(e))
            raise

        # ── Step 6: SAVE ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 6, "SAVE")
        t0 = time.time()
        try:
            with get_cursor() as cur:
                cur.execute("""
                    UPDATE candidates SET
                        name = %s, email = %s, phone = %s, location = %s, linkedin_url = %s,
                        "current_role" = %s, "current_company" = %s,
                        total_experience_years = %s, seniority_level = %s,
                        skills_technical = %s, skills_soft = %s, tools = %s, languages = %s,
                        experience = %s, education = %s, certifications = %s, projects = %s,
                        summary_short = %s, summary_detailed = %s,
                        raw_text = %s, page_count = %s,
                        dob            = COALESCE(%s, dob),
                        national_id    = COALESCE(%s, national_id),
                        gender         = COALESCE(%s, gender),
                        marital_status = COALESCE(%s, marital_status),
                        nationality    = COALESCE(%s, nationality),
                        religion       = COALESCE(%s, religion),
                        height         = COALESCE(%s, height),
                        weight         = COALESCE(%s, weight),
                        father_name    = COALESCE(%s, father_name),
                        is_processed = TRUE, processing_error = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                """, (
                    enriched.get("name") or "Unknown",
                    enriched.get("email"),
                    enriched.get("phone"),
                    enriched.get("location"),
                    enriched.get("linkedin_url"),
                    enriched.get("current_role"),
                    enriched.get("current_company"),
                    enriched.get("total_experience_years"),
                    enriched.get("seniority_level"),
                    enriched.get("skills_technical", []),
                    enriched.get("skills_soft", []),
                    enriched.get("tools", []),
                    enriched.get("languages", []),
                    json.dumps(enriched.get("experience", [])),
                    json.dumps(enriched.get("education", [])),
                    json.dumps(enriched.get("certifications", [])),
                    json.dumps(enriched.get("projects", [])),
                    enriched.get("summary_short"),
                    enriched.get("summary_detailed"),
                    raw_text,
                    page_count,
                    enriched.get("dob"),
                    enriched.get("national_id"),
                    enriched.get("gender"),
                    enriched.get("marital_status"),
                    enriched.get("nationality"),
                    enriched.get("religion"),
                    enriched.get("height"),
                    enriched.get("weight"),
                    enriched.get("father_name"),
                    candidate_id,
                ))
            steps_done.append(("save", "OK"))
            _trace_finish(t_id, status="done", latency_ms=int((time.time()-t0)*1000))
        except Exception as e:
            _trace_finish(t_id, status="error",
                          latency_ms=int((time.time()-t0)*1000), error_msg=str(e))
            raise

        # ── Step 7: KNOWLEDGE ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 7, "KNOWLEDGE", model=LITE_MODEL)
        t0 = time.time()
        try:
            qa_pairs = await asyncio.to_thread(generate_qa_pairs, raw_text, enriched.get("name", "candidate"))
            steps_done.append(("knowledge", f"{len(qa_pairs)} Q&A pairs"))
            in_tok = _est_tokens(raw_text)
            out_tok = _est_tokens(json.dumps(qa_pairs))
            _trace_finish(t_id, status="done", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          input_tokens=in_tok, output_tokens=out_tok,
                          details={"pairs": len(qa_pairs), "token_estimate": True})
        except Exception as e:
            _trace_finish(t_id, status="error", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000), error_msg=str(e))
            raise

        # ── Step 8: HYPE_EMBED ── (parallel embeddings for all QA pairs)
        t_id = _trace_start(candidate_id, run_id, ingest_id, 8, "HYPE_EMBED", model=EMBED_MODEL)
        t0 = time.time()
        try:
            embedded_qa = 0
            embed_chars = 0
            # Fan out all QA embeddings concurrently — capped by LLM_GATE inside embed_text
            qa_embeds = await asyncio.gather(*[embed_text(qa["question"]) for qa in qa_pairs], return_exceptions=True)
            for qa, q_embedding in zip(qa_pairs, qa_embeds):
                if isinstance(q_embedding, Exception):
                    continue
                if q_embedding:
                    insert_qa_pair(candidate_id, qa["question"], qa["answer"], q_embedding)
                    embedded_qa += 1
                    embed_chars += len(qa["question"])
            steps_done.append(("hype_embed", f"{embedded_qa} embedded"))
            in_tok = _est_tokens(" " * embed_chars)
            _trace_finish(t_id, status="done", model=EMBED_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          input_tokens=in_tok, output_tokens=0,
                          details={"n_chunks": embedded_qa, "token_estimate": True})
        except Exception as e:
            _trace_finish(t_id, status="error", model=EMBED_MODEL,
                          latency_ms=int((time.time()-t0)*1000), error_msg=str(e))
            raise

        # ── Step 9: CONTEXT_EMBED ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 9, "CONTEXT_EMBED", model=EMBED_MODEL)
        t0 = time.time()
        try:
            header = (
                f"Candidate: {enriched.get('name', 'Unknown')} | "
                f"Role: {enriched.get('current_role', 'N/A')} | "
                f"Experience: {enriched.get('total_experience_years', 0)}yr | "
                f"Skills: {', '.join(enriched.get('skills_technical', [])[:8])}"
            )
            contextual_text = f"{header}\n\n{raw_text[:6000]}"
            skills_text = (
                f"Skills and expertise of {enriched.get('name', 'candidate')}: "
                f"Technical: {', '.join(enriched.get('skills_technical', []))}. "
                f"Tools: {', '.join(enriched.get('tools', []))}. "
                f"Soft skills: {', '.join(enriched.get('skills_soft', []))}."
            )
            exp_texts = []
            for exp in enriched.get("experience", [])[:5]:
                if isinstance(exp, dict):
                    exp_texts.append(
                        f"{exp.get('role', '')} at {exp.get('company', '')} "
                        f"({exp.get('start_date', '')} - {exp.get('end_date', '')}): "
                        f"{exp.get('description', '')}"
                    )
            exp_text = (
                f"Work experience of {enriched.get('name', 'candidate')}: " + " | ".join(exp_texts)
                if exp_texts else None
            )
            # Fan out all three embeddings concurrently
            embed_jobs = [embed_text(contextual_text), embed_text(skills_text)]
            if exp_text:
                embed_jobs.append(embed_text(exp_text))
            embeds = await asyncio.gather(*embed_jobs, return_exceptions=True)
            full_embedding = embeds[0] if not isinstance(embeds[0], Exception) else None
            skills_embedding = embeds[1] if not isinstance(embeds[1], Exception) else None
            exp_embedding = embeds[2] if len(embeds) > 2 and not isinstance(embeds[2], Exception) else None
            if full_embedding:
                insert_embedding(
                    candidate_id, "full_cv", contextual_text[:2000],
                    full_embedding,
                    metadata={"name": enriched.get("name"),
                              "skills_count": len(enriched.get("skills_technical", []))},
                )
            if skills_embedding:
                insert_embedding(candidate_id, "skills", skills_text, skills_embedding)
            if exp_text and exp_embedding:
                insert_embedding(candidate_id, "experience", exp_text[:2000], exp_embedding)
            chunks = sum(1 for e in (full_embedding, skills_embedding, exp_embedding) if e)
            steps_done.append(("context_embed", "full_cv + skills + experience"))
            in_tok = _est_tokens(contextual_text + skills_text)
            _trace_finish(t_id, status="done", model=EMBED_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          input_tokens=in_tok, output_tokens=0,
                          details={"n_chunks": chunks, "token_estimate": True})
        except Exception as e:
            _trace_finish(t_id, status="error", model=EMBED_MODEL,
                          latency_ms=int((time.time()-t0)*1000), error_msg=str(e))
            raise

        # ── Step 10: QUALITY ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 10, "QUALITY", model=LITE_MODEL)
        t0 = time.time()
        try:
            quality = await asyncio.to_thread(compute_quality_score, enriched)
            steps_done.append(("quality", f"{quality}/100"))
            _trace_finish(t_id, status="done", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          details={"score": quality})
        except Exception as e:
            _trace_finish(t_id, status="error", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000), error_msg=str(e))
            raise

        # ── Step 11: TAG ──
        t_id = _trace_start(candidate_id, run_id, ingest_id, 11, "TAG", model=LITE_MODEL)
        t0 = time.time()
        try:
            tags = enriched.get("tags", [])
            with get_cursor() as cur:
                cur.execute("""
                    UPDATE candidates SET quality_score = %s, tags = %s, updated_at = NOW()
                    WHERE id = %s
                """, (quality, tags, candidate_id))
            steps_done.append(("tag", tags))
            _trace_finish(t_id, status="done", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          details={"tags": tags})
        except Exception as e:
            _trace_finish(t_id, status="error", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000), error_msg=str(e))
            raise

        # ── Facet mining (auxiliary, non-blocking) ──
        try:
            from backend.agents.facet_miner import mine_candidate
            fm = mine_candidate(candidate_id)
            steps_done.append(("facets", f"+{fm.get('added',0)} ↑{fm.get('bumped',0)}"))
        except Exception as e:
            logger.warning(f"facet mining failed: {e}")

        # ── Step 12: AUTO_MATCH ──
        # Gated by MATCH_ON_CV_UPLOAD (default False). When disabled, CV→position
        # matching ONLY runs at position-create time, not per-CV. Skipping here
        # avoids scanning every active position on every CV upload.
        from backend.core.config import MATCH_ON_CV_UPLOAD
        t_id = _trace_start(candidate_id, run_id, ingest_id, 12, "AUTO_MATCH", model=LITE_MODEL)
        t0 = time.time()
        if not MATCH_ON_CV_UPLOAD:
            logger.info(
                f"[CV {candidate_id}] pipeline.step.auto_match.skipped "
                f"reason=match_on_cv_upload_disabled"
            )
            steps_done.append(("auto_match", "skipped (flag off)"))
            _trace_finish(t_id, status="done", model=LITE_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          details={"n_positions": 0, "n_matched": 0,
                                   "skipped": True,
                                   "reason": "match_on_cv_upload_disabled"})
        else:
            try:
                n_pos, n_matched = await _auto_match_candidate(candidate_id, enriched)
                steps_done.append(("auto_match", "OK"))
                _trace_finish(t_id, status="done", model=LITE_MODEL,
                              latency_ms=int((time.time()-t0)*1000),
                              details={"n_positions": n_pos, "n_matched": n_matched})
            except Exception as am_err:
                logger.warning(f"[CV {candidate_id}] Auto-match failed: {am_err}")
                steps_done.append(("auto_match", f"error: {am_err}"))
                _trace_finish(t_id, status="error", model=LITE_MODEL,
                              latency_ms=int((time.time()-t0)*1000),
                              error_msg=str(am_err))

        # ── Step 13: AI_SUMMARY (auto-generate executive brief) ──
        # Wrapped in broad try/except: any failure here MUST NOT fail the upload.
        # On failure: log, mark candidate.ai_summary_status='failed', leave ai_summary unchanged.
        # Uses LITE_MODEL (gemini-3.1-flash-lite) — 4x cheaper than CHAT_MODEL,
        # quality plenty for 200-word exec brief. Override via SUMMARY_MODEL env.
        SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", LITE_MODEL)
        t_id = _trace_start(candidate_id, run_id, ingest_id, 13, "AI_SUMMARY", model=SUMMARY_MODEL)
        t0 = time.time()
        try:
            from backend.core.config import llm_call
            _CM = SUMMARY_MODEL
            exp_lines = ""
            for exp in (enriched.get("experience") or [])[:5]:
                if isinstance(exp, dict):
                    exp_lines += f"- {exp.get('role','')} at {exp.get('company','')} ({exp.get('start_date','')} - {exp.get('end_date','')})\n"
            sum_prompt = f"""Generate a 200-word executive brief for this candidate. Sections: Strengths, Concerns, Fit Assessment, Recommendation.

CANDIDATE: {enriched.get('name','Unknown')}
CURRENT ROLE: {enriched.get('current_role','N/A')} at {enriched.get('current_company','N/A')}
EXPERIENCE: {enriched.get('total_experience_years',0)} years | Seniority: {enriched.get('seniority_level','N/A')}
SKILLS: {', '.join((enriched.get('skills_technical') or [])[:15])}
TOOLS: {', '.join((enriched.get('tools') or [])[:10])}
QUALITY SCORE: {enriched.get('quality_score','N/A')}/100

WORK HISTORY:
{exp_lines or 'Not available'}

CV SHORT SUMMARY: {enriched.get('summary_short','N/A')}

Write a concise, professional executive brief."""
            ai_sum = await asyncio.to_thread(llm_call, sum_prompt, _CM, 0.3, 900)
            if ai_sum:
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE candidates SET ai_summary=%s, ai_summary_generated_at=NOW(), "
                        "ai_summary_status='ready' WHERE id=%s",
                        (ai_sum, candidate_id),
                    )
                steps_done.append(("ai_summary", f"{len(ai_sum)} chars"))
                _trace_finish(t_id, status="done", model=SUMMARY_MODEL,
                              latency_ms=int((time.time()-t0)*1000),
                              details={"chars": len(ai_sum)})
            else:
                # Empty response — mark failed but don't raise
                try:
                    with get_cursor() as cur:
                        cur.execute(
                            "UPDATE candidates SET ai_summary_status='failed' WHERE id=%s",
                            (candidate_id,),
                        )
                except Exception:
                    pass
                steps_done.append(("ai_summary", "empty"))
                _trace_finish(t_id, status="error", model=SUMMARY_MODEL,
                              latency_ms=int((time.time()-t0)*1000),
                              error_msg="empty response")
        except Exception as sum_err:
            # Step 13 failure isolation: log + mark failed, NEVER raise.
            # Upload must succeed even if AI summary breaks (timeout, cost cap, API error).
            logger.warning(f"[CV {candidate_id}] AI summary failed (isolated): {sum_err}")
            try:
                with get_cursor() as cur:
                    cur.execute(
                        "UPDATE candidates SET ai_summary_status='failed' WHERE id=%s",
                        (candidate_id,),
                    )
            except Exception as db_err:
                logger.warning(f"[CV {candidate_id}] failed to mark ai_summary_status: {db_err}")
            steps_done.append(("ai_summary", f"error: {sum_err}"))
            _trace_finish(t_id, status="error", model=SUMMARY_MODEL,
                          latency_ms=int((time.time()-t0)*1000),
                          error_msg=str(sum_err))

        # ── Competency auto-extract (not traced; auxiliary) ──
        try:
            from backend.routes.candidate_extras import _internal_autoextract_competencies
            comp_res = _internal_autoextract_competencies(candidate_id)
            steps_done.append(("competencies", f"{comp_res.get('scored', 0)} scored"))
        except Exception as e:
            logger.warning(f"competency auto-extract failed: {e}")
            steps_done.append(("competencies", f"error: {e}"))

        try:
            from backend.agents.sync import enqueue_dedup
            enqueue_dedup("auto_match_candidate", {"candidate_id": candidate_id})
        except Exception as e:
            logger.warning(f"enqueue auto_match_candidate failed: {e}")

        try:
            from backend.agents.dedup import propose_candidate_dups
            propose_candidate_dups(candidate_id)
        except Exception as e:
            logger.warning(f"dedup propose failed: {e}")

        duration = round(time.time() - start, 1)
        logger.info(f"[agent:pipeline] CV {candidate_id} complete in {duration}s")
        try: _cd_pipe("pipeline", events=1)
        except Exception: pass

        return {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "status": "success",
            "name": enriched.get("name"),
            "skills_count": len(enriched.get("skills_technical", [])),
            "qa_pairs": len(qa_pairs),
            "quality_score": quality,
            "duration_s": duration,
            "steps": steps_done,
        }

    except Exception as e:
        logger.error(f"[agent:pipeline] CV {candidate_id} failed: {e}")
        try: _cd_pipe("pipeline", error=str(e))
        except Exception: pass
        try:
            with get_cursor() as cur:
                cur.execute("""
                    UPDATE candidates SET is_processed = FALSE, processing_error = %s, updated_at = NOW()
                    WHERE id = %s
                """, (str(e)[:500], candidate_id))
        except Exception:
            pass

        return {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "status": "error",
            "error": str(e),
            "steps": steps_done,
            "duration_s": round(time.time() - start, 1),
        }


async def _auto_match_candidate(candidate_id: int, enriched: dict):
    """Auto-match a newly processed candidate against all active positions with JDs.
    Returns (n_positions, n_matched)."""
    from backend.routes.matching import score_candidate_against_position
    from backend.core.database import add_candidate_to_position

    candidate = {
        "id": candidate_id,
        "skills_technical": enriched.get("skills_technical", []),
        "total_experience_years": enriched.get("total_experience_years"),
        "education": enriched.get("education", []),
        "certifications": enriched.get("certifications", []),
        "experience": enriched.get("experience", []),
    }

    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM positions
            WHERE status = 'active' AND jd_text IS NOT NULL AND jd_text != ''
        """)
        cols = [desc[0] for desc in cur.description]
        positions = [dict(zip(cols, row)) for row in cur.fetchall()]

    if not positions:
        return (0, 0)

    matched_count = 0
    for position in positions:
        try:
            scores = score_candidate_against_position(candidate, position)
            min_score = position.get("min_match_score", 50)

            if scores["composite"] >= min_score:
                add_candidate_to_position(
                    position["id"], candidate_id,
                    scores={
                        "composite": scores["composite"],
                        "skills": scores["skills"],
                        "experience": scores["experience"],
                        "education": scores["education"],
                        "certifications": scores["certifications"],
                        "industry": scores["industry"],
                        "semantic": None,
                        "explanation": None,
                        "skills_matched": scores.get("skills_matched", []),
                        "skills_missing": scores.get("skills_missing", []),
                    },
                    added_by="ai_auto_match",
                )
                matched_count += 1

                hiring_manager_id = position.get("hiring_manager_id")
                if hiring_manager_id:
                    try:
                        from backend.routes.notifications import create_notification
                        cand_name = enriched.get("name", f"Candidate #{candidate_id}")
                        create_notification(
                            user_id=hiring_manager_id,
                            type="ai_match",
                            title=f"New candidate match: {cand_name} for {position.get('title', '')}",
                            message=f"Score: {scores['composite']}% — auto-matched on CV upload.",
                            link=f"/positions/{position.get('slug', '')}",
                        )
                    except Exception:
                        pass

                try:
                    with get_cursor() as cur:
                        cur.execute("""
                            INSERT INTO candidate_activity (candidate_id, position_id, user_id, activity_type, details)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            candidate_id,
                            position["id"],
                            hiring_manager_id,
                            "ai_auto_match",
                            json.dumps({"score": scores["composite"], "position_title": position.get("title")}),
                        ))
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[auto_match] Candidate {candidate_id} vs position {position.get('slug')}: {e}")

    logger.info(f"[auto_match] Candidate {candidate_id} matched to {matched_count}/{len(positions)} positions")
    return (len(positions), matched_count)
