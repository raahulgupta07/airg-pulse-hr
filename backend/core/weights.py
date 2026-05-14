"""Weight inheritance resolver.

Effective weights = walk:
  position (override) -> jd -> sector -> tenant default,
clamped by tenant floors / caps, with JD locks bypassing position override.
"""
from __future__ import annotations

import json
from typing import Optional

from backend.core.database import get_cursor

DIMS = ("skills", "experience", "industry", "education", "certifications", "culture", "competencies")
DEFAULTS = {"skills": 40, "experience": 25, "industry": 15,
            "education": 10, "certifications": 10, "culture": 0, "competencies": 0}


def _load_tenant_policy() -> dict:
    out = {"floors": {}, "caps": {}, "knockout": {"min": 0, "max": 100}, "enforcement": "clamp"}
    with get_cursor() as cur:
        cur.execute("SELECT key, value, enforcement FROM tenant_scoring_policy")
        for k, v, en in cur.fetchall():
            v = float(v)
            if k.endswith(".min"):
                dim = k[:-4]
                if dim == "knockout":
                    out["knockout"]["min"] = v
                else:
                    out["floors"][dim] = v
            elif k.endswith(".max"):
                dim = k[:-4]
                if dim == "knockout":
                    out["knockout"]["max"] = v
                else:
                    out["caps"][dim] = v
            if en:
                out["enforcement"] = en
    return out


def _load_sector(sector_id: Optional[int]) -> Optional[dict]:
    if not sector_id:
        return None
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, name, weight_skills, weight_experience, weight_industry, "
            "weight_education, weight_certifications, weight_culture, forced_dims "
            "FROM sectors WHERE id = %s", (sector_id,))
        row = cur.fetchone()
    if not row:
        return None
    cols = ["id","name","skills","experience","industry","education","certifications","culture","forced_dims"]
    d = dict(zip(cols, row))
    d["competencies"] = None
    fd = d.get("forced_dims")
    if isinstance(fd, str):
        try: d["forced_dims"] = json.loads(fd)
        except Exception: d["forced_dims"] = []
    return d


def _load_jd(jd_id: Optional[int]) -> Optional[dict]:
    if not jd_id:
        return None
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, weight_skills, weight_experience, weight_industry, "
            "weight_education, weight_certifications, weight_culture, "
            "COALESCE(weight_competencies, 0), knockout_threshold, "
            "weights_locked, weights_locked_dims, scoring_profile "
            "FROM jd_repository WHERE id = %s", (jd_id,))
        row = cur.fetchone()
    if not row:
        return None
    cols = ["id","skills","experience","industry","education","certifications","culture","competencies","knockout","weights_locked","weights_locked_dims","scoring_profile"]
    d = dict(zip(cols, row))
    ld = d.get("weights_locked_dims")
    if isinstance(ld, str):
        try: d["weights_locked_dims"] = json.loads(ld)
        except Exception: d["weights_locked_dims"] = []
    return d


def resolve_weights(position: dict) -> dict:
    """Return per-dim resolved weight + provenance.
    Result:
      {
        "dims": [
          {"dim":"skills","tenant_min":30,"tenant_max":100,"sector":25,"jd":40,
           "position":40,"effective":40,"source":"jd","locked":false,"floored":false}
        ],
        "totals": {"effective": 100, "raw": 100},
        "knockout": {"value": 60, "source": "position"},
        "lock": {"jd_locked": false, "locked_dims": [...]}
      }
    """
    tenant = _load_tenant_policy()
    sector = _load_sector(position.get("sector_id"))
    jd = _load_jd(position.get("weights_source_jd_id"))
    pos_overridden = bool(position.get("weights_overridden"))

    rows = []
    raw_total = 0.0
    for dim in DIMS:
        tenant_min = tenant["floors"].get(dim)
        tenant_max = tenant["caps"].get(dim)
        sector_v = sector.get(dim) if sector else None
        jd_v = jd.get(dim) if jd else None
        pos_v = position.get(f"weight_{dim}")
        forced = bool(sector and dim in (sector.get("forced_dims") or []))
        jd_locked_dim = bool(jd and (jd.get("weights_locked") or dim in (jd.get("weights_locked_dims") or [])))

        # Determine effective value + source
        if jd_locked_dim and jd_v is not None:
            effective, source = float(jd_v), "jd-locked"
        elif forced and sector_v is not None:
            effective, source = float(sector_v), "sector-forced"
        elif pos_overridden and pos_v is not None:
            effective, source = float(pos_v), "position"
        elif jd_v is not None:
            effective, source = float(jd_v), "jd"
        elif sector_v is not None:
            effective, source = float(sector_v), "sector"
        else:
            effective, source = float(DEFAULTS[dim]), "default"

        floored = False
        capped = False
        if tenant_min is not None and effective < tenant_min:
            effective = tenant_min; floored = True; source += "+floor"
        if tenant_max is not None and effective > tenant_max:
            effective = tenant_max; capped = True; source += "+cap"

        rows.append({
            "dim": dim,
            "tenant_min": tenant_min, "tenant_max": tenant_max,
            "sector": sector_v, "jd": jd_v, "position": pos_v,
            "effective": effective,
            "source": source,
            "locked": jd_locked_dim,
            "forced": forced,
            "floored": floored, "capped": capped,
        })
        raw_total += effective

    # Normalize to 100
    if raw_total > 0:
        for r in rows:
            r["effective_normalized"] = round(r["effective"] * 100.0 / raw_total, 2)
    else:
        for r in rows:
            r["effective_normalized"] = 0

    knockout = position.get("knockout_threshold")
    knockout_src = "position"
    if knockout is None and jd:
        knockout = jd.get("knockout"); knockout_src = "jd"
    if knockout is None:
        knockout = 0; knockout_src = "default"
    knockout = float(knockout)
    if knockout > tenant["knockout"]["max"]:
        knockout = tenant["knockout"]["max"]; knockout_src += "+cap"
    if knockout < tenant["knockout"]["min"]:
        knockout = tenant["knockout"]["min"]; knockout_src += "+floor"

    return {
        "dims": rows,
        "raw_total": raw_total,
        "knockout": {"value": knockout, "source": knockout_src},
        "lock": {
            "jd_locked": bool(jd and jd.get("weights_locked")),
            "locked_dims": (jd.get("weights_locked_dims") if jd else []) or [],
        },
        "tenant": tenant,
        "sector": sector,
        "jd": jd,
    }


def effective_weights_for_scoring(position: dict) -> dict:
    """Return flat dict {skills, experience, ...} normalized to 100 for matcher."""
    r = resolve_weights(position)
    return {row["dim"]: row["effective_normalized"] for row in r["dims"]}


# ---------------------------------------------------------------------------
# Competency scoring
# ---------------------------------------------------------------------------
_SOURCE_PRIORITY = {
    "manual": 1.0,
    "manager-rating": 0.95,
    "scorecard": 0.9,
    "cv-extract": 0.6,
    "self-report": 0.4,
}


def score_competencies(candidate_id: int, position_id: int) -> dict:
    """Score candidate's demonstrated competencies vs position's required.

    Returns {"score": 0-100, "gaps": [{key, label, required, actual, gap, importance}]}
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT pc.competency_id, c.key, c.label,
                   pc.required_level, pc.importance, pc.weight
            FROM position_competencies pc
            JOIN competencies c ON c.id = pc.competency_id
            WHERE pc.position_id = %s
            ORDER BY CASE pc.importance
                WHEN 'required' THEN 1
                WHEN 'preferred' THEN 2
                WHEN 'nice' THEN 3
                ELSE 4 END
        """, (position_id,))
        required_rows = cur.fetchall()

        if not required_rows:
            return {"score": 0, "gaps": [], "no_requirements": True}

        comp_ids = [r[0] for r in required_rows]
        cur.execute("""
            SELECT competency_id, level, source
            FROM candidate_competencies
            WHERE candidate_id = %s AND competency_id = ANY(%s) AND level IS NOT NULL
        """, (candidate_id, comp_ids))
        all_actual = cur.fetchall()

    # Aggregate: weighted avg by source priority
    by_comp: dict = {}
    for cid, level, source in all_actual:
        prio = _SOURCE_PRIORITY.get(source, 0.5)
        by_comp.setdefault(cid, []).append((float(level or 0), prio))

    actual_levels = {}
    for cid, samples in by_comp.items():
        wsum = sum(p for _, p in samples) or 1.0
        avg = sum(l * p for l, p in samples) / wsum
        actual_levels[cid] = avg

    score_sum = 0.0
    weight_sum = 0.0
    gaps: list = []

    for comp_id, key, label, req_level, importance, weight in required_rows:
        actual = actual_levels.get(comp_id, 0.0)
        gap = actual - float(req_level)
        raw = max(0.0, min(100.0, 100.0 + gap * 20.0))
        if importance == "preferred":
            raw *= 0.7
        elif importance == "nice":
            raw *= 0.3
        w = float(weight or 1.0)
        score_sum += raw * w
        weight_sum += w
        gaps.append({
            "competency_id": comp_id,
            "key": key,
            "label": label,
            "required": int(req_level),
            "actual": round(actual, 2),
            "gap": round(gap, 2),
            "importance": importance,
        })

    score = round(score_sum / weight_sum, 1) if weight_sum > 0 else 0.0
    return {"score": score, "gaps": gaps}
