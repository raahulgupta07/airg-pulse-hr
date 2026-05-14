"""Vision model bench — OCR + structure on single image, score against ground truth."""
from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
GT_PATH = ROOT / "bench" / "ground_truth.json"
RUNS_DIR = ROOT / "bench" / "runs"
RESULTS_MD = ROOT / "bench" / "vision_results.md"

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
}

OCR_PROMPT = """Extract ALL text from this image verbatim. Preserve structure (labels, values, sections).
Output as clean markdown. Include every handwritten value. Do not summarize."""

STRUCT_PROMPT = """Extract these 17 fields from the text. Return STRICT JSON only, no commentary.

Fields:
applied_position, name, father, nrc, dob, religion, nationality, gender, marital,
height, weight, education, other_qual, exp_jobs, total_years, phone, address

Rules:
- exp_jobs = pipe-separated "company (Ny)" entries
- total_years = sum of experience as integer string
- phone = comma-separated all numbers
- Use null if missing

Text:
{text}
"""


def load_env():
    """Load OPENROUTER_API_KEY from .env."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                os.environ["OPENROUTER_API_KEY"] = key
                return key
    return os.environ.get("OPENROUTER_API_KEY")


def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def call_openrouter(model: str, messages: list, api_key: str, max_tokens: int = 2000) -> dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8090",
        "X-Title": "HIRE Vision Bench",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    t0 = time.time()
    with httpx.Client(timeout=180.0) as c:
        r = c.post(url, headers=headers, json=body)
    elapsed = (time.time() - t0) * 1000
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:500]}", "latency_ms": elapsed}
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {}) or {}
    return {
        "ok": True,
        "text": text,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "latency_ms": elapsed,
    }


def cost(model: str, p_tok: int, c_tok: int) -> float:
    pin, pout = PRICES.get(model, (0, 0))
    return (p_tok * pin + c_tok * pout) / 1_000_000.0


def fuzzy_eq(a: str | None, b: str | None, threshold: float = 0.80) -> bool:
    if a is None or b is None:
        return False
    a_, b_ = str(a).strip().lower(), str(b).strip().lower()
    if not a_ or not b_:
        return False
    if a_ == b_:
        return True
    return difflib.SequenceMatcher(None, a_, b_).ratio() >= threshold


def score_fields(extracted: dict, gt: dict) -> dict:
    matches = {}
    for k, v in gt.items():
        ext_v = extracted.get(k) if isinstance(extracted, dict) else None
        matches[k] = {
            "gt": v,
            "got": ext_v,
            "match": fuzzy_eq(ext_v, v),
        }
    n_match = sum(1 for m in matches.values() if m["match"])
    return {"matches": matches, "field_acc": n_match / len(gt), "n_match": n_match, "n_total": len(gt)}


def parse_json(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s)
    except Exception:
        # Best-effort: find first {...}
        i, j = s.find("{"), s.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(s[i:j+1])
            except Exception:
                return {}
        return {}


def run_model(model: str, image_path: Path, api_key: str) -> dict:
    print(f"\n=== {model} ===")
    img_b64 = encode_image(image_path)
    img_url = f"data:image/png;base64,{img_b64}"

    # Step 1: OCR
    print("  OCR…", end=" ", flush=True)
    ocr_res = call_openrouter(model, [{
        "role": "user",
        "content": [
            {"type": "text", "text": OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": img_url}},
        ],
    }], api_key, max_tokens=8000)
    if not ocr_res["ok"]:
        print(f"FAIL: {ocr_res['error']}")
        return {"model": model, "ok": False, "error": ocr_res["error"]}
    print(f"{ocr_res['latency_ms']:.0f}ms · {ocr_res['completion_tokens']} tok")

    # Step 2: STRUCTURE
    print("  STRUCT…", end=" ", flush=True)
    struct_res = call_openrouter(model, [{
        "role": "user",
        "content": STRUCT_PROMPT.format(text=ocr_res["text"]),
    }], api_key, max_tokens=4000)
    if not struct_res["ok"]:
        print(f"FAIL: {struct_res['error']}")
        return {"model": model, "ok": False, "error": struct_res["error"], "ocr_text": ocr_res["text"]}
    print(f"{struct_res['latency_ms']:.0f}ms · {struct_res['completion_tokens']} tok")

    parsed = parse_json(struct_res["text"])

    # Score
    gt = json.loads(GT_PATH.read_text())
    score = score_fields(parsed, gt)

    total_cost = cost(model, ocr_res["prompt_tokens"], ocr_res["completion_tokens"]) + \
                 cost(model, struct_res["prompt_tokens"], struct_res["completion_tokens"])
    total_lat = ocr_res["latency_ms"] + struct_res["latency_ms"]

    result = {
        "model": model,
        "ok": True,
        "ocr_text": ocr_res["text"],
        "ocr_chars": len(ocr_res["text"]),
        "struct_raw": struct_res["text"],
        "parsed": parsed,
        "score": score,
        "tokens": {
            "ocr_in": ocr_res["prompt_tokens"], "ocr_out": ocr_res["completion_tokens"],
            "struct_in": struct_res["prompt_tokens"], "struct_out": struct_res["completion_tokens"],
        },
        "cost_usd": round(total_cost, 6),
        "latency_ms": round(total_lat),
    }

    out = RUNS_DIR / f"{model.replace('/', '__')}.json"
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"  → {result['score']['n_match']}/{result['score']['n_total']} fields · ${result['cost_usd']:.5f} · {result['latency_ms']}ms")
    print(f"  saved: {out.relative_to(ROOT)}")

    append_md(result)
    return result


def append_md(result: dict):
    """Append/update row in vision_results.md."""
    headers = [
        "| Model | Field acc | OCR chars | Latency | Cost | Wins |",
        "|---|---|---|---|---|---|",
    ]
    if not RESULTS_MD.exists():
        RESULTS_MD.write_text("# Vision Bench Results\n\nDoc: bench_input.png (Myanmar driver form)\n\n" + "\n".join(headers) + "\n")

    s = result["score"]
    win_keys = [k for k, v in s["matches"].items() if v["match"]]
    row = f"| `{result['model']}` | {s['n_match']}/{s['n_total']} ({100*s['field_acc']:.0f}%) | {result['ocr_chars']} | {result['latency_ms']}ms | ${result['cost_usd']:.5f} | {', '.join(win_keys[:5]) + ('…' if len(win_keys)>5 else '')} |"

    text = RESULTS_MD.read_text()
    # Remove existing row for this model
    lines = [l for l in text.splitlines() if not l.startswith(f"| `{result['model']}`")]
    lines.append(row)
    RESULTS_MD.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--image", default=str(ROOT / "bench_input.png"))
    args = ap.parse_args()

    api_key = load_env()
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set"); sys.exit(1)

    run_model(args.model, Path(args.image), api_key)
