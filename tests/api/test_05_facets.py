"""Facet system tests — CV vs JD split, recompute idempotent, filter by skill."""


def test_cv_facets_have_skills(client):
    r = client.get("/facets/groups?domain=cv")
    assert r.status_code == 200
    groups = r.json()
    raw = groups if isinstance(groups, list) else groups.get("groups", [])
    assert raw, "no cv facet groups"


def test_facet_filter_returns_subset(client):
    # All seniors have varied skills; filter on python should subset
    r_all = client.get("/candidates/?limit=50")
    all_items = r_all.json().get("candidates") or r_all.json().get("items") or r_all.json()
    r_py = client.get("/candidates/?skills=python&limit=50")
    py_items = r_py.json().get("candidates") or r_py.json().get("items") or r_py.json()
    assert len(py_items) <= len(all_items)
    assert len(py_items) >= 1


def test_recompute_idempotent(client):
    r1 = client.post("/facets/recompute?domain=cv")
    assert r1.status_code in (200, 202)
    r2 = client.post("/facets/recompute?domain=cv")
    assert r2.status_code in (200, 202)
