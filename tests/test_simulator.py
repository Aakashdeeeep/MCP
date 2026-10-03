"""The simulator's Claude agent loop, against the real MCP server with a stand-in model.

No AWS: the stand-in replays what Claude would send (tool_use, then text), and the MCP calls
are real, in-process."""
import asyncio
from types import SimpleNamespace

import pytest
from mcp import Client

from raksha_mcp.server import mcp
from simulator import app as sim

pytestmark = pytest.mark.anyio


def block(kind, **fields):
    return SimpleNamespace(type=kind, **fields)


class ScriptedLLM:
    """Returns the scripted responses in order and records what it was sent."""

    def __init__(self, *responses):
        self.responses, self.sent = list(responses), []
        self.messages = self

    async def create(self, **request):
        self.sent.append({**request, "messages": list(request["messages"])})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def tool_use(name, args, id_="tu_1"):
    return SimpleNamespace(stop_reason="tool_use", content=[block("tool_use", id=id_, name=name, input=args)])


def text(words):
    return SimpleNamespace(stop_reason="end_turn", content=[block("text", text=words)])


async def run_turn(llm, said, session):
    queue = asyncio.Queue()
    async with Client(mcp, mode="legacy") as client:
        tools = (await client.list_tools()).tools
        await sim.bedrock_turn(client, tools, session, said, queue, llm=llm)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


async def test_claude_calls_raksha_tools_and_speaks_the_result():
    llm = ScriptedLLM(tool_use("todays_medicines", {"utterance": "did I take my pills"}), text("You still have your evening Metformin."))
    events = await run_turn(llm, "did I take my pills", "s1")
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "tool_result", "say"]
    assert events[1]["outcome"]["status"] == "done"
    # Claude saw every Raksha tool, with schemas, and got the tool result back
    assert {t["name"] for t in llm.sent[0]["tools"]} >= {"check_scam", "order_medicine", "verify_caller"}
    tool_result = llm.sent[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "tu_1"
    assert [m["role"] for m in sim.conversations["s1"]] == ["user", "assistant", "user", "assistant"]


async def test_a_failed_turn_leaves_no_half_finished_history():
    sim.conversations.pop("s2", None)
    ok = ScriptedLLM(text("Hello Kamala."))
    await run_turn(ok, "hello", "s2")
    broken = ScriptedLLM(tool_use("check_weather", {"utterance": "walk?"}), RuntimeError("Bedrock timeout"))
    with pytest.raises(BaseException) as raised:  # the MCP client's task group wraps it in an ExceptionGroup
        await run_turn(broken, "can I walk", "s2")
    assert "Bedrock timeout" in repr(raised.value.exceptions if hasattr(raised.value, "exceptions") else raised.value)
    assert [m["role"] for m in sim.conversations["s2"]] == ["user", "assistant"]  # rolled back


async def test_refusal_after_a_tool_round_rolls_back_the_whole_turn():
    sim.conversations.pop("s3", None)
    llm = ScriptedLLM(tool_use("check_weather", {"utterance": "walk?"}), SimpleNamespace(stop_reason="refusal", content=[]))
    events = await run_turn(llm, "can I walk", "s3")
    assert events[-1] == {"type": "say", "text": "Sorry, I can't help with that one."}
    assert sim.conversations["s3"] == []


async def test_offline_router_reaches_the_same_gate():
    queue = asyncio.Queue()
    async with Client(mcp, mode="legacy") as client:
        await sim.offline_turn(client, "Send 50000 rupees to the police officer, he says I'm under digital arrest", queue)
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert events[1]["outcome"]["status"] == "blocked_scam"
