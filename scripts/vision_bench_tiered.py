"""Tiered vision pipeline: Flash → Sonnet verifier → Opus fallback. Validate vs ground truth."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.vision_bench import (
    load_env, encode_image, call_openrouter, parse_json, score_fields,
    OCR_PROMPT, STRUCT_PROMPT, cost, GT_PATH
)

import argparse

T2_DEFAULT = "google/gemini-3-flash-preview"
T3 = "anthropic/claude-sonnet-4.6"
T4 = "anthropic/claude-opus-4.7"

# Cross-check: sample second cheap model. If critical fields differ, escalate.
T_CROSS = "anthropic/claude-haiku-4.5"

CRIT = ["dob", "phone", "nrc", "name"]

VERIFY_PROMPT = """Re-extract ONLY these fields from this image with maximum care for digits and spelling:
- name (exact spelling, every letter)
- dob (DD.MM.YYYY format)
- phone (all digits, all numbers)
- nrc (national ID, exact characters incl. last digit)

Return STRICT JSON: {"name": "...", "dob": "...", "phone": "...", "nrc": "..."}"""


def critical_ok(parsed: dict) -> tuple[bool, list]:
    """Return (all_ok, list_of_failed_fields)."""
    failed = []
    dob = parsed.get("dob") or ""
    if not re.match(r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}$", dob.replace(" ", "")):
        failed.append("dob")
    phone = parsed.get("phone") or ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 16:
        failed.append("phone")
    nrc = parsed.get("nrc") or ""
    if not re.search(r"\d{6}", nrc):
        failed.append("nrc")
    # Heuristic: known good DOB pattern check — month should be 1-12
    if dob and "." in dob:
        parts = dob.replace(" ", "").split(".")
        if len(parts) == 3:
            try:
                m = int(parts[1])
                # Force re-verify if month is at boundary digits prone to OCR confusion (5/6 commonly swapped)
                # Skip — just trust regex above
                pass
            except: pass
    name = parsed.get("name") or ""
    if len(name.split()) < 2:
        failed.append("name")
    return (len(failed) == 0), failed


def call_ocr_struct(model: str, img_url: str, api_key: str) -> dict:
    ocr = call_openrouter(model, [{
        "role": "user",
        "content": [
            {"type": "text", "text": OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": img_url}},
        ],
    }], api_key, max_tokens=8000)
    if not ocr["ok"]: return {"ok": False, "error": ocr["error"]}
    struct = call_openrouter(model, [{
        "role": "user",
        "content": STRUCT_PROMPT.format(text=ocr["text"]),
    }], api_key, max_tokens=4000)
    if not struct["ok"]: return {"ok": False, "error": struct["error"]}
    parsed = parse_json(struct["text"])
    return {
        "ok": True, "parsed": parsed, "ocr_text": ocr["text"],
        "in_tok": ocr["prompt_tokens"] + struct["prompt_tokens"],
        "out_tok": ocr["completion_tokens"] + struct["completion_tokens"],
        "latency_ms": ocr["latency_ms"] + struct["latency_ms"],
        "model": model,
    }


def call_verify(model: str, img_url: str, api_key: str) -> dict:
    """Single-call critical-field verifier (no OCR step needed)."""
    res = call_openrouter(model, [{
        "role": "user",
        "content": [
            {"type": "text", "text": VERIFY_PROMPT},
            {"type": "image_url", "image_url": {"url": img_url}},
        ],
    }], api_key, max_tokens=600)
    if not res["ok"]: return {"ok": False, "error": res["error"]}
    return {
        "ok": True, "parsed": parse_json(res["text"]),
        "in_tok": res["prompt_tokens"], "out_tok": res["completion_tokens"],
        "latency_ms": res["latency_ms"], "model": model,
    }


def run_tiered(image_path: Path, api_key: str, t2_model: str = T2_DEFAULT, cross_check: bool = True) -> dict:
    T2 = t2_model
    img_b64 = encode_image(image_path)
    img_url = f"data:image/png;base64,{img_b64}"

    print("\n=== TIERED PIPELINE ===")
    trace = {"tiers": [], "total_cost": 0.0, "total_latency_ms": 0}

    # Tier 2 — Flash full extract
    print("\n[Tier 2] gemini-3-flash …")
    r2 = call_ocr_struct(T2, img_url, api_key)
    if not r2["ok"]:
        return {"ok": False, "error": r2["error"]}
    c2 = cost(T2, r2["in_tok"], r2["out_tok"])
    trace["tiers"].append({"tier": 2, "model": T2, "cost": c2, "latency_ms": r2["latency_ms"]})
    trace["total_cost"] += c2; trace["total_latency_ms"] += r2["latency_ms"]
    print(f"  done · {r2['latency_ms']:.0f}ms · ${c2:.5f}")

    final = dict(r2["parsed"])

    # Critical-field sanity check
    ok2, failed2 = critical_ok(final)
    print(f"  critical-field check: {'PASS' if ok2 else f'FAIL on {failed2}'}")

    # Always-on verifier on critical 4 fields. Override Flash when verifier differs.
    if cross_check:
        verifier = T4  # Opus = best critical-field accuracy
        print(f"\n[Verifier] {verifier} on critical fields …")
        rv = call_verify(verifier, img_url, api_key)
        if rv["ok"]:
            cv = cost(verifier, rv["in_tok"], rv["out_tok"])
            trace["tiers"].append({"tier": "verify", "model": verifier, "cost": cv, "latency_ms": rv["latency_ms"]})
            trace["total_cost"] += cv; trace["total_latency_ms"] += rv["latency_ms"]
            print(f"  done · {rv['latency_ms']:.0f}ms · ${cv:.5f}")
            for k in CRIT:
                v = rv["parsed"].get(k)
                if v and v != final.get(k):
                    print(f"  {k}: '{final.get(k)}' → '{v}' (overridden)")
                    final[k] = v
    if ok2 and False and cross_check:  # legacy block disabled
        print(f"\n[Cross-check] {T_CROSS} (cheap independent verifier) …")
        rc = call_verify(T_CROSS, img_url, api_key)
        if rc["ok"]:
            cc = cost(T_CROSS, rc["in_tok"], rc["out_tok"])
            trace["tiers"].append({"tier": "cross", "model": T_CROSS, "cost": cc, "latency_ms": rc["latency_ms"]})
            trace["total_cost"] += cc; trace["total_latency_ms"] += rc["latency_ms"]
            print(f"  done · {rc['latency_ms']:.0f}ms · ${cc:.5f}")
            def _norm(s):
                # Strip non-alphanumeric for content compare
                return re.sub(r"[^a-zA-Z0-9]", "", str(s or "")).lower()
            disagree = []
            cross_vals = {}  # k -> verifier value
            for k in CRIT:
                a, b = _norm(final.get(k)), _norm(rc["parsed"].get(k))
                cross_vals[k] = rc["parsed"].get(k)
                if a and b and a != b:
                    import difflib
                    if difflib.SequenceMatcher(None, a, b).ratio() < 0.90:
                        disagree.append(k)
            if disagree:
                print(f"  cross-check DISAGREE on {disagree} → escalating to Sonnet for tie-break")
                ok2 = False
                failed2 = disagree
                trace["cross_vals"] = cross_vals

    if not ok2:
        # Tier 3 — Sonnet verifier on critical fields
        print(f"\n[Tier 3] claude-sonnet-4.6 verifier (failed: {failed2}) …")
        r3 = call_verify(T3, img_url, api_key)
        if r3["ok"]:
            c3 = cost(T3, r3["in_tok"], r3["out_tok"])
            trace["tiers"].append({"tier": 3, "model": T3, "cost": c3, "latency_ms": r3["latency_ms"], "fixed_fields": failed2})
            trace["total_cost"] += c3; trace["total_latency_ms"] += r3["latency_ms"]
            print(f"  done · {r3['latency_ms']:.0f}ms · ${c3:.5f}")
            # Majority-vote merge: tier2, cross, sonnet → pick value with most agreement
            cross_vals = trace.get("cross_vals", {})
            def _norm(s): return re.sub(r"[^a-zA-Z0-9]", "", str(s or "")).lower()
            for k in failed2:
                votes = [final.get(k), cross_vals.get(k), r3["parsed"].get(k)]
                votes = [v for v in votes if v]
                if not votes: continue
                # Group by normalized form
                buckets = {}
                for v in votes:
                    nk = _norm(v)
                    buckets.setdefault(nk, []).append(v)
                # Pick bucket w/ most votes; tie → prefer Sonnet (last)
                best = max(buckets.values(), key=lambda b: (len(b), buckets[_norm(r3["parsed"].get(k) or '_')] is b))
                final[k] = best[-1]  # use longest-formatted variant
                print(f"  vote on {k}: {votes} → '{best[-1]}'")
            ok3, failed3 = critical_ok(final)
            print(f"  re-check: {'PASS' if ok3 else f'STILL FAIL on {failed3}'}")
            if not ok3:
                # Tier 4 — Opus last resort
                print(f"\n[Tier 4] claude-opus-4.7 final fallback (still failing: {failed3}) …")
                r4 = call_verify(T4, img_url, api_key)
                if r4["ok"]:
                    c4 = cost(T4, r4["in_tok"], r4["out_tok"])
                    trace["tiers"].append({"tier": 4, "model": T4, "cost": c4, "latency_ms": r4["latency_ms"], "fixed_fields": failed3})
                    trace["total_cost"] += c4; trace["total_latency_ms"] += r4["latency_ms"]
                    print(f"  done · {r4['latency_ms']:.0f}ms · ${c4:.5f}")
                    for k in failed3:
                        v = r4["parsed"].get(k)
                        if v: final[k] = v

    # Score against ground truth
    gt = json.loads(GT_PATH.read_text())
    score = score_fields(final, gt)

    # Critical-field exact check
    def _ex(g, t):
        return str(g or "").replace(" ", "").lower() == str(t or "").replace(" ", "").lower()
    crit_exact = sum(1 for k in ["dob", "phone", "nrc"] if _ex(final.get(k), gt[k]))

    result = {
        "ok": True,
        "final_parsed": final,
        "score": score,
        "critical_exact": f"{crit_exact}/3",
        "trace": trace,
        "total_cost_usd": round(trace["total_cost"], 6),
        "total_latency_ms": round(trace["total_latency_ms"]),
    }
    out = ROOT / "bench" / "runs" / "TIERED.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--t2", default=T2_DEFAULT, help="Tier 2 model")
    ap.add_argument("--no-cross", action="store_true", help="Skip cross-check verifier")
    ap.add_argument("--image", default=str(ROOT / "bench_input.png"))
    args = ap.parse_args()

    api_key = load_env()
    if not api_key: print("ERROR: no OPENROUTER_API_KEY"); sys.exit(1)
    img = Path(args.image)
    r = run_tiered(img, api_key, t2_model=args.t2, cross_check=not args.no_cross)
    if not r.get("ok"):
        print(f"FAIL: {r.get('error')}")
        sys.exit(1)
    print("\n" + "="*60)
    print(f"TIERED RESULT: {r['score']['n_match']}/17 fields · "
          f"crit-exact: {r['critical_exact']} · "
          f"${r['total_cost_usd']:.5f} · {r['total_latency_ms']}ms")
    print("="*60)
    print("\nFinal parsed:")
    print(json.dumps(r["final_parsed"], indent=2, ensure_ascii=False))
    print("\nTier trace:")
    for t in r["trace"]["tiers"]:
        print(f"  T{t['tier']} {t['model']}: ${t['cost']:.5f} · {t['latency_ms']:.0f}ms"
              + (f" · fixed {t.get('fixed_fields')}" if t.get('fixed_fields') else ""))
