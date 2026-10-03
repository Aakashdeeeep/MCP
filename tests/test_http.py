"""The HTTP side: health, bearer auth on /mcp, the family's approval page and feed."""
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from raksha_mcp import gate, web
from raksha_mcp.server import app


@pytest.fixture(scope="module")
def client():
    # one lifespan for the module: the MCP session manager can only start once per app
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_family_pages(client):
    assert client.get("/health").json()["ok"] is True
    assert "family feed" in client.get("/family").text
    assert isinstance(client.get("/api/feed").json(), list)


def test_approval_page_approves_once(client):
    out = gate.handle("pharmacy-order", "order_medicine", {"name": "Metformin"}, "<script>alert(1)</script>")
    page = client.get(f"/approval/{out['approval_id']}")
    assert page.status_code == 200 and "Approve" in page.text
    assert "<script>alert(1)" not in page.text  # the elder's words are escaped
    first = client.post(f"/approval/{out['approval_id']}", data={"decision": "approve"})
    assert "Approved and done" in first.text
    again = client.post(f"/approval/{out['approval_id']}", data={"decision": "approve"})
    assert again.status_code == 409
    assert client.get("/approval/nope").status_code == 404


def test_bearer_guard():
    inner = Starlette(routes=[Route("/mcp", lambda r: PlainTextResponse("ok"), methods=["POST"]),
                              Route("/health", lambda r: PlainTextResponse("ok"))])
    client = TestClient(web.BearerAuth(inner, "s3cret"))
    assert client.post("/mcp").status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer s3cret"}).text == "ok"
    assert client.get("/health").text == "ok"
