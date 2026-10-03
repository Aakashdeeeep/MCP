"""Alexa+ simulator: a voice assistant that reaches Raksha only through MCP.

It plays the part Alexa+ plays in production. It is a separate process, it connects to the
Raksha MCP server over Streamable HTTP (2025-11-25 by default, like Alexa+), discovers the
tools with tools/list, and lets a model decide which to call. Nothing about Raksha is
hard-coded here, so whatever works in the simulator works for any MCP client.

  SIM_AGENT=bedrock  Claude on Amazon Bedrock plans the tool calls (needs AWS credentials)
  SIM_AGENT=offline  a keyword router picks one tool per turn (no LLM, no credentials)

Run:  uvicorn simulator.app:app --port 8080   (with the MCP server on :8000)
"""
import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import ElicitResult
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from simulator import offline_router

MCP_URL = os.environ.get("RAKSHA_MCP_URL", "http://localhost:8000/mcp")
MCP_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
MCP_MODE = os.environ.get("SIM_MCP_MODE", "legacy")  # legacy = 2025-11-25 handshake, like Alexa+
AGENT = os.environ.get("SIM_AGENT", "bedrock" if os.environ.get("RAKSHA_BEDROCK") == "1" else "offline")
MODEL_ID = os.environ.get("SIM_MODEL_ID", "anthropic.claude-opus-5-5")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "us-east-1"))
SERVER_BASE = MCP_URL.rsplit("/mcp", 1)[0]
# The family passcode, so the simulator's phone panel works against a deployed server too.
# The simulator is a local demo tool: don't expose it publicly with this set.
FAMILY_KEY = os.environ.get("SIM_FAMILY_KEY", "")
STATIC = Path(__file__).parent / "static"
MAX_TOOL_ROUNDS = 6

PERSONA = (
    "You are Alexa, a warm voice assistant in the home of an elderly woman in India. Speak in "
    "short, simple English sentences: this is read aloud. Use Raksha's tools for anything about "
    "her medicines, health, family, money, errands or anything that might be a scam. Pass her exact "
    "words as `utterance` on every call and an honest `confidence`. When a tool result has text, say "
    "that text (you may add one short friendly sentence). Never claim something was ordered or paid "
    "when the result status is pending_family_approval."
)

conversations = {}  # session id -> Anthropic messages list
pending_elicitations = {}  # elicitation id -> Future


def mcp_client(elicitation_callback):
    headers = {"Authorization": f"Bearer {MCP_TOKEN}"} if MCP_TOKEN else {}
    transport = streamable_http_client(MCP_URL, http_client=httpx2.AsyncClient(headers=headers, timeout=60))
    return Client(transport, mode=MCP_MODE, elicitation_callback=elicitation_callback)


def sse(event):
    return f"data: {json.dumps(event, default=str)}\n\n"


async def turn(request: Request) -> Response:
    body = await request.json()
    text = (body.get("text") or "").strip()[:1000]
    session = body.get("session") or uuid.uuid4().hex
    queue: asyncio.Queue = asyncio.Queue()

    async def ask_elder(context, params):
        """MCP elicitation: Raksha asks the elder something. Shown and spoken in the browser."""
        elicitation_id = uuid.uuid4().hex[:8]
        future = asyncio.get_running_loop().create_future()
        pending_elicitations[elicitation_id] = future
        await queue.put({"type": "elicit", "id": elicitation_id, "message": params.message})
        try:
            accepted = await asyncio.wait_for(future, timeout=90)
        except asyncio.TimeoutError:
            accepted = False
        finally:
            pending_elicitations.pop(elicitation_id, None)
        if accepted:
            return ElicitResult(action="accept", content={"send_to_family": True})
        return ElicitResult(action="decline")

    async def run():
        try:
            async with mcp_client(ask_elder) as client:
                tools = (await client.list_tools()).tools
                await queue.put({"type": "connected", "protocol": client.protocol_version, "tools": len(tools), "agent": AGENT})
                if AGENT == "bedrock":
                    await bedrock_turn(client, tools, session, text, queue)
                else:
                    await offline_turn(client, text, queue)
        except Exception as error:  # noqa: BLE001 - surface it in the UI instead of hanging
            await queue.put({"type": "error", "message": f"{type(error).__name__}: {error}"})
        finally:
            await queue.put(None)

    async def stream():
        task = asyncio.create_task(run())
        while (event := await queue.get()) is not None:
            yield sse(event)
        await task
        yield sse({"type": "done", "session": session})

    return StreamingResponse(stream(), media_type="text/event-stream")


async def call_tool(client, name, args, queue):
    await queue.put({"type": "tool_call", "name": name, "args": args})
    result = await client.call_tool(name, args)
    outcome = result.structured_content or {}
    speech = result.content[0].text if result.content else ""
    await queue.put({"type": "tool_result", "name": name, "speech": speech, "outcome": outcome, "is_error": result.is_error})
    return speech, outcome


async def offline_turn(client, text, queue):
    choice = offline_router.route(text)
    if choice is None:
        await queue.put({"type": "say", "text": "I'm here. You can ask about your medicines, your family, the weather, or tell me about a suspicious call."})
        return
    name, args = choice
    speech, outcome = await call_tool(client, name, {**args, "utterance": text, "confidence": 0.9}, queue)
    offline_router.remember_approval(outcome)
    await queue.put({"type": "say", "text": speech})


async def bedrock_turn(client, tools, session, text, queue):
    from anthropic import AsyncAnthropicBedrockMantle

    llm = AsyncAnthropicBedrockMantle(aws_region=BEDROCK_REGION)
    tool_defs = [
        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in tools
    ]
    instructions = getattr(client, "instructions", None) or ""
    messages = conversations.setdefault(session, [])
    messages.append({"role": "user", "content": text})

    for _ in range(MAX_TOOL_ROUNDS):
        response = await llm.messages.create(
            model=MODEL_ID,
            max_tokens=4000,
            system=f"{PERSONA}\n\n{instructions}",
            tools=tool_defs,
            messages=messages,
            output_config={"effort": "low"},  # a voice turn: keep it quick
        )
        if response.stop_reason == "refusal":
            await queue.put({"type": "say", "text": "Sorry, I can't help with that one."})
            messages.pop()
            return
        messages.append({"role": "assistant", "content": response.content})
        uses = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not uses:
            spoken = " ".join(block.text for block in response.content if block.type == "text").strip()
            await queue.put({"type": "say", "text": spoken or "Okay."})
            return
        results = []
        for use in uses:
            speech, outcome = await call_tool(client, use.name, dict(use.input), queue)
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": json.dumps({"say": speech, **outcome}, default=str)})
        messages.append({"role": "user", "content": results})
    await queue.put({"type": "say", "text": "Let me stop there. Could you ask me again?"})


async def answer_elicitation(request: Request) -> Response:
    future = pending_elicitations.get(request.path_params["elicitation_id"])
    if future is None or future.done():
        return JSONResponse({"ok": False}, status_code=404)
    future.set_result(bool((await request.json()).get("accept")))
    return JSONResponse({"ok": True})


async def proxy_feed(request: Request) -> Response:
    async with httpx2.AsyncClient(timeout=10) as http:
        upstream = await http.get(f"{SERVER_BASE}/api/feed", params={"key": request.query_params.get("key") or FAMILY_KEY})
    return Response(upstream.content, status_code=upstream.status_code, media_type="application/json")


async def proxy_scam_watch(request: Request) -> Response:
    """The family panel's banner: is money paused, and the button that lifts it."""
    params = {"key": request.query_params.get("key") or FAMILY_KEY}
    async with httpx2.AsyncClient(timeout=10) as http:
        upstream = await http.request(request.method, f"{SERVER_BASE}/api/scam-watch", params=params)
    return Response(upstream.content, status_code=upstream.status_code, media_type="application/json")


async def proxy_decision(request: Request) -> Response:
    """The family panel's Approve / Reject buttons post to the MCP server's approval page."""
    body = await request.json()
    async with httpx2.AsyncClient(timeout=30) as http:
        upstream = await http.post(
            f"{SERVER_BASE}/approval/{request.path_params['approval_id']}",
            data={"decision": "approve" if body.get("approve") else "reject", "passcode": body.get("passcode") or FAMILY_KEY},
            headers={"Accept": "application/json"},
        )
    if upstream.headers.get("content-type", "").startswith("application/json"):
        return Response(upstream.content, status_code=upstream.status_code, media_type="application/json")
    return JSONResponse({"error": "already answered or not found"}, status_code=upstream.status_code)


async def info(request: Request) -> Response:
    return JSONResponse({"agent": AGENT, "model": MODEL_ID if AGENT == "bedrock" else None, "mcp_url": MCP_URL, "mode": MCP_MODE})


async def index(request: Request) -> Response:
    return FileResponse(STATIC / "index.html")


app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/info", info),
        Route("/api/turn", turn, methods=["POST"]),
        Route("/api/elicit/{elicitation_id}", answer_elicitation, methods=["POST"]),
        Route("/api/feed", proxy_feed),
        Route("/api/scam-watch", proxy_scam_watch, methods=["GET", "DELETE"]),
        Route("/api/approval/{approval_id}", proxy_decision, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
)
