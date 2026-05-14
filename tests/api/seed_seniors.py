"""Seed senior CVs + JDs + positions into the running API."""
import sys
import time
from pathlib import Path

import httpx

from tests.api.seniors_data import SENIORS, JDS, POSITIONS
from tests.api.build_pdfs import build_all

API = "http://localhost:8090/api"
TIMEOUT = 60.0


def upload_cv(client: httpx.Client, pdf_path: Path) -> dict:
    with pdf_path.open("rb") as f:
        files = {"files": (pdf_path.name, f, "application/pdf")}
        data = {"auto_process": "true"}
        r = client.post(f"{API}/candidates/upload", files=files, data=data, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def wait_pipeline(client: httpx.Client, candidate_id: int, max_wait_s: int = 300) -> dict:
    """Poll until candidate.is_processed=true or status=error."""
    start = time.time()
    while time.time() - start < max_wait_s:
        r = client.get(f"{API}/candidates/{candidate_id}", timeout=TIMEOUT)
        if r.status_code == 200:
            j = r.json()
            cand = j.get("candidate") if isinstance(j, dict) and "candidate" in j else j
            if cand.get("is_processed"):
                return {"ok": True, "candidate": cand, "elapsed_s": round(time.time() - start, 1)}
            if cand.get("processing_status") == "error":
                return {"ok": False, "error": cand.get("processing_error"), "elapsed_s": round(time.time() - start, 1)}
        time.sleep(3)
    return {"ok": False, "error": "timeout", "elapsed_s": max_wait_s}


def create_jd(client: httpx.Client, jd: dict) -> dict:
    r = client.post(f"{API}/jds/", json=jd, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def create_position(client: httpx.Client, pos: dict) -> dict:
    r = client.post(f"{API}/positions/", json=pos, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def main():
    print("=" * 60)
    print("HIRE — SENIOR FIXTURE SEED")
    print("=" * 60)

    print("\n[1/4] Building CV PDFs...")
    pdf_paths = build_all()

    headers = {}  # DEV_MODE on, no auth needed
    with httpx.Client(headers=headers) as client:
        # Health
        try:
            r = client.get(f"{API}/health", timeout=5.0)
            print(f"\n[2/4] API health: {r.status_code} {r.json() if r.status_code == 200 else r.text}")
        except Exception as e:
            print(f"\nERROR — API not reachable at {API}: {e}")
            sys.exit(1)

        # Upload CVs
        print(f"\n[3/4] Uploading {len(pdf_paths)} senior CVs...")
        uploaded = []
        for p in pdf_paths:
            try:
                resp = upload_cv(client, p)
                results = resp.get("results", []) if isinstance(resp, dict) else resp
                if results:
                    cid = results[0].get("candidate_id")
                    print(f"  ✓ {p.name:40s} → candidate_id={cid}")
                    uploaded.append((p.name, cid))
                else:
                    print(f"  ✗ {p.name:40s} → no candidate_id in response: {resp}")
            except Exception as e:
                print(f"  ✗ {p.name:40s} → {e}")

        # Wait pipelines
        print(f"\n  Waiting for {len(uploaded)} pipelines to complete (max 5min each)...")
        done = 0
        errors = 0
        for name, cid in uploaded:
            res = wait_pipeline(client, cid, max_wait_s=300)
            if res["ok"]:
                done += 1
                print(f"  ✓ {name:40s} done in {res['elapsed_s']}s")
            else:
                errors += 1
                print(f"  ✗ {name:40s} error after {res['elapsed_s']}s: {res.get('error')}")
        print(f"\n  Pipelines: {done} done, {errors} errors")

        # JDs
        print(f"\n[4/4] Creating {len(JDS)} senior JDs...")
        jd_ids = []
        for jd in JDS:
            try:
                resp = create_jd(client, jd)
                jd_id = resp.get("jd_id")
                print(f"  ✓ {jd['title']:40s} → jd_id={jd_id}")
                jd_ids.append(jd_id)
            except Exception as e:
                print(f"  ✗ {jd['title']:40s} → {e}")

        # Positions
        print(f"\n     Creating {len(POSITIONS)} positions...")
        pos_ids = []
        for pos in POSITIONS:
            try:
                resp = create_position(client, pos)
                pid = resp.get("position_id")
                slug = resp.get("slug")
                print(f"  ✓ {pos['title']:40s} → id={pid} slug={slug}")
                pos_ids.append((pid, slug))
            except Exception as e:
                print(f"  ✗ {pos['title']:40s} → {e}")

    print("\n" + "=" * 60)
    print(f"SEED COMPLETE: {done} CVs, {len(jd_ids)} JDs, {len(pos_ids)} positions")
    print("=" * 60)
    print("View at:")
    print("  http://localhost:8090/candidates")
    print("  http://localhost:8090/jds")
    print("  http://localhost:8090/")


if __name__ == "__main__":
    main()
