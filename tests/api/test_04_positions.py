"""Position listing + slug retrieval + auto-match."""

EXPECTED = {
    "Head of AI Platform",
    "Staff Backend Engineer (Payments)",
    "Director of Data Science",
}


def test_three_positions_listed(client):
    r = client.get("/positions/")
    assert r.status_code == 200
    items = r.json().get("positions") or r.json().get("items") or r.json()
    titles = {p.get("title") for p in items}
    assert EXPECTED & titles == EXPECTED, f"missing: {EXPECTED - titles}"


def test_position_by_slug(client):
    r = client.get("/positions/head-of-ai-platform")
    assert r.status_code == 200
    p = r.json()
    pos = p.get("position") if isinstance(p, dict) and "position" in p else p
    assert pos.get("title") == "Head of AI Platform"
