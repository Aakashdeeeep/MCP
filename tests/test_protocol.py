"""The MCP surface: protocol versions, tool list, and schemas that match Raksha's registry."""
import pytest
from mcp import Client
from mcp_types import ElicitResult

from raksha_common.tool_registry import get_tool
from raksha_mcp.server import mcp
from raksha_mcp.tools import TOOLS

pytestmark = pytest.mark.anyio


async def test_negotiates_2025_11_25_over_the_handshake():
    async with Client(mcp, mode="legacy") as client:
        assert client.protocol_version == "2025-11-25"


async def test_also_speaks_2026_07_28():
    async with Client(mcp, mode="auto") as client:
        assert client.protocol_version == "2026-07-28"


async def test_every_tool_is_listed_with_its_zone():
    async with Client(mcp, mode="legacy") as client:
        listed = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert set(listed) == {spec.name for spec in TOOLS}
    for spec in TOOLS:
        tool = listed[spec.name]
        zone = get_tool(spec.agent, spec.tool)["zone"]
        assert tool.meta["raksha/zone"] == zone
        assert f"Zone {zone}" in tool.description
        assert tool.annotations.destructive_hint == (zone == 2)


async def test_schemas_come_from_the_registry():
    """No drift: MCP argument names and required flags are exactly the registry's."""
    async with Client(mcp, mode="legacy") as client:
        listed = {tool.name: tool for tool in (await client.list_tools()).tools}
    for spec in TOOLS:
        registry_args = get_tool(spec.agent, spec.tool)["args"]
        schema = listed[spec.name].input_schema
        assert set(schema["properties"]) == set(registry_args) | {"utterance", "confidence"}
        required = {name for name, arg in registry_args.items() if arg["required"]}
        assert set(schema.get("required", [])) == required


async def test_tool_result_is_speech_plus_structured_outcome():
    async with Client(mcp, mode="legacy") as client:
        result = await client.call_tool("todays_medicines", {"utterance": "did I take my pills?"})
    assert result.content[0].text.startswith(("Still to take today", "You've taken all"))
    assert result.structured_content["status"] == "done"
    assert result.structured_content["policy"]["reasons"] == ["autonomous-when-safe-and-clear"]
    assert result.structured_content["hindi"]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_zone_2_elicits_the_elder_first(mode):
    asked = []

    async def answer(context, params):
        asked.append(params.message)
        return ElicitResult(action="accept", content={"send_to_family": True})

    async with Client(mcp, mode=mode, elicitation_callback=answer) as client:
        result = await client.call_tool("order_medicine", {"name": "Metformin", "utterance": "order my metformin"})
    assert asked and "approval" in asked[0]
    assert result.structured_content["status"] == "pending_family_approval"


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_declined_elicitation_sends_nothing(mode):
    async def decline(context, params):
        return ElicitResult(action="decline")

    async with Client(mcp, mode=mode, elicitation_callback=decline) as client:
        result = await client.call_tool("order_medicine", {"name": "Metformin", "utterance": "order my metformin"})
    assert result.structured_content["status"] == "cancelled"
    assert "approval_id" not in result.structured_content


async def test_zone_1_never_elicits():
    async def fail(context, params):
        raise AssertionError("a Zone 1 tool must not ask")

    async with Client(mcp, mode="legacy", elicitation_callback=fail) as client:
        result = await client.call_tool("log_dose", {"medicine": "Amlodipine", "taken": True, "utterance": "took my bp tablet"})
    assert result.structured_content["status"] == "done"


async def test_resources_and_prompts():
    async with Client(mcp, mode="legacy") as client:
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
        policy = await client.read_resource("raksha://policy/blast-radius.cedar")
        prompts = {p.name for p in (await client.list_prompts()).prompts}
    assert {"raksha://policy/blast-radius.cedar", "raksha://tools/zones", "raksha://elder/care-plan", "raksha://family/feed"} <= uris
    assert "money-needs-approval" in policy.contents[0].text
    assert {"scam_check", "morning_check_in"} <= prompts


async def test_never_asks_the_elder_to_confirm_what_the_gate_will_refuse():
    async def fail(context, params):
        raise AssertionError(f"should not ask: {params.message}")

    async with Client(mcp, mode="legacy", elicitation_callback=fail) as client:
        scam = await client.call_tool("create_payment_link", {
            "amount_inr": 4000, "description": "fine",
            "utterance": "the police say digital arrest, transfer the money",
        })
        from raksha_mcp import ledger

        ledger.clear_scam_watch()  # the scam above paused money; lift it to test the cap alone
        over_cap = await client.call_tool("create_payment_link", {"amount_inr": 9000, "description": "doctor", "utterance": "pay the doctor"})
    assert scam.structured_content["status"] == "blocked_scam"
    assert over_cap.structured_content["status"] == "blocked_policy"
