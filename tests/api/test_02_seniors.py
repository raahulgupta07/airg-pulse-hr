"""Verify seeded seniors made it through pipeline + extraction."""
import pytest

EXPECTED_NAMES = {
    "Anika Raman", "Diego Hernandez", "Priya Sharma", "Marcus Johnson",
    "Yuki Tanaka", "Sofia Rossi", "Ahmed Al-Mansour", "Elena Volkov",
}


def test_eight_seniors_listed(client):
    r = client.get("/candidates/?limit=50")
    assert r.status_code == 200
    j = r.json()
    items = j.get("candidates") or j.get("items") or j
    names = {c.get("name") for c in items if isinstance(c, dict)}
    found = EXPECTED_NAMES & names
    assert len(found) == 8, f"missing: {EXPECTED_NAMES - names}"


def test_anika_extraction_quality(client):
    r = client.get("/candidates/?limit=50")
    items = r.json().get("candidates") or r.json().get("items") or r.json()
    anika = next((c for c in items if c.get("name") == "Anika Raman"), None)
    assert anika, "Anika not found"
    detail = client.get(f"/candidates/{anika['id']}").json()
    assert detail.get("email") == "anika.raman@example.com"
    assert detail.get("total_experience_years") and detail["total_experience_years"] >= 10
    skills = detail.get("skills_technical") or []
    assert any("go" in s.lower() for s in skills)
    assert any("kubernetes" in s.lower() for s in skills)


def test_all_extracted_fields(client):
    """Pipeline outcome via list payload — current_role/company/years populated."""
    r = client.get("/candidates/?limit=50")
    items = r.json().get("candidates") or r.json().get("items") or r.json()
    seniors = [c for c in items if c.get("name") in EXPECTED_NAMES]
    assert len(seniors) == 8
    no_role = [c["name"] for c in seniors if not c.get("current_role")]
    no_years = [c["name"] for c in seniors if not c.get("total_experience_years")]
    assert not no_role, f"no current_role: {no_role}"
    assert not no_years, f"no years: {no_years}"


def test_each_senior_is_processed_via_detail(client):
    r = client.get("/candidates/?limit=50")
    items = r.json().get("candidates") or r.json().get("items") or r.json()
    for c in items:
        if c.get("name") not in EXPECTED_NAMES:
            continue
        d = client.get(f"/candidates/{c['id']}").json()
        assert d.get("is_processed") is True, f"{c['name']} not processed"
