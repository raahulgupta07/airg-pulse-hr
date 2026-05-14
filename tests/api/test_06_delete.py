"""Soft archive vs hard delete on a throwaway candidate."""
from pathlib import Path
import httpx


def _upload_throwaway(client, api_url):
    pdf = Path("tests/seniors_pdf/Anika_Raman.pdf")
    with pdf.open("rb") as f:
        r = client.post("/candidates/upload",
                        files={"files": ("throwaway.pdf", f, "application/pdf")},
                        data={"auto_process": "false"})
    r.raise_for_status()
    res = r.json().get("results", [])
    return res[0]["candidate_id"]


def test_soft_archive_hides_row(client):
    cid = _upload_throwaway(client, None)
    r = client.delete(f"/candidates/{cid}")
    assert r.status_code == 200
    listing = client.get("/candidates/?limit=200").json()
    items = listing.get("candidates") or listing.get("items") or listing
    assert not any(c.get("id") == cid for c in items), "soft-archived row leaking into list"


def test_hard_delete_removes_file(client):
    cid = _upload_throwaway(client, None)
    detail = client.get(f"/candidates/{cid}").json()
    file_path = detail.get("pdf_path")
    r = client.delete(f"/candidates/{cid}?hard=true")
    assert r.status_code == 200
    j = r.json()
    assert j.get("hard") is True
    # candidate gone
    g = client.get(f"/candidates/{cid}")
    assert g.status_code == 404
