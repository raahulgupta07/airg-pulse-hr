"""Database — PostgreSQL connection pool and schema management."""
from __future__ import annotations

import os
import logging
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "pulse")
DB_PASS = os.getenv("DB_PASS", "pulse_secret")
DB_DATABASE = os.getenv("DB_DATABASE", "pulsedb")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_DATABASE}"

# Pool sizing — env-tunable for ECS task density (defaults match prior values).
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

# ---------------------------------------------------------------------------
# Connection Pool (lazy init)
# ---------------------------------------------------------------------------
_pool = None


def get_pool():
    """Get or create connection pool."""
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=DB_POOL_MIN,
            max_size=DB_POOL_MAX,
            open=True,
        )
    return _pool


@contextmanager
def get_conn():
    """Get a database connection from the pool."""
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


@contextmanager
def get_cursor():
    """Get a cursor from a pooled connection."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            yield cur
        conn.commit()


# ---------------------------------------------------------------------------
# Schema Management
# ---------------------------------------------------------------------------
def ensure_schema():
    """Check DB connectivity and verify tables exist."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'candidates'")
                exists = cur.fetchone()[0] > 0
        if exists:
            logger.info("Database schema verified — tables exist")
            # Auto-create candidate_tags table if missing
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS candidate_tags (
                                id SERIAL PRIMARY KEY,
                                candidate_id INTEGER REFERENCES candidates(id) ON DELETE CASCADE,
                                tag TEXT NOT NULL,
                                color TEXT DEFAULT '#383832',
                                created_by INTEGER REFERENCES users(id),
                                created_at TIMESTAMP DEFAULT NOW(),
                                UNIQUE(candidate_id, tag)
                            );
                            CREATE INDEX IF NOT EXISTS idx_candidate_tags_candidate ON candidate_tags(candidate_id);
                            CREATE INDEX IF NOT EXISTS idx_candidate_tags_tag ON candidate_tags(tag);
                        """)
                    conn.commit()
                logger.info("candidate_tags table ensured")
            except Exception as tag_err:
                logger.warning(f"Could not ensure candidate_tags table: {tag_err}")
        else:
            # Try running init.sql
            init_sql = Path(__file__).parent.parent.parent / "db" / "init.sql"
            if init_sql.exists():
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(init_sql.read_text())
                    conn.commit()
                logger.info("Database schema initialized from init.sql")
            else:
                logger.warning("Tables missing and init.sql not found")
    except Exception as e:
        logger.error(f"Schema check failed: {e}")
        raise


# ---------------------------------------------------------------------------
# Candidate CRUD
# ---------------------------------------------------------------------------
def insert_candidate(data: dict) -> int:
    """Insert a candidate into the central repo. Returns candidate_id."""
    with get_cursor() as cur:
        # Defaults for visibility fields
        data.setdefault("owner_id", 1)
        data.setdefault("sector_id", None)
        data.setdefault("visibility", "private")
        # Assign external-facing public_id (mig 039) if not provided
        if not data.get("public_id"):
            try:
                from backend.core.ids import gen_public_id
                data["public_id"] = gen_public_id("candidates")
            except Exception:
                data["public_id"] = None
        # Audit + retention (mig 055/056). Default created/updated_by to owner_id.
        data.setdefault("created_by_id", data.get("owner_id"))
        data.setdefault("updated_by_id", data.get("owner_id"))
        if "expires_at_days" not in data and "expires_at" not in data:
            try:
                from backend.core.expiry import get_default_expiry_days
                data["expires_at_days"] = get_default_expiry_days("cv")
            except Exception:
                data["expires_at_days"] = 90
        cur.execute("""
            INSERT INTO candidates (
                public_id,
                name, email, phone, location, linkedin_url,
                "current_role", "current_company", total_experience_years, seniority_level,
                skills_technical, skills_soft, tools, languages,
                experience, education, certifications, projects,
                summary_short, summary_detailed, raw_text,
                pdf_path, file_type, file_name, page_count,
                quality_score, tags, source, status, is_processed,
                owner_id, sector_id, visibility,
                created_by_id, updated_by_id,
                expires_at
            ) VALUES (
                %(public_id)s,
                %(name)s, %(email)s, %(phone)s, %(location)s, %(linkedin_url)s,
                %(current_role)s, %(current_company)s, %(total_experience_years)s, %(seniority_level)s,
                %(skills_technical)s, %(skills_soft)s, %(tools)s, %(languages)s,
                %(experience)s, %(education)s, %(certifications)s, %(projects)s,
                %(summary_short)s, %(summary_detailed)s, %(raw_text)s,
                %(pdf_path)s, %(file_type)s, %(file_name)s, %(page_count)s,
                %(quality_score)s, %(tags)s, %(source)s, %(status)s, %(is_processed)s,
                %(owner_id)s, %(sector_id)s, %(visibility)s,
                %(created_by_id)s, %(updated_by_id)s,
                NOW() + (%(expires_at_days)s || ' days')::interval
            ) RETURNING id
        """, data)
        return cur.fetchone()[0]


def get_candidate(candidate_id: int) -> dict | None:
    """Get a single candidate by ID."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM candidates WHERE id = %s AND status != 'blacklisted'", (candidate_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))


def _build_tsquery(search: str) -> tuple[str, str]:
    """Build a tsquery string supporting AND/OR/NOT boolean operators.

    Returns (query_fragment, param) where query_fragment uses to_tsquery
    if boolean operators are present, otherwise plainto_tsquery.
    """
    import re
    upper = search.strip()
    # Check for boolean operators (case-sensitive uppercase)
    has_bool = bool(re.search(r'\b(AND|OR|NOT)\b', upper))
    if not has_bool:
        return "search_vector @@ plainto_tsquery('english', %s)", search

    # Replace boolean keywords with tsquery operators
    parts = re.split(r'\s+', upper)
    tsquery_parts = []
    for part in parts:
        if part == 'AND':
            tsquery_parts.append('&')
        elif part == 'OR':
            tsquery_parts.append('|')
        elif part == 'NOT':
            tsquery_parts.append('& !')
        else:
            # Lowercase the actual search term
            tsquery_parts.append(part.lower())
    tsquery_str = ' '.join(tsquery_parts)
    return "search_vector @@ to_tsquery('english', %s)", tsquery_str


def list_candidates(search: str = None, skills: list = None, seniority: str = None,
                    limit: int = 50, offset: int = 0) -> list[dict]:
    """List candidates with optional filters."""
    conditions = ["status = 'active'"]
    params = []

    if search:
        query_frag, query_param = _build_tsquery(search)
        conditions.append(query_frag)
        params.append(query_param)

    if skills:
        conditions.append("skills_technical && %s")
        params.append(skills)

    if seniority:
        conditions.append("seniority_level = %s")
        params.append(seniority)

    # Safe: conditions list built internally, values are parameterized
    where = " AND ".join(conditions)
    params.extend([limit, offset])

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT id, name, email, "current_role", "current_company",
                   total_experience_years, seniority_level, skills_technical,
                   tags, quality_score, source, created_at
            FROM candidates
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def count_candidates(status: str = 'active') -> int:
    """Count total candidates."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM candidates WHERE status = %s", (status,))
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Candidate Embeddings
# ---------------------------------------------------------------------------
def insert_embedding(candidate_id: int, chunk_type: str, content: str,
                     embedding: list[float], metadata: dict = None, quality: float = 1.0):
    """Insert an embedding for a candidate."""
    import json
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO candidate_embeddings (candidate_id, chunk_type, content, metadata, embedding, quality)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (candidate_id, chunk_type, content, json.dumps(metadata or {}), embedding, quality))


def insert_qa_pair(candidate_id: int, question: str, answer: str, embedding: list[float] = None):
    """Insert a HyPE Q&A pair."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO candidate_qa_pairs (candidate_id, question, answer, embedding)
            VALUES (%s, %s, %s, %s)
        """, (candidate_id, question, answer, embedding))


# ---------------------------------------------------------------------------
# Vector Search
# ---------------------------------------------------------------------------
def vector_search_candidates(query_embedding: list[float], limit: int = 20,
                             chunk_type: str = None) -> list[dict]:
    """Search candidates by vector similarity."""
    conditions = []
    params = [query_embedding, query_embedding]

    if chunk_type:
        conditions.append("ce.chunk_type = %s")
        params.append(chunk_type)

    # Safe: conditions list built internally, values are parameterized
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT DISTINCT ON (ce.candidate_id)
                ce.candidate_id,
                c.name,
                c.current_role,
                c.skills_technical,
                c.total_experience_years,
                c.seniority_level,
                (1 - (ce.embedding <=> %s)) * (0.7 + 0.3 * ce.quality) AS similarity
            FROM candidate_embeddings ce
            JOIN candidates c ON c.id = ce.candidate_id
            {where}
            ORDER BY ce.candidate_id, similarity DESC
        """, params)

        # Re-sort by similarity
        cols = [desc[0] for desc in cur.description]
        results = [dict(zip(cols, row)) for row in cur.fetchall()]
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:limit]


def vector_search_qa(query_embedding: list[float], limit: int = 20) -> list[dict]:
    """HyPE search — question-to-question matching."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                qa.candidate_id,
                qa.question,
                qa.answer,
                c.name,
                (1 - (qa.embedding <=> %s)) AS similarity
            FROM candidate_qa_pairs qa
            JOIN candidates c ON c.id = qa.candidate_id
            WHERE qa.embedding IS NOT NULL
            ORDER BY qa.embedding <=> %s
            LIMIT %s
        """, (query_embedding, query_embedding, limit))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Position CRUD
# ---------------------------------------------------------------------------
def insert_position(data: dict) -> int:
    """Create a position. Returns position_id."""
    from backend.core.ids import gen_public_id
    data = {**data, "public_id": data.get("public_id") or gen_public_id("positions")}
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO positions (
                public_id,
                slug, title, department, location, employment_type,
                hiring_manager_id, status, icon,
                jd_text, required_skills, nice_to_have_skills,
                min_experience_years, education_level, industry_keywords,
                weight_skills, weight_experience, weight_education,
                weight_certifications, weight_industry, min_match_score
            ) VALUES (
                %(public_id)s,
                %(slug)s, %(title)s, %(department)s, %(location)s, %(employment_type)s,
                %(hiring_manager_id)s, %(status)s, %(icon)s,
                %(jd_text)s, %(required_skills)s, %(nice_to_have_skills)s,
                %(min_experience_years)s, %(education_level)s, %(industry_keywords)s,
                %(weight_skills)s, %(weight_experience)s, %(weight_education)s,
                %(weight_certifications)s, %(weight_industry)s, %(min_match_score)s
            ) RETURNING id
        """, data)
        return cur.fetchone()[0]


def get_position(slug: str) -> dict | None:
    """Get position by slug."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM positions WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))


def list_positions(status: str = None) -> list[dict]:
    """List all positions with candidate counts."""
    conditions = []
    params = []
    if status:
        conditions.append("p.status = %s")
        params.append(status)

    # Safe: conditions list built internally, values are parameterized
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT
                p.*,
                COUNT(pc.id) AS cv_count,
                COUNT(CASE WHEN pc.stage = 'shortlisted' THEN 1 END) AS shortlisted,
                ROUND(AVG(pc.match_score_composite)::numeric, 1) AS avg_match
            FROM positions p
            LEFT JOIN position_candidates pc ON pc.position_id = p.id
            {where}
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """, params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Position Candidates
# ---------------------------------------------------------------------------
def add_candidate_to_position(position_id: int, candidate_id: int,
                              scores: dict = None, added_by: str = 'manual') -> int:
    """Add a candidate to a position with optional scores."""
    scores = scores or {}
    auto_added = added_by in ('ai_scan', 'auto_match', 'ai_auto')
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO position_candidates (
                position_id, candidate_id,
                match_score_composite, match_score_skills, match_score_experience,
                match_score_education, match_score_certifications, match_score_industry,
                match_score_culture,
                match_score_semantic, match_explanation,
                skills_matched, skills_missing,
                stage, added_by, auto_added
            ) VALUES (
                %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s,
                'uploaded', %s, %s
            )
            ON CONFLICT (position_id, candidate_id) DO UPDATE SET
                match_score_composite = EXCLUDED.match_score_composite,
                match_score_skills = EXCLUDED.match_score_skills,
                match_score_experience = EXCLUDED.match_score_experience,
                match_score_education = EXCLUDED.match_score_education,
                match_score_certifications = EXCLUDED.match_score_certifications,
                match_score_industry = EXCLUDED.match_score_industry,
                match_score_culture = EXCLUDED.match_score_culture,
                match_score_semantic = EXCLUDED.match_score_semantic,
                match_explanation = EXCLUDED.match_explanation,
                skills_matched = EXCLUDED.skills_matched,
                skills_missing = EXCLUDED.skills_missing,
                updated_at = NOW()
            RETURNING id
        """, (
            position_id, candidate_id,
            scores.get('composite'), scores.get('skills'), scores.get('experience'),
            scores.get('education'), scores.get('certifications'), scores.get('industry'),
            scores.get('culture'),
            scores.get('semantic'), scores.get('explanation'),
            scores.get('skills_matched', []), scores.get('skills_missing', []),
            added_by, auto_added,
        ))
        return cur.fetchone()[0]


def get_position_candidates(position_id: int, stage: str = None,
                            limit: int = 50, offset: int = 0) -> list[dict]:
    """Get candidates for a position, ranked by match score.

    Excludes 'suggested' attachment_state (those are AI suggestions, shown
    separately in the AI tab — they are NOT yet attached to the pipeline).
    """
    conditions = ["pc.position_id = %s",
                  "COALESCE(pc.attachment_state, 'attached') != 'suggested'"]
    params = [position_id]

    if stage:
        conditions.append("pc.stage = %s")
        params.append(stage)

    # Safe: conditions list built internally, values are parameterized
    where = " AND ".join(conditions)
    params.extend([limit, offset])

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT
                pc.*,
                c.name, c.email, c.current_role, c.current_company,
                c.total_experience_years, c.seniority_level,
                c.skills_technical, c.tags, c.quality_score, c.pdf_path
            FROM position_candidates pc
            JOIN candidates c ON c.id = pc.candidate_id
            WHERE {where}
            ORDER BY pc.match_score_composite DESC NULLS LAST
            LIMIT %s OFFSET %s
        """, params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def update_candidate_stage(position_id: int, candidate_id: int, stage: str,
                           rejection_reason: str = None):
    """Move a candidate to a new pipeline stage."""
    with get_cursor() as cur:
        cur.execute("""
            UPDATE position_candidates
            SET stage = %s, stage_changed_at = NOW(), rejection_reason = %s, updated_at = NOW()
            WHERE position_id = %s AND candidate_id = %s
        """, (stage, rejection_reason, position_id, candidate_id))


def get_pipeline_counts(position_id: int) -> dict:
    """Get candidate counts per pipeline stage."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT stage, COUNT(*) as count
            FROM position_candidates
            WHERE position_id = %s
            GROUP BY stage
        """, (position_id,))
        return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
def create_chat_session(user_id: int = None, position_id: int = None, title: str = None) -> int:
    """Create a new chat session."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO chat_sessions (user_id, position_id, title)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (user_id, position_id, title))
        return cur.fetchone()[0]


def add_chat_message(session_id: int, role: str, content: str,
                     sources: list = None, suggestions: list = None,
                     model_used: str = None) -> int:
    """Add a message to a chat session."""
    import json
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO chat_messages (session_id, role, content, sources, suggestions, model_used)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (session_id, role, content, json.dumps(sources or []), suggestions or [], model_used))
        # Update session message count
        cur.execute("""
            UPDATE chat_sessions SET message_count = message_count + 1, updated_at = NOW()
            WHERE id = %s
        """, (session_id,))
        return cur.fetchone()[0]


def get_chat_messages(session_id: int) -> list[dict]:
    """Get all messages for a chat session."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM chat_messages
            WHERE session_id = %s
            ORDER BY created_at ASC
            LIMIT 500
        """, (session_id,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def list_chat_sessions(user_id: int = None, position_id: int = None) -> list[dict]:
    """List chat sessions."""
    conditions = []
    params = []
    if user_id:
        conditions.append("user_id = %s")
        params.append(user_id)
    if position_id is not None:
        conditions.append("position_id = %s")
        params.append(position_id)

    # Safe: conditions list built internally, values are parameterized
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT * FROM chat_sessions
            {where}
            ORDER BY updated_at DESC
            LIMIT 50
        """, params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# HR Brain
# ---------------------------------------------------------------------------
def get_brain_entries(category: str = None, position_id: int = None) -> list[dict]:
    """Get HR Brain knowledge entries."""
    conditions = []
    params = []
    if category:
        conditions.append("category = %s")
        params.append(category)
    if position_id is not None:
        conditions.append("(position_id = %s OR position_id IS NULL)")
        params.append(position_id)
    else:
        conditions.append("position_id IS NULL")

    # Safe: conditions list built internally, values are parameterized
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as cur:
        cur.execute(f"SELECT * FROM hr_brain {where} ORDER BY created_at DESC LIMIT 500", params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_feedback_patterns(position_id: int = None) -> dict:
    """Get DO/AVOID patterns for agent injection."""
    conditions = []
    params = []
    if position_id is not None:
        conditions.append("(position_id = %s OR position_id IS NULL)")
        params.append(position_id)

    # Safe: conditions list built internally, values are parameterized
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as cur:
        cur.execute(f"SELECT type, pattern FROM hr_brain_learnings {where} ORDER BY confidence DESC LIMIT 500", params)
        do_patterns = []
        avoid_patterns = []
        for row in cur.fetchall():
            if row[0] == 'learned_positive':
                do_patterns.append(row[1])
            else:
                avoid_patterns.append(row[1])
        return {"do": do_patterns, "avoid": avoid_patterns}


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def list_templates(category: str = None) -> list[dict]:
    """List templates, optionally filtered by category."""
    if category:
        query = "SELECT * FROM templates WHERE category = %s ORDER BY usage_count DESC LIMIT 500"
        params = (category,)
    else:
        query = "SELECT * FROM templates ORDER BY usage_count DESC LIMIT 500"
        params = ()

    with get_cursor() as cur:
        cur.execute(query, params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_template(template_id: int) -> dict | None:
    """Get a single template."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM templates WHERE id = %s", (template_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------
def log_audit(user_id: int, action: str, resource_type: str = None,
              resource_id: int = None, details: dict = None):
    """Log an audit event."""
    import json
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO audit_log (user_id, action, resource_type, resource_id, details)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, action, resource_type, resource_id, json.dumps(details or {})))
