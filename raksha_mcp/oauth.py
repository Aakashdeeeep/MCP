"""OAuth 2.1 account linking for Alexa+ (authorization code + PKCE S256).

Alexa+ links an add-on to a user's account through OAuth. Here "linking" means a family
member, holding the family passcode, lets this Alexa act for the elder. What's served:

  /.well-known/oauth-protected-resource[/mcp]   RFC 9728 metadata for the /mcp resource
  /.well-known/oauth-authorization-server       RFC 8414 metadata (S256 only)
  /authorize                                    consent page: family passcode -> one-time code
  /token                                        code + PKCE verifier -> access + refresh token

Codes and tokens are stored hashed in the ledger table with a DynamoDB TTL, so any Lambda
instance can verify them. Public clients only (no client secret); PKCE S256 is mandatory,
codes are single-use, refresh tokens rotate. Unauthenticated /mcp calls get a bare 401
(no WWW-Authenticate header), per the Alexa+ MCP checklist.
"""
import base64
import hashlib
import hmac
import html
import json
import secrets
import time
import urllib.parse

from raksha_mcp import config, ledger

CODE_TTL = 600
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
SCOPE = "raksha"


def canonical_resource():
    return f"{config.PUBLIC_BASE_URL}/mcp"


def protected_resource_metadata():
    return {
        "resource": canonical_resource(),
        "authorization_servers": [config.PUBLIC_BASE_URL],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Raksha",
    }


def authorization_server_metadata():
    base = config.PUBLIC_BASE_URL
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
    }


class OAuthError(Exception):
    def __init__(self, error, description):
        super().__init__(description)
        self.error, self.description = error, description


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _put(kind, secret, record, ttl):
    now = int(time.time())
    ledger.table().put_item(
        Item={"pk": f"OAUTH#{kind}#{_hash(secret)}", "sk": "META", "data": json.dumps(record), "ttl": now + ttl}
    )


def _take(kind, secret):
    """Read and delete in one step, so a code or refresh token works exactly once."""
    try:
        item = ledger.table().delete_item(
            Key={"pk": f"OAUTH#{kind}#{_hash(secret)}", "sk": "META"},
            ConditionExpression="attribute_exists(pk)",
            ReturnValues="ALL_OLD",
        ).get("Attributes")
    except ledger.table().meta.client.exceptions.ConditionalCheckFailedException:
        return None
    if not item or int(item["ttl"]) < time.time():
        return None
    return json.loads(item["data"])


def redirect_allowed(uri):
    try:
        parts = urllib.parse.urlparse(uri)
    except ValueError:
        return False
    if parts.fragment:
        return False
    if config.OAUTH_REDIRECT_HOSTS:
        return parts.scheme == "https" and parts.hostname in config.OAUTH_REDIRECT_HOSTS
    if parts.scheme == "https" and parts.hostname:
        return True
    return parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")


def validate_authorize(params):
    """Check an /authorize request. Errors that make the redirect untrustworthy raise."""
    redirect_uri = params.get("redirect_uri", "")
    if not params.get("client_id"):
        raise OAuthError("invalid_request", "client_id is required")
    if not redirect_allowed(redirect_uri):
        raise OAuthError("invalid_request", "redirect_uri is not allowed")
    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "response_type must be code")
    if not params.get("code_challenge") or params.get("code_challenge_method") != "S256":
        raise OAuthError("invalid_request", "PKCE with code_challenge_method=S256 is required")
    resource = params.get("resource")
    if resource and resource.rstrip("/") != canonical_resource():
        raise OAuthError("invalid_target", "resource must be this server's /mcp endpoint")
    return {
        "client_id": params["client_id"],
        "redirect_uri": redirect_uri,
        "code_challenge": params["code_challenge"],
        "state": params.get("state", ""),
        "scope": SCOPE,
        "resource": canonical_resource(),
    }


def approve(request, passcode):
    """The family said yes on the consent page. Returns the redirect URL carrying the code."""
    if config.APPROVAL_PASSCODE and not hmac.compare_digest(passcode or "", config.APPROVAL_PASSCODE):
        raise OAuthError("access_denied", "Wrong family passcode.")
    code = secrets.token_urlsafe(32)
    _put("CODE", code, request, CODE_TTL)
    ledger.record("account_linked", f"Alexa account linking approved for client {request['client_id']}")
    return _redirect(request["redirect_uri"], {"code": code, "state": request["state"]})


def deny(request):
    return _redirect(request["redirect_uri"], {"error": "access_denied", "state": request["state"]})


def _redirect(uri, query):
    query = {k: v for k, v in query.items() if v}
    return uri + ("&" if "?" in uri else "?") + urllib.parse.urlencode(query)


def token(form):
    grant = form.get("grant_type")
    if grant == "authorization_code":
        record = _take("CODE", form.get("code", ""))
        if record is None:
            raise OAuthError("invalid_grant", "code is invalid, used or expired")
        if form.get("redirect_uri") != record["redirect_uri"]:
            raise OAuthError("invalid_grant", "redirect_uri does not match")
        if form.get("client_id") and form["client_id"] != record["client_id"]:
            raise OAuthError("invalid_grant", "client_id does not match")
        verifier = form.get("code_verifier", "")
        digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if not verifier or not hmac.compare_digest(digest, record["code_challenge"]):
            raise OAuthError("invalid_grant", "PKCE verification failed")
        resource = form.get("resource")
        if resource and resource.rstrip("/") != record["resource"]:
            raise OAuthError("invalid_target", "resource does not match")
        return _issue(record["client_id"], record["scope"], record["resource"])
    if grant == "refresh_token":
        record = _take("REFRESH", form.get("refresh_token", ""))
        if record is None:
            raise OAuthError("invalid_grant", "refresh_token is invalid or expired")
        return _issue(record["client_id"], record["scope"], record["resource"])
    raise OAuthError("unsupported_grant_type", "use authorization_code or refresh_token")


def _issue(client_id, scope, resource):
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    grant = {"client_id": client_id, "scope": scope, "resource": resource}
    _put("ACCESS", access, grant, ACCESS_TTL)
    _put("REFRESH", refresh, grant, REFRESH_TTL)
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
        "refresh_token": refresh,
        "scope": scope,
    }


def access_token_valid(value):
    if not value:
        return False
    item = ledger.table().get_item(Key={"pk": f"OAUTH#ACCESS#{_hash(value)}", "sk": "META"}).get("Item")
    return bool(item) and int(item["ttl"]) >= time.time()


def consent_page(request, error=None):
    from raksha_mcp.web import shell

    e = html.escape
    passcode = (
        "<p><label>Family passcode <input name=passcode type=password required autocomplete=off></label></p>"
        if config.APPROVAL_PASSCODE
        else ""
    )
    hidden = "".join(f"<input type=hidden name={e(k)} value='{e(v)}'>" for k, v in request.items())
    return shell(
        "Link Alexa to Raksha",
        f"<h1><span class=brand>Raksha</span> · link Alexa</h1>"
        f"<p class=sub>Let this Alexa ask Raksha for {e(config.ELDER_NAME)}: medicines, health readings, "
        "family messages and scam checks. Orders and payments still need your approval every time.</p>"
        + (f"<p class=err>{e(error)}</p>" if error else "")
        + f"<form method=post>{hidden}{passcode}<div class=row>"
        "<button class='btn approve' name=decision value=allow>Link Alexa</button>"
        "<button class='btn reject' name=decision value=deny>Cancel</button></div></form>"
        f"<p class=detail>Requested by client: {e(request['client_id'])}</p>",
    )
