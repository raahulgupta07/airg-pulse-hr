"""Merge engine — preview, apply, reject, revert merge proposals."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from backend.core.database import get_cursor

logger = logging.getLogger(__name__)


# Tables to rewire when merging two candidate rows.
# Format: (table, fk_column, special) where special is one of:
#   None             — straight UPDATE
#   "pos_cand_uniq"  — position_candidates unique on (position_id, candidate_id)
#   "eeo_uniq"       — eeo_data unique on candidate_id
#   "tags_uniq"      — candidate_tags unique on (candidate_id, tag)
#   "notif_filter"   — notifications WHERE type related to candidate w/ resource_id encoded in link
#   "audit_filter"   — audit_log WHERE resource_type='candidates'
CANDIDATE_FK_TABLES = [
    ("position_candidates", "candidate_id", "pos_cand_uniq"),
    ("candidate_notes", "candidate_id", None),
    ("candidate_activity", "candidate_id", None),
    ("candidate_screenshots", "candidate_id", None),
    ("candidate_qa_pairs", "candidate_id", None),
    ("candidate_embeddings", "candidate_id", None),
    ("candidate_flags", "candidate_id", None),
    ("eeo_data", "candidate_id", "eeo_uniq"),
    ("candidate_tags", "candidate_id", "tags_uniq"),
    ("audit_log", "resource_id", "audit_filter"),
]

JD_FK_TABLES = [
    # positions referencing weights_source_jd_id
    ("positions", "weights_source_jd_id", None),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _table_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name=%s", (name,))
    return cur.fetchone() is not None


def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
        (table, column),
    )
    return cur.fetchone() is not None


def _get_proposal(proposal_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM merge_proposals WHERE id=%s", (proposal_id,))
        row = cur.fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(404, f"Proposal {proposal_id} not found")
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------
def preview_merge(proposal_id: int) -> dict:
    """Return full merge preview with field-level winner/loser values + assignment counts."""
    p = _get_proposal(proposal_id)
    entity_type = p["entity_type"]
    winner_id = p["winner_id"]
    loser_id = p["loser_id"]

    if entity_type == "candidate":
        table = "candidates"
        fk_tables = CANDIDATE_FK_TABLES
    elif entity_type == "jd":
        table = "jd_repository"
        fk_tables = JD_FK_TABLES
    else:
        from fastapi import HTTPException
        raise HTTPException(400, f"Unsupported entity_type {entity_type}")

    with get_cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE id=%s", (winner_id,))
        wrow = cur.fetchone()
        wcols = [d[0] for d in cur.description] if wrow else []
        winner = dict(zip(wcols, wrow)) if wrow else {}

        cur.execute(f"SELECT * FROM {table} WHERE id=%s", (loser_id,))
        lrow = cur.fetchone()
        lcols = [d[0] for d in cur.description] if lrow else []
        loser = dict(zip(lcols, lrow)) if lrow else {}

        # Field-level diff (skip internal fields)
        skip = {"id", "created_at", "updated_at", "search_vector", "uuid", "merged_into", "raw_text"}
        fields = {}
        suggested = {}
        for k in winner:
            if k in skip:
                continue
            wv = winner.get(k)
            lv = loser.get(k)
            same = wv == lv
            fields[k] = {"winner": wv, "loser": lv, "same": same}
            # default merged value: prefer winner; if winner empty/null, take loser
            if wv in (None, "", [], {}):
                suggested[k] = lv
            else:
                suggested[k] = wv

        # Assignment counts (FK references to loser)
        counts = {}
        for tbl, col, special in fk_tables:
            if not _table_exists(cur, tbl) or not _column_exists(cur, tbl, col):
                continue
            if special == "audit_filter":
                cur.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE {col}=%s AND resource_type='candidates'",
                    (loser_id,),
                )
            else:
                cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col}=%s", (loser_id,))
            counts[tbl] = cur.fetchone()[0]

    return {
        "proposal": p,
        "entity_type": entity_type,
        "winner": winner,
        "loser": loser,
        "fields": fields,
        "suggested_merged": suggested,
        "assignment_counts": counts,
        "diff": p.get("diff") or {},
    }


# ---------------------------------------------------------------------------
# Apply merge
# ---------------------------------------------------------------------------
def apply_merge(
    proposal_id: int,
    field_choices: Optional[dict] = None,
    archive: bool = True,
    user_id: Optional[int] = None,
    auto: bool = False,
) -> dict:
    """Apply a merge proposal in a single transaction."""
    from backend.core.database import get_conn

    field_choices = field_choices or {}

    p = _get_proposal(proposal_id)
    if p["status"] == "applied":
        # Idempotent
        return {
            "merged_id": p["winner_id"],
            "loser_id": p["loser_id"],
            "fk_changes_count": 0,
            "already_applied": True,
        }
    if p["status"] in ("rejected", "reverted"):
        from fastapi import HTTPException
        raise HTTPException(400, f"Cannot apply merge in status {p['status']}")

    entity_type = p["entity_type"]
    winner_id = p["winner_id"]
    loser_id = p["loser_id"]

    if winner_id == loser_id:
        from fastapi import HTTPException
        raise HTTPException(400, "winner_id == loser_id")

    if entity_type == "candidate":
        return _apply_candidate_merge(proposal_id, winner_id, loser_id, field_choices, archive, user_id)
    elif entity_type == "jd":
        return _apply_jd_merge(proposal_id, winner_id, loser_id, field_choices, archive, user_id)
    else:
        from fastapi import HTTPException
        raise HTTPException(400, f"Unsupported entity_type {entity_type}")


def _log_fk_change(cur, proposal_id: int, table: str, fk_col: str, row_id: int, old: int, new: int):
    cur.execute(
        """INSERT INTO merge_fk_history (proposal_id, table_name, fk_column, row_id, old_value, new_value)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (proposal_id, table, fk_col, row_id, old, new),
    )


def _apply_candidate_merge(proposal_id, winner_id, loser_id, field_choices, archive, user_id):
    from backend.core.database import get_conn

    fk_changes = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1. Update winner with chosen field values
            if field_choices:
                # Filter only valid columns
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='candidates'")
                valid_cols = {r[0] for r in cur.fetchall()}
                set_parts, params = [], []
                for k, v in field_choices.items():
                    if k in valid_cols and k not in ("id", "uuid", "created_at", "merged_into"):
                        set_parts.append(f"{k} = %s")
                        params.append(v)
                if set_parts:
                    set_parts.append("updated_at = NOW()")
                    params.append(winner_id)
                    cur.execute(f"UPDATE candidates SET {', '.join(set_parts)} WHERE id = %s", params)

            # 2. Rewire FKs
            for tbl, col, special in CANDIDATE_FK_TABLES:
                cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name=%s", (tbl,))
                if not cur.fetchone():
                    continue
                cur.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
                    (tbl, col),
                )
                if not cur.fetchone():
                    continue

                if special == "pos_cand_uniq":
                    # Find loser rows
                    cur.execute(f"SELECT id, position_id FROM {tbl} WHERE {col}=%s", (loser_id,))
                    rows = cur.fetchall()
                    for rid, pos_id in rows:
                        cur.execute(
                            f"SELECT id FROM {tbl} WHERE position_id=%s AND {col}=%s",
                            (pos_id, winner_id),
                        )
                        if cur.fetchone():
                            # Winner already has row for this position — delete loser row
                            cur.execute(f"DELETE FROM {tbl} WHERE id=%s", (rid,))
                            _log_fk_change(cur, proposal_id, tbl, col, rid, loser_id, -1)
                        else:
                            cur.execute(f"UPDATE {tbl} SET {col}=%s WHERE id=%s", (winner_id, rid))
                            _log_fk_change(cur, proposal_id, tbl, col, rid, loser_id, winner_id)
                        fk_changes += 1

                elif special == "eeo_uniq":
                    cur.execute(f"SELECT id FROM {tbl} WHERE {col}=%s", (loser_id,))
                    rows = cur.fetchall()
                    for (rid,) in rows:
                        cur.execute(f"SELECT id FROM {tbl} WHERE {col}=%s", (winner_id,))
                        if cur.fetchone():
                            cur.execute(f"DELETE FROM {tbl} WHERE id=%s", (rid,))
                            _log_fk_change(cur, proposal_id, tbl, col, rid, loser_id, -1)
                        else:
                            cur.execute(f"UPDATE {tbl} SET {col}=%s WHERE id=%s", (winner_id, rid))
                            _log_fk_change(cur, proposal_id, tbl, col, rid, loser_id, winner_id)
                        fk_changes += 1

                elif special == "tags_uniq":
                    cur.execute(f"SELECT id, tag FROM {tbl} WHERE {col}=%s", (loser_id,))
                    rows = cur.fetchall()
                    for rid, tag in rows:
                        cur.execute(
                            f"SELECT id FROM {tbl} WHERE {col}=%s AND tag=%s",
                            (winner_id, tag),
                        )
                        if cur.fetchone():
                            cur.execute(f"DELETE FROM {tbl} WHERE id=%s", (rid,))
                            _log_fk_change(cur, proposal_id, tbl, col, rid, loser_id, -1)
                        else:
                            cur.execute(f"UPDATE {tbl} SET {col}=%s WHERE id=%s", (winner_id, rid))
                            _log_fk_change(cur, proposal_id, tbl, col, rid, loser_id, winner_id)
                        fk_changes += 1

                elif special == "audit_filter":
                    cur.execute(
                        f"SELECT id FROM {tbl} WHERE {col}=%s AND resource_type='candidates'",
                        (loser_id,),
                    )
                    rows = cur.fetchall()
                    for (rid,) in rows:
                        cur.execute(f"UPDATE {tbl} SET {col}=%s WHERE id=%s", (winner_id, rid))
                        _log_fk_change(cur, proposal_id, tbl, col, rid, loser_id, winner_id)
                        fk_changes += 1

                else:
                    cur.execute(f"SELECT id FROM {tbl} WHERE {col}=%s", (loser_id,))
                    rows = cur.fetchall()
                    for (rid,) in rows:
                        cur.execute(f"UPDATE {tbl} SET {col}=%s WHERE id=%s", (winner_id, rid))
                        _log_fk_change(cur, proposal_id, tbl, col, rid, loser_id, winner_id)
                        fk_changes += 1

            # Notifications referencing candidate (best-effort: link contains /candidates/<id>)
            try:
                cur.execute(
                    "SELECT id FROM notifications WHERE link LIKE %s",
                    (f"%/candidates/{loser_id}%",),
                )
                for (nid,) in cur.fetchall():
                    cur.execute(
                        "UPDATE notifications SET link = REPLACE(link, %s, %s) WHERE id=%s",
                        (f"/candidates/{loser_id}", f"/candidates/{winner_id}", nid),
                    )
                    _log_fk_change(cur, proposal_id, "notifications", "link", nid, loser_id, winner_id)
                    fk_changes += 1
            except Exception:
                pass

            # 3. Archive or delete loser
            if archive:
                cur.execute(
                    "UPDATE candidates SET status='merged', merged_into=%s, updated_at=NOW() WHERE id=%s",
                    (winner_id, loser_id),
                )
            else:
                cur.execute("DELETE FROM candidates WHERE id=%s", (loser_id,))

            # 4. Update proposal
            cur.execute(
                "UPDATE merge_proposals SET status='applied', decided_by=%s, decided_at=NOW() WHERE id=%s",
                (user_id, proposal_id),
            )

            # 5. Audit log
            try:
                cur.execute(
                    """INSERT INTO audit_log (user_id, action, resource_type, resource_id, details)
                       VALUES (%s, 'CANDIDATE_MERGE', 'candidates', %s, %s)""",
                    (
                        user_id,
                        winner_id,
                        json.dumps({
                            "proposal_id": proposal_id,
                            "winner_id": winner_id,
                            "loser_id": loser_id,
                            "archive": archive,
                            "fk_changes": fk_changes,
                        }),
                    ),
                )
            except Exception as e:
                logger.warning(f"audit_log insert failed: {e}")

        conn.commit()

    return {"merged_id": winner_id, "loser_id": loser_id, "fk_changes_count": fk_changes}


def _apply_jd_merge(proposal_id, winner_id, loser_id, field_choices, archive, user_id):
    from backend.core.database import get_conn

    fk_changes = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            if field_choices:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='jd_repository'"
                )
                valid_cols = {r[0] for r in cur.fetchall()}
                set_parts, params = [], []
                for k, v in field_choices.items():
                    if k in valid_cols and k not in ("id", "uuid", "created_at", "merged_into"):
                        set_parts.append(f"{k}=%s")
                        params.append(v)
                if set_parts:
                    set_parts.append("updated_at=NOW()")
                    params.append(winner_id)
                    cur.execute(f"UPDATE jd_repository SET {', '.join(set_parts)} WHERE id=%s", params)

            # positions.weights_source_jd_id
            cur.execute("SELECT id FROM positions WHERE weights_source_jd_id=%s", (loser_id,))
            for (pid,) in cur.fetchall():
                cur.execute("UPDATE positions SET weights_source_jd_id=%s WHERE id=%s", (winner_id, pid))
                _log_fk_change(cur, proposal_id, "positions", "weights_source_jd_id", pid, loser_id, winner_id)
                fk_changes += 1

            # positions.jd_id (if column exists)
            cur.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name='positions' AND column_name='jd_id'"
            )
            if cur.fetchone():
                cur.execute("SELECT id FROM positions WHERE jd_id=%s", (loser_id,))
                for (pid,) in cur.fetchall():
                    cur.execute("UPDATE positions SET jd_id=%s WHERE id=%s", (winner_id, pid))
                    _log_fk_change(cur, proposal_id, "positions", "jd_id", pid, loser_id, winner_id)
                    fk_changes += 1

            if archive:
                cur.execute(
                    "UPDATE jd_repository SET status='merged', merged_into=%s, updated_at=NOW() WHERE id=%s",
                    (winner_id, loser_id),
                )
            else:
                cur.execute("DELETE FROM jd_repository WHERE id=%s", (loser_id,))

            cur.execute(
                "UPDATE merge_proposals SET status='applied', decided_by=%s, decided_at=NOW() WHERE id=%s",
                (user_id, proposal_id),
            )
            try:
                cur.execute(
                    """INSERT INTO audit_log (user_id, action, resource_type, resource_id, details)
                       VALUES (%s, 'JD_MERGE', 'jd_repository', %s, %s)""",
                    (
                        user_id,
                        winner_id,
                        json.dumps({"proposal_id": proposal_id, "winner_id": winner_id,
                                    "loser_id": loser_id, "archive": archive,
                                    "fk_changes": fk_changes}),
                    ),
                )
            except Exception:
                pass
        conn.commit()
    return {"merged_id": winner_id, "loser_id": loser_id, "fk_changes_count": fk_changes}


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------
def reject_merge(proposal_id: int, user_id: Optional[int], notes: Optional[str] = None) -> dict:
    p = _get_proposal(proposal_id)
    if p["status"] != "pending":
        from fastapi import HTTPException
        raise HTTPException(400, f"Cannot reject merge in status {p['status']}")

    with get_cursor() as cur:
        cur.execute(
            "UPDATE merge_proposals SET status='rejected', decided_by=%s, decided_at=NOW(), notes=%s WHERE id=%s",
            (user_id, notes, proposal_id),
        )
        # Insert into not_duplicates (idempotent via unique index)
        try:
            cur.execute(
                """INSERT INTO not_duplicates (entity_type, a_id, b_id, decided_by)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (p["entity_type"], p["winner_id"], p["loser_id"], user_id),
            )
        except Exception as e:
            logger.warning(f"not_duplicates insert failed: {e}")

    return {"id": proposal_id, "status": "rejected"}


# ---------------------------------------------------------------------------
# Revert
# ---------------------------------------------------------------------------
def revert_merge(proposal_id: int, user_id: Optional[int]) -> dict:
    p = _get_proposal(proposal_id)
    if p["status"] != "applied":
        from fastapi import HTTPException
        raise HTTPException(400, f"Cannot revert merge in status {p['status']}")

    entity_type = p["entity_type"]
    winner_id = p["winner_id"]
    loser_id = p["loser_id"]

    if entity_type == "candidate":
        table = "candidates"
    elif entity_type == "jd":
        table = "jd_repository"
    else:
        from fastapi import HTTPException
        raise HTTPException(400, f"Unsupported entity_type {entity_type}")

    from backend.core.database import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Verify loser still exists (was archived, not hard-deleted)
            cur.execute(f"SELECT id, status FROM {table} WHERE id=%s", (loser_id,))
            row = cur.fetchone()
            if not row:
                from fastapi import HTTPException
                raise HTTPException(400, "cannot revert hard delete")
            # Replay history backwards
            cur.execute(
                """SELECT id, table_name, fk_column, row_id, old_value, new_value
                   FROM merge_fk_history WHERE proposal_id=%s ORDER BY id DESC""",
                (proposal_id,),
            )
            history = cur.fetchall()
            for hid, tbl, col, rid, old_val, new_val in history:
                # Special: notifications.link replacement
                if tbl == "notifications" and col == "link":
                    cur.execute(
                        "UPDATE notifications SET link = REPLACE(link, %s, %s) WHERE id=%s",
                        (f"/candidates/{new_val}", f"/candidates/{old_val}", rid),
                    )
                    continue
                # If new_value == -1, the row was deleted during merge (conflict with winner) — cannot restore
                if new_val == -1:
                    logger.warning(f"cannot restore deleted row {tbl}.{rid} during revert")
                    continue
                # straight update back
                try:
                    cur.execute(f"UPDATE {tbl} SET {col}=%s WHERE id=%s", (old_val, rid))
                except Exception as e:
                    logger.warning(f"revert {tbl}.{rid}: {e}")

            # Restore loser
            cur.execute(
                f"UPDATE {table} SET status='active', merged_into=NULL, updated_at=NOW() WHERE id=%s",
                (loser_id,),
            )
            cur.execute(
                "UPDATE merge_proposals SET status='reverted', decided_by=%s, decided_at=NOW() WHERE id=%s",
                (user_id, proposal_id),
            )
            try:
                cur.execute(
                    """INSERT INTO audit_log (user_id, action, resource_type, resource_id, details)
                       VALUES (%s, 'MERGE_REVERT', %s, %s, %s)""",
                    (
                        user_id, table, winner_id,
                        json.dumps({"proposal_id": proposal_id, "winner_id": winner_id, "loser_id": loser_id}),
                    ),
                )
            except Exception:
                pass
        conn.commit()
    return {"id": proposal_id, "status": "reverted", "loser_id": loser_id}
