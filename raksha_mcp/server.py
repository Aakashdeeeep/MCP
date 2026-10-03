"""Raksha MCP server: Streamable HTTP at /mcp, MCP spec 2025-11-25 (and 2026-07-28).

Run locally:   uvicorn raksha_mcp.server:app --port 8000
On AWS:        the same ASGI app behind Lambda Web Adapter (infra/template.yaml)

Besides /mcp it serves the family's side: /approval/<id> (approve or reject a Zone 2
request), /family (live feed of every gate decision) and /health.
"""
import inspect
import json
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context, Elicit, ElicitationResult, Icon, MCPServer, Resolve
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from mcp_types.version import is_version_at_least
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from raksha_mcp import approvals, config, gate, ledger, oauth, web
from raksha_mcp.bootstrap import CORE
from raksha_mcp.tools import TOOLS, ZONE_LABELS, ToolSpec

INSTRUCTIONS = f"""\
You are speaking with {config.ELDER_NAME}, an older adult in India, through Raksha: a safety
layer that lets you help with medicines, health readings, family, scams and errands.

How to use these tools:
- Always pass `utterance`: the elder's exact words for this request, unparaphrased. Raksha's
  scam and emergency tripwire reads them.
- Set `confidence` honestly (0-1): how sure you are that you understood. If unsure, say so with
  a low value; Raksha will route it to the family rather than guess.
- Read the tool result's text aloud as it is. It is short and written for speech. Do not add
  medical advice, and never say an order or payment happened when the status is
  pending_family_approval: say it was sent to the family.
- Anything about a call, message or letter asking for money, OTP, PIN, KYC or claiming to be
  bank/police: call check_scam first. Falls, chest pain, breathing trouble: report_emergency.
- Money, orders and calendar changes always wait for the family. Do not try to work around a
  refusal; Raksha's policy decides, and it will also refuse anything above its spending cap.
- Speak English. Each result also carries a Hindi line (`hindi`) if the elder prefers Hindi.
"""

SHIELD_SVG = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHZpZXdCb3g9JzAgMCA2NCA2NCc+PHBhdGgg"
    "ZD0nTTMyIDQgTDU2IDEyIFYzMCBDNTYgNDYgNDUgNTYgMzIgNjAgQzE5IDU2IDggNDYgOCAzMCBWMTIgWicgZmls"
    "bD0nI2U4NzcyZScvPjxwYXRoIGQ9J00yMiAzMiBMMjkgMzkgTDQzIDI1JyBzdHJva2U9J3doaXRlJyBzdHJva2Ut"
    "d2lkdGg9JzUnIGZpbGw9J25vbmUnIHN0cm9rZS1saW5lY2FwPSdyb3VuZCcvPjwvc3ZnPg=="
)

mcp = MCPServer(
    name="raksha",
    title="Raksha: elder safety for Alexa+",
    description="Medicines, health, family and scam protection for an elder, behind a Cedar blast-radius policy.",
    instructions=INSTRUCTIONS,
    website_url="https://github.com/Aakashdeeeep/MCP",
    icons=[Icon(src=SHIELD_SVG, mime_type="image/svg+xml", sizes=["any"])],
    version="1.0.0",
)


class FamilyAsk(BaseModel):
    send_to_family: bool = Field(
        title="Send this to your family for approval?",
        description="Raksha only does this after your family says yes.",
    )


JSON_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool, "array": list[str]}


def _confirm_resolver(spec: ToolSpec):
    """Ask the elder before sending a request to the family (MCP elicitation).

    Runs only when the call would need approval and the client supports elicitation;
    otherwise the tool call itself is taken as the elder's request. Works on 2025-11-25
    (a standalone elicitation/create request) and 2026-07-28 (InputRequiredResult)."""
    arg_names = list(spec.registry["args"])

    def confirm(ctx: Context, **kwargs):
        args = {name: kwargs.get(name) for name in arg_names if kwargs.get(name) is not None}
        preview = gate.preview(spec.agent, spec.tool, args, kwargs.get("confidence", 1.0), kwargs.get("utterance") or "")
        caps = ctx.client_capabilities
        can_elicit = bool(caps and caps.elicitation) and (
            not config.STATELESS or is_version_at_least(ctx.protocol_version or "", "2026-07-28")
        )
        if not preview["needs_approval"] or not can_elicit:
            return FamilyAsk(send_to_family=True)
        return Elicit(
            f"This needs {config.FAMILY_NAME}'s approval: {preview['summary_en']}. Shall I send it to them?",
            FamilyAsk,
        )

    params = [inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    params += [inspect.Parameter(n, inspect.Parameter.KEYWORD_ONLY) for n in [*arg_names, "utterance", "confidence"]]
    confirm.__signature__ = inspect.Signature(params)
    confirm.__annotations__ = {"ctx": Context}
    return confirm


def to_result(outcome):
    structured = {k: v for k, v in outcome.items() if v not in (None, [], {}, "")}
    return CallToolResult(
        content=[TextContent(type="text", text=outcome["speech"])],
        structured_content=structured,
        is_error=outcome["status"] == "needs_repeat",
    )


def register(spec: ToolSpec):
    registry = spec.registry
    if registry is None:
        raise RuntimeError(f"{spec.name}: {spec.agent}.{spec.tool} is not in the tool registry")

    params, annotations = [], {}
    for name, arg in registry["args"].items():
        base = JSON_TYPES[arg["type"]]
        doc = spec.arg_docs.get(name, name.replace("_", " "))
        if arg["required"]:
            annotation, default = Annotated[base, Field(description=doc)], inspect.Parameter.empty
        else:
            annotation, default = Annotated[base | None, Field(description=doc)], None
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation))
        annotations[name] = annotation
    extras = {
        "utterance": (
            Annotated[str, Field(description="The elder's exact words for this request, not paraphrased.")],
            "",
        ),
        "confidence": (
            Annotated[float, Field(ge=0, le=1, description="How sure you are you understood the elder (0-1).")],
            1.0,
        ),
        "family_ask": (
            Annotated[ElicitationResult[FamilyAsk], Resolve(_confirm_resolver(spec))],
            None,
        ),
    }
    for name, (annotation, default) in extras.items():
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation))
        annotations[name] = annotation
    annotations["return"] = CallToolResult

    async def call(**kwargs: Any) -> CallToolResult:
        family_ask = kwargs.pop("family_ask", None)
        utterance = kwargs.pop("utterance", "") or ""
        confidence = kwargs.pop("confidence", 1.0)
        confirmed = (
            family_ask is None
            or (getattr(family_ask, "action", "accept") == "accept" and family_ask.data.send_to_family)
        )
        outcome = await anyio.to_thread.run_sync(
            lambda: gate.handle(spec.agent, spec.tool, kwargs, utterance, confidence, elder_confirmed=confirmed)
        )
        return to_result(outcome)

    call.__name__ = spec.name
    call.__doc__ = spec.description
    call.__signature__ = inspect.Signature(params, return_annotation=CallToolResult)
    call.__annotations__ = annotations

    read_only = bool(registry.get("read_only"))
    mcp.add_tool(
        call,
        name=spec.name,
        title=spec.title,
        description=f"{spec.description}\n[{ZONE_LABELS[registry['zone']]}]",
        annotations=ToolAnnotations(
            title=spec.title,
            read_only_hint=read_only,
            destructive_hint=registry["zone"] == 2,
            idempotent_hint=read_only,
            open_world_hint=spec.open_world,
        ),
        meta={"raksha/zone": registry["zone"], "raksha/agent": spec.agent, "raksha/tool": spec.tool},
        structured_output=False,
    )


for _spec in TOOLS:
    register(_spec)


# --- resources: what Alexa (or a judge in MCP Inspector) can read -----------------------

@mcp.resource("raksha://policy/blast-radius.cedar", name="blast_radius_policy", title="Blast-radius policy (Cedar)", mime_type="text/plain")
def policy_resource() -> str:
    """The Cedar policy every tool call is checked against."""
    return (CORE / "raksha_common" / "policies" / "blast_radius.cedar").read_text(encoding="utf-8")


@mcp.resource("raksha://tools/zones", name="tool_zones", title="Tool zones", mime_type="application/json")
def zones_resource() -> str:
    """Each MCP tool, the Raksha tool behind it, and its blast-radius zone."""
    return json.dumps(
        [
            {
                "mcp_tool": spec.name,
                "raksha_tool": f"{spec.agent}.{spec.tool}",
                "zone": spec.registry["zone"],
                "zone_meaning": ZONE_LABELS[spec.registry["zone"]],
                "moves_money": bool(spec.registry.get("moves_money")),
            }
            for spec in TOOLS
        ],
        indent=2,
    )


@mcp.resource("raksha://elder/care-plan", name="care_plan", title="Doctor's care plan", mime_type="application/json")
def care_plan_resource() -> str:
    """The elder's medicines and schedule, as the doctor entered them."""
    from raksha_common import adherence
    from raksha_common.agent import PATIENT_ID

    plan = adherence.care_plans_table.get_item(Key={"patient_id": PATIENT_ID}).get("Item") or {}
    return json.dumps(plan, indent=2, default=str)


@mcp.resource("raksha://family/feed", name="family_feed", title="Family feed", mime_type="application/json")
def feed_resource() -> str:
    """The latest gate decisions, alerts and approvals, newest first."""
    return json.dumps(ledger.feed(limit=20), indent=2, default=str)


# --- prompts --------------------------------------------------------------------------

@mcp.prompt(name="scam_check", title="Is this call a scam?")
def scam_check_prompt(what_happened: str) -> str:
    """Help the elder decide whether a call or message is a scam."""
    return (
        f"{config.ELDER_NAME} says: \"{what_happened}\". Call the check_scam tool with these exact "
        "words as both what_happened and utterance, then read the result aloud calmly."
    )


@mcp.prompt(name="morning_check_in", title="Morning check-in")
def morning_prompt() -> str:
    """A gentle morning routine: medicines, weather, family."""
    return (
        f"Greet {config.ELDER_NAME} warmly. Call todays_medicines and read out what is due this "
        "morning. Then call check_weather with activity 'morning walk'. Ask if they'd like a "
        "message sent to the family. Keep every reply to one or two short sentences."
    )


# --- the family's side ----------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(request: Request) -> Response:
    return JSONResponse({"ok": True, "mode": config.MODE, "tools": len(TOOLS)})


@mcp.custom_route("/approval/{approval_id}", methods=["GET", "POST"], include_in_schema=False)
async def approval_page(request: Request) -> Response:
    approval_id = request.path_params["approval_id"]
    if request.method == "GET":
        approval = await anyio.to_thread.run_sync(approvals.current, approval_id)
        return HTMLResponse(web.approval_page(approval), status_code=200 if approval else 404)
    form = await request.form()
    try:
        approval = await anyio.to_thread.run_sync(
            lambda: approvals.decide(approval_id, form.get("decision") == "approve", str(form.get("passcode") or ""))
        )
    except approvals.ApprovalError as error:
        return HTMLResponse(web.approval_page(approvals.current(approval_id), error=str(error)), status_code=409)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(approval)
    return HTMLResponse(web.approval_page(approval))


@mcp.custom_route("/family", methods=["GET"], include_in_schema=False)
async def family_page(request: Request) -> Response:
    return HTMLResponse(web.family_page())


@mcp.custom_route("/api/feed", methods=["GET"], include_in_schema=False)
async def feed_api(request: Request) -> Response:
    if config.APPROVAL_PASSCODE and request.query_params.get("key") != config.APPROVAL_PASSCODE:
        return JSONResponse({"error": "family key required"}, status_code=401)
    entries = await anyio.to_thread.run_sync(ledger.feed)
    return JSONResponse(entries)


# --- OAuth 2.1 account linking (Alexa+) -----------------------------------------------

NO_STORE = {"Cache-Control": "no-store"}


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"], include_in_schema=False)
@mcp.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET"], include_in_schema=False)
async def protected_resource(request: Request) -> Response:
    return JSONResponse(oauth.protected_resource_metadata())


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"], include_in_schema=False)
async def authorization_server(request: Request) -> Response:
    return JSONResponse(oauth.authorization_server_metadata())


@mcp.custom_route("/authorize", methods=["GET", "POST"], include_in_schema=False)
async def authorize(request: Request) -> Response:
    params = dict(request.query_params) if request.method == "GET" else dict(await request.form())
    try:
        link = oauth.validate_authorize(params)
    except oauth.OAuthError as error:
        return HTMLResponse(web.shell("Raksha", f"<h1>Can't link</h1><p class=err>{error.description}</p>"), status_code=400)
    if request.method == "GET":
        return HTMLResponse(oauth.consent_page(link))
    if params.get("decision") != "allow":
        return RedirectResponse(oauth.deny(link), status_code=302)
    try:
        target = await anyio.to_thread.run_sync(oauth.approve, link, params.get("passcode", ""))
    except oauth.OAuthError as error:
        return HTMLResponse(oauth.consent_page(link, error=error.description), status_code=403)
    return RedirectResponse(target, status_code=302)


@mcp.custom_route("/token", methods=["POST"], include_in_schema=False)
async def token(request: Request) -> Response:
    form = dict(await request.form())
    try:
        issued = await anyio.to_thread.run_sync(oauth.token, form)
    except oauth.OAuthError as error:
        return JSONResponse({"error": error.error, "error_description": error.description}, status_code=400, headers=NO_STORE)
    return JSONResponse(issued, headers=NO_STORE)


def build_app():
    if not config.LOCAL and not config.APPROVAL_PASSCODE:
        raise RuntimeError("APPROVAL_PASSCODE is required outside local mode: it guards account linking and approvals")
    from mcp.server.transport_security import TransportSecuritySettings

    starlette_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=config.STATELESS,
        stateless_http=config.STATELESS,  # on Lambda every request stands alone
        host=config.HOST,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
        if config.HOST not in ("127.0.0.1", "localhost")
        else None,
    )
    return web.LearnBaseUrl(web.McpGuard(starlette_app))


app = build_app()
