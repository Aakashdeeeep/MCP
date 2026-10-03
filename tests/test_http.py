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
    with TestClient(app, base_url="http://localhost:8000") as test_client:
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


def test_guard_auth_and_origin(monkeypatch):
    from raksha_mcp import config

    monkeypatch.setattr(config, "REQUIRE_AUTH", True)
    monkeypatch.setattr(config, "MCP_AUTH_TOKEN", "s3cret")
    inner = Starlette(routes=[Route("/mcp", lambda r: PlainTextResponse("ok"), methods=["POST"]),
                              Route("/health", lambda r: PlainTextResponse("ok"))])
    client = TestClient(web.McpGuard(inner))
    denied = client.post("/mcp")
    assert denied.status_code == 401 and "www-authenticate" not in denied.headers
    assert client.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer s3cret"}).text == "ok"
    assert client.post("/mcp", headers={"Authorization": "Bearer s3cret", "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/mcp", headers={"Authorization": "Bearer s3cret", "Origin": "http://localhost:8080"}).text == "ok"
    assert client.get("/health").text == "ok"


def _pkce():
    import base64
    import hashlib
    import secrets

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def test_alexa_account_linking_oauth_flow(client, monkeypatch):
    """OAuth 2.1 + PKCE end to end, then the access token opens /mcp."""
    from urllib.parse import parse_qs, urlparse

    from raksha_mcp import config

    monkeypatch.setattr(config, "REQUIRE_AUTH", True)
    monkeypatch.setattr(config, "APPROVAL_PASSCODE", "2468")
    base = config.PUBLIC_BASE_URL

    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == f"{base}/mcp" and prm["authorization_servers"] == [base]
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["code_challenge_methods_supported"] == ["S256"]

    verifier, challenge = _pkce()
    params = {
        "response_type": "code", "client_id": "alexa", "redirect_uri": "https://alexa.example/callback",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "resource": f"{base}/mcp",
    }
    assert "Link Alexa" in client.get("/authorize", params=params).text
    assert client.get("/authorize", params={**params, "code_challenge_method": "plain"}).status_code == 400
    wrong = client.post("/authorize", data={**params, "decision": "allow", "passcode": "0000"}, follow_redirects=False)
    assert wrong.status_code == 403
    ok = client.post("/authorize", data={**params, "decision": "allow", "passcode": "2468"}, follow_redirects=False)
    query = parse_qs(urlparse(ok.headers["location"]).query)
    assert query["state"] == ["xyz"]
    code = query["code"][0]

    token_form = {"grant_type": "authorization_code", "code": code, "redirect_uri": params["redirect_uri"],
                  "client_id": "alexa", "code_verifier": "not-the-verifier"}
    assert client.post("/token", data=token_form).json()["error"] == "invalid_grant"  # bad PKCE burns the code
    verifier, challenge = _pkce()
    ok = client.post("/authorize", data={**params, "code_challenge": challenge, "decision": "allow", "passcode": "2468"}, follow_redirects=False)
    code = parse_qs(urlparse(ok.headers["location"]).query)["code"][0]
    tokens = client.post("/token", data={**token_form, "code": code, "code_verifier": verifier}).json()
    assert tokens["token_type"] == "Bearer"
    assert client.post("/token", data={**token_form, "code": code, "code_verifier": verifier}).status_code == 400  # single use

    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    headers = {"Accept": "application/json, text/event-stream"}
    assert client.post("/mcp", json=init, headers=headers).status_code == 401
    authed = client.post("/mcp", json=init, headers={**headers, "Authorization": f"Bearer {tokens['access_token']}"})
    assert authed.status_code == 200 and "2025-11-25" in authed.text

    refreshed = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}).json()
    assert refreshed["access_token"] != tokens["access_token"]
    assert client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}).status_code == 400
