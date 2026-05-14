"""Smoke: every key GET returns 2xx + JSON."""
import pytest

GETS = [
    "/health",
    "/ai-status",
    "/candidates/",
    "/candidates/pending",
    "/jds/",
    "/positions/",
    "/facets/groups?domain=cv",
    "/facets/groups?domain=jd",
    "/facets?type=skill&limit=10",
    "/analytics/overview",
    "/notifications/",
    "/pools/",
    "/saved-searches/",
]


@pytest.mark.parametrize("path", GETS)
def test_get_smoke(client, path):
    r = client.get(path)
    assert r.status_code in (200, 204), f"{path} → {r.status_code} {r.text[:200]}"
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
        r.json()  # parses
