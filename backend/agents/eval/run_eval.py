"""Eval runner — invoke agent on goldens, score with LITE judge.

Usage:
    python -m backend.agents.eval.run_eval [--limit N] [--out report.json]

Loads golden.jsonl, runs each query through `backend.agents.hr_agent.arun`,
captures the tool-call trace + final answer, then asks the LITE_MODEL judge
to score each interaction on three 0-5 dimensions (correctness, tool_choice,
conciseness). Aggregates per-category and overall.

CI gate: exits 0 if overall average >= 4.0, else exits 1.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EVAL_DIR = Path(__file__).parent
GOLDEN_PATH = EVAL_DIR / "golden.jsonl"
DEFAULT_OUT = EVAL_DIR / "report.json"
PASS_THRESHOLD = 4.0
JUDGE_TEMPERATURE = 0.1
ANSWER_TRUNCATE = 1000


# ---------------------------------------------------------------------------
# Golden loader
# ---------------------------------------------------------------------------
def load_goldens(path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    """Read JSONL goldens; raises on malformed lines."""
    if not path.exists():
        raise FileNotFoundError(f"Golden file missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Bad JSON at {path}:{i} -> {e}") from e
    return rows


# ---------------------------------------------------------------------------
# Agent invocation
# ---------------------------------------------------------------------------
async def run_one(golden: dict[str, Any]) -> dict[str, Any]:
    """Invoke hr_agent.arun on a single golden, return collected events."""
    # Lazy import so the judge can still run if the agent module isn't ready.
    from backend.agents.hr_agent import arun  # type: ignore

    session_id = f"eval-{uuid.uuid4().hex[:8]}"
    user = {"role": "admin", "tenant_id": 1, "user_id": 1}
    events: list[dict[str, Any]] = []
    t0 = time.time()
    try:
        async for ev in arun(golden["q"], session_id=session_id, user=user):
            # Normalize: events may be dataclass-like or dicts
            events.append(_event_to_dict(ev))
    except Exception as e:
        events.append({"event": "error", "data": {"message": f"{type(e).__name__}: {e}"}})
    latency_ms = int((time.time() - t0) * 1000)

    actual_tools = [
        ev["data"].get("name")
        for ev in events
        if ev.get("event") == "tool_call" and isinstance(ev.get("data"), dict)
    ]
    final_answer = ""
    for ev in events:
        if ev.get("event") == "answer" and isinstance(ev.get("data"), dict):
            final_answer = ev["data"].get("content", "") or ""

    return {
        "events": events,
        "actual_tools": [t for t in actual_tools if t],
        "final_answer": final_answer,
        "latency_ms": latency_ms,
    }


def _event_to_dict(ev: Any) -> dict[str, Any]:
    """Coerce an event (dict / object with .event+.data) into a plain dict."""
    if isinstance(ev, dict):
        return ev
    return {
        "event": getattr(ev, "event", None),
        "data": getattr(ev, "data", {}),
    }


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------
JUDGE_PROMPT = """You are evaluating an HR chatbot.
Question: {q}
Expected behavior: {rubric}
Tools used: {actual_tools}
Expected tools: {expected_tools}
Answer: {final_answer}

Score 0-5 each:
- correctness (does answer satisfy the rubric?)
- tool_choice (did it pick reasonable tools? +1 if all expected hit, +1 partial)
- conciseness (no rambling)
Return JSON {{"correctness": <0-5>, "tool_choice": <0-5>, "conciseness": <0-5>, "notes": "<one sentence>"}}
"""


def judge(golden: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Call LITE_MODEL judge, return parsed scores."""
    from backend.core.config import LITE_MODEL, llm_call

    prompt = JUDGE_PROMPT.format(
        q=golden["q"],
        rubric=golden.get("rubric", ""),
        actual_tools=run["actual_tools"],
        expected_tools=golden.get("expected_tools", []),
        final_answer=(run["final_answer"] or "")[:ANSWER_TRUNCATE],
    )
    raw = llm_call(prompt, model=LITE_MODEL, temperature=JUDGE_TEMPERATURE, max_tokens=300)
    return _parse_judge(raw)


def _parse_judge(raw: str | None) -> dict[str, Any]:
    """Extract scoring JSON from judge output. Robust to fences / preamble."""
    fallback = {"correctness": 0, "tool_choice": 0, "conciseness": 0,
                "notes": "judge_parse_failed"}
    if not raw:
        return fallback
    # Pull first {...} block
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return fallback
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return fallback
    return {
        "correctness": _clip(obj.get("correctness", 0)),
        "tool_choice": _clip(obj.get("tool_choice", 0)),
        "conciseness": _clip(obj.get("conciseness", 0)),
        "notes": str(obj.get("notes", ""))[:300],
    }


def _clip(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(5.0, f))


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
DIMS = ("correctness", "tool_choice", "conciseness")


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-dim, per-category, and overall averages."""
    overall = {d: _mean([r["scores"][d] for r in results]) for d in DIMS}
    overall["avg"] = _mean(list(overall.values()))

    by_cat: dict[str, dict[str, float]] = {}
    cat_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        cat_groups[r["category"]].append(r)
    for cat, rows in cat_groups.items():
        cat_dims = {d: _mean([r["scores"][d] for r in rows]) for d in DIMS}
        cat_dims["avg"] = _mean(list(cat_dims.values()))
        cat_dims["n"] = len(rows)
        by_cat[cat] = cat_dims

    return {"overall": overall, "by_category": by_cat, "n": len(results)}


def _mean(xs: list[float]) -> float:
    xs = [float(x) for x in xs if x is not None]
    return round(statistics.mean(xs), 3) if xs else 0.0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_summary(agg: dict[str, Any]) -> None:
    print("\n" + "=" * 64)
    print(f"EVAL SUMMARY  (n={agg['n']})")
    print("=" * 64)
    o = agg["overall"]
    print(f"  OVERALL AVG: {o['avg']:.2f}   "
          f"correctness={o['correctness']:.2f}  "
          f"tool_choice={o['tool_choice']:.2f}  "
          f"conciseness={o['conciseness']:.2f}")
    print("-" * 64)
    print(f"  {'CATEGORY':<14} {'N':>3}  {'AVG':>5}  {'CORR':>5}  "
          f"{'TOOL':>5}  {'CONC':>5}")
    for cat, s in sorted(agg["by_category"].items()):
        print(f"  {cat:<14} {int(s['n']):>3}  {s['avg']:>5.2f}  "
              f"{s['correctness']:>5.2f}  {s['tool_choice']:>5.2f}  "
              f"{s['conciseness']:>5.2f}")
    print("=" * 64)
    verdict = "PASS" if o["avg"] >= PASS_THRESHOLD else "FAIL"
    print(f"  THRESHOLD {PASS_THRESHOLD}  ->  {verdict}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def _async_main(limit: int | None, out_path: Path) -> int:
    goldens = load_goldens()
    if limit:
        goldens = goldens[:limit]

    results: list[dict[str, Any]] = []
    for i, g in enumerate(goldens, 1):
        print(f"[{i}/{len(goldens)}] {g['id']} ({g['category']}): {g['q'][:60]}")
        run = await run_one(g)
        scores = judge(g, run)
        results.append({
            "id": g["id"],
            "category": g["category"],
            "q": g["q"],
            "expected_tools": g.get("expected_tools", []),
            "actual_tools": run["actual_tools"],
            "final_answer": run["final_answer"],
            "latency_ms": run["latency_ms"],
            "scores": scores,
        })

    agg = aggregate(results)
    report = {
        "threshold": PASS_THRESHOLD,
        "passed": agg["overall"]["avg"] >= PASS_THRESHOLD,
        "aggregate": agg,
        "results": results,
    }
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport written: {out_path}")
    print_summary(agg)
    return 0 if report["passed"] else 1


def main() -> None:
    p = argparse.ArgumentParser(description="Run HR agent eval against goldens.")
    p.add_argument("--limit", type=int, default=None,
                   help="Run only the first N goldens (smoke test).")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help=f"Path for JSON report (default: {DEFAULT_OUT}).")
    args = p.parse_args()
    rc = asyncio.run(_async_main(args.limit, args.out))
    sys.exit(rc)


if __name__ == "__main__":
    main()
