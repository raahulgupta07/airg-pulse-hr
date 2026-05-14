"""
facet_miner — Extract & normalize filter facets (skills/companies/locations/etc.)
from candidate rows after CV pipeline completes.

Self-growing: each unique normalized value is upserted into facet_options.
NEW values surface in the UI for 7 days with a fresh-paint badge.
Idempotent — safe to re-run on the same candidate.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from backend.core.database import get_conn

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Alias map — common abbreviations & shortcuts → canonical forms
# Lowercase keys; values are canonical lowercase forms.
# ─────────────────────────────────────────────────────────────────────
ALIASES: dict[str, str] = {
    # Cloud
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "aws": "amazon web services",
    "gcp": "google cloud",
    "gcs": "google cloud",
    "azure devops": "azure",
    "ms azure": "azure",
    # Languages
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "py3": "python",
    "golang": "go",
    "c sharp": "c#",
    "csharp": "c#",
    "objective c": "objective-c",
    # DBs
    "pg": "postgresql",
    "postgres": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "mssql": "sql server",
    "ms sql": "sql server",
    # Frameworks
    "reactjs": "react",
    "react.js": "react",
    "node": "node.js",
    "nodejs": "node.js",
    "vuejs": "vue",
    "vue.js": "vue",
    "nextjs": "next.js",
    "next": "next.js",
    "nestjs": "nest.js",
    "tf": "terraform",
    # ML
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "llm": "large language models",
    # Misc
    "ci/cd": "ci-cd",
    "ci cd": "ci-cd",
    "rest api": "rest",
    "restful": "rest",
    "graphql api": "graphql",
    "uk": "united kingdom",
    "usa": "united states",
    "us": "united states",
}


def _canonicalize(raw: str) -> tuple[str, str] | None:
    """Return (display_value, canonical) or None if empty/garbage."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    # collapse whitespace
    low = " ".join(low.split())
    if not low or len(low) > 200:
        return None
    canon = ALIASES.get(low, low)
    return (s, canon)


def _flatten(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for v in values or []:
        if v is None:
            continue
        if isinstance(v, (list, tuple, set)):
            out.extend(_flatten(v))
        elif isinstance(v, dict):
            # Pull common label-ish keys
            for k in ("name", "value", "label", "title", "institution", "issuer", "degree", "field", "company", "location"):
                if k in v and v[k]:
                    out.append(str(v[k]))
        else:
            out.append(str(v))
    return out


def _extract_from_candidate(row: dict) -> dict[str, list[str]]:
    """Map candidate row fields → {facet_type: [raw_values]}."""
    skills: list[str] = []
    skills.extend(_flatten(row.get("skills_technical")))
    skills.extend(_flatten(row.get("skills_soft")))
    skills.extend(_flatten(row.get("tools")))

    languages = _flatten(row.get("languages"))

    # Experience JSONB → companies + locations
    companies: list[str] = []
    locations_exp: list[str] = []
    for e in (row.get("experience") or []):
        if isinstance(e, dict):
            if e.get("company"): companies.append(str(e["company"]))
            if e.get("location"): locations_exp.append(str(e["location"]))
    if row.get("current_company"):
        companies.append(str(row["current_company"]))

    locations: list[str] = []
    if row.get("location"):
        # split "City, Country" → keep as-is + last segment
        loc = str(row["location"])
        locations.append(loc)
        parts = [p.strip() for p in loc.split(",") if p.strip()]
        if len(parts) > 1:
            locations.append(parts[-1])
    locations.extend(locations_exp)

    # Certifications JSONB
    certs: list[str] = []
    for c in (row.get("certifications") or []):
        if isinstance(c, dict):
            if c.get("name"): certs.append(str(c["name"]))
        elif c:
            certs.append(str(c))

    # Education JSONB → institutions + degrees
    education: list[str] = []
    for e in (row.get("education") or []):
        if isinstance(e, dict):
            for k in ("institution", "degree", "field"):
                if e.get(k): education.append(str(e[k]))
        elif e:
            education.append(str(e))

    # Tags too — they often contain useful facets
    skills.extend(_flatten(row.get("tags")))

    return {
        "skill": skills,
        "company": companies,
        "location": locations,
        "language": languages,
        "cert": certs,
        "education": education,
    }


def _upsert_facet(cur, facet_type: str, display: str, canonical: str) -> str:
    """
    Try exact match; if none, try pg_trgm fuzzy >= 0.85 on canonical within facet_type.
    Returns 'added' or 'bumped'.
    """
    # 1) exact canonical match
    cur.execute(
        "SELECT id FROM facet_options WHERE facet_type=%s AND canonical=%s",
        (facet_type, canonical),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE facet_options SET count = count + 1, updated_at = NOW() WHERE id=%s",
            (row[0],),
        )
        return "bumped"

    # 2) fuzzy match — only meaningful for tokens >= 4 chars
    if len(canonical) >= 4:
        cur.execute(
            """
            SELECT id, canonical, similarity(canonical, %s) AS sim
              FROM facet_options
             WHERE facet_type = %s
               AND canonical %% %s
             ORDER BY sim DESC
             LIMIT 1
            """,
            (canonical, facet_type, canonical),
        )
        fz = cur.fetchone()
        if fz and fz[2] is not None and float(fz[2]) >= 0.85:
            cur.execute(
                "UPDATE facet_options SET count = count + 1, updated_at = NOW() WHERE id=%s",
                (fz[0],),
            )
            return "bumped"

    # 3) insert fresh
    cur.execute(
        """
        INSERT INTO facet_options (facet_type, value, canonical, source, count, is_new)
        VALUES (%s, %s, %s, 'ai', 1, TRUE)
        ON CONFLICT (facet_type, canonical) DO UPDATE SET count = facet_options.count + 1, updated_at = NOW()
        """,
        (facet_type, display, canonical),
    )
    return "added"


CANDIDATE_COLS = [
    "id", "location", "current_company", "skills_technical", "skills_soft",
    "tools", "languages", "experience", "education", "certifications", "tags",
]


def mine_candidate(candidate_id: int) -> dict:
    """Extract facets from one candidate. Idempotent. Returns {added, bumped}."""
    added = 0
    bumped = 0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cols_csv = ", ".join(f'"{c}"' for c in CANDIDATE_COLS)
                cur.execute(f"SELECT {cols_csv} FROM candidates WHERE id = %s", (candidate_id,))
                row = cur.fetchone()
                if not row:
                    return {"added": 0, "bumped": 0, "skipped": "not_found"}
                rec = dict(zip(CANDIDATE_COLS, row))

                grouped = _extract_from_candidate(rec)
                seen: set[tuple[str, str]] = set()
                for ftype, raws in grouped.items():
                    for raw in raws:
                        norm = _canonicalize(raw)
                        if not norm:
                            continue
                        display, canon = norm
                        # dedup within a single candidate so we don't bump ×3
                        if (ftype, canon) in seen:
                            continue
                        seen.add((ftype, canon))
                        try:
                            r = _upsert_facet(cur, ftype, display, canon)
                            if r == "added":
                                added += 1
                            else:
                                bumped += 1
                        except Exception as ie:
                            logger.warning(f"facet upsert fail {ftype}/{canon}: {ie}")
            conn.commit()
    except Exception as e:
        logger.warning(f"mine_candidate({candidate_id}) failed: {e}")
        return {"added": added, "bumped": bumped, "error": str(e)}

    return {"added": added, "bumped": bumped}


def mine_all() -> dict:
    """Backfill: re-run miner across all candidates. Idempotent."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM candidates WHERE status='active' OR status IS NULL")
            ids = [r[0] for r in cur.fetchall()]
    total_added = 0
    total_bumped = 0
    for cid in ids:
        r = mine_candidate(cid)
        total_added += r.get("added", 0)
        total_bumped += r.get("bumped", 0)
    return {"candidates": len(ids), "added": total_added, "bumped": total_bumped}


# ─────────────────────────────────────────────────────────────────────
# JD facet mining — separate facet_type prefix `jd_*`
# ─────────────────────────────────────────────────────────────────────
JD_COLS = [
    "id", "department", "location", "employment_type", "seniority_level",
    "required_skills", "nice_to_have_skills", "industry_keywords",
]


def _extract_from_jd(row: dict) -> dict[str, list[str]]:
    """Map jd_repository row → {jd_facet_type: [raw_values]}."""
    skills: list[str] = []
    skills.extend(_flatten(row.get("required_skills")))
    skills.extend(_flatten(row.get("nice_to_have_skills")))
    skills.extend(_flatten(row.get("industry_keywords")))

    dept: list[str] = []
    if row.get("department"):
        dept.append(str(row["department"]))

    locations: list[str] = []
    if row.get("location"):
        loc = str(row["location"])
        locations.append(loc)
        parts = [p.strip() for p in loc.split(",") if p.strip()]
        if len(parts) > 1:
            locations.append(parts[-1])

    emp: list[str] = []
    if row.get("employment_type"):
        emp.append(str(row["employment_type"]))

    seniority: list[str] = []
    if row.get("seniority_level"):
        seniority.append(str(row["seniority_level"]))

    return {
        "jd_skill": skills,
        "jd_dept": dept,
        "jd_location": locations,
        "jd_employment_type": emp,
        "jd_seniority": seniority,
    }


def mine_jd(jd_id: int) -> dict:
    """Extract facets from one JD. Idempotent. Returns {added, bumped}."""
    added = 0
    bumped = 0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cols_csv = ", ".join(f'"{c}"' for c in JD_COLS)
                cur.execute(
                    f"SELECT {cols_csv} FROM jd_repository WHERE id = %s",
                    (jd_id,),
                )
                row = cur.fetchone()
                if not row:
                    return {"added": 0, "bumped": 0, "skipped": "not_found"}
                rec = dict(zip(JD_COLS, row))

                grouped = _extract_from_jd(rec)
                seen: set[tuple[str, str]] = set()
                for ftype, raws in grouped.items():
                    for raw in raws:
                        norm = _canonicalize(raw)
                        if not norm:
                            continue
                        display, canon = norm
                        if (ftype, canon) in seen:
                            continue
                        seen.add((ftype, canon))
                        try:
                            r = _upsert_facet(cur, ftype, display, canon)
                            if r == "added":
                                added += 1
                            else:
                                bumped += 1
                        except Exception as ie:
                            logger.warning(f"jd facet upsert fail {ftype}/{canon}: {ie}")
            conn.commit()
    except Exception as e:
        logger.warning(f"mine_jd({jd_id}) failed: {e}")
        return {"added": added, "bumped": bumped, "error": str(e)}
    return {"added": added, "bumped": bumped}


def mine_all_jds() -> dict:
    """Backfill: re-run JD miner across all active JDs. Idempotent."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM jd_repository WHERE status='active' OR status IS NULL")
            ids = [r[0] for r in cur.fetchall()]
    total_added = 0
    total_bumped = 0
    for jid in ids:
        r = mine_jd(jid)
        total_added += r.get("added", 0)
        total_bumped += r.get("bumped", 0)
    return {"jds": len(ids), "added": total_added, "bumped": total_bumped}
