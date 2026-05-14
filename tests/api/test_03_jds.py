"""JD listing + filter + facet mining."""

EXPECTED_JD_TITLES = {
    "Head of AI Platform", "VP of Engineering", "Staff Backend Engineer",
    "Director of Data Science", "Principal Site Reliability Engineer",
}


def test_five_jds_listed(client):
    r = client.get("/jds/?limit=50")
    assert r.status_code == 200
    items = r.json().get("jds") or r.json().get("items") or r.json()
    titles = {j.get("title") for j in items}
    found = EXPECTED_JD_TITLES & titles
    assert len(found) == 5, f"missing JDs: {EXPECTED_JD_TITLES - titles}"


def test_jd_facets_mined(client):
    r = client.get("/facets/groups?domain=jd")
    assert r.status_code == 200
    body = r.json()
    groups = body.get("groups") if isinstance(body, dict) else body
    assert groups, "no jd facet groups returned"
    # at least one of jd_skill / jd_dept / jd_location should be present
    keys = set(groups.keys()) if isinstance(groups, dict) else {g.get("type") for g in groups}
    assert keys & {"jd_skill", "jd_dept", "jd_location", "jd_seniority", "jd_employment_type"}


def test_filter_jds_by_seniority(client):
    r = client.get("/jds/?seniorities=Director,VP")
    assert r.status_code == 200


def test_jd_detail(client):
    r = client.get("/jds/?limit=50")
    items = r.json().get("jds") or r.json().get("items") or r.json()
    jd = next((j for j in items if j.get("title") == "Head of AI Platform"), None)
    assert jd, "Head of AI Platform JD missing"
    detail = client.get(f"/jds/{jd['id']}").json()
    assert detail.get("title") == "Head of AI Platform"
    assert "PyTorch" in (detail.get("jd_text") or "") or "pytorch" in (detail.get("jd_text") or "").lower()
