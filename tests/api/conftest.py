import httpx
import pytest

API = "http://localhost:8090/api"


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=API, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="session")
def api_url():
    return API
