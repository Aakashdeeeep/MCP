import re

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from mcp_blast_radius import ApprovalError, BlastRadius, Zone

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def build(**kwargs):
    server = MCPServer("test")
    asked, alerts, paid = [], [], []
    gate = BlastRadius(
        server,
        tripwire=lambda text: ["otp"] if re.search(r"\botp\b", text, re.I) else [],
        on_approval_needed=asked.append,
        on_alert=lambda tool, signals: alerts.append((tool, signals)),
        **kwargs,
    )

    @gate.tool(zone=Zone.AUTO)
    def balance() -> str:
        """Balance."""
        return "1000"

    @gate.tool(zone=Zone.APPROVE, moves_money=True, amount_arg="rupees")
    def pay(payee: str, rupees: float) -> str:
        """Pay."""
        paid.append((payee, rupees))
        return f"paid {rupees:g} to {payee}"

    @gate.tool(zone=Zone.PANIC)
    def emergency(what: str) -> str:
        """Emergency."""
        return "family alerted"

    return server, gate, asked, alerts, paid


async def call(server, name, args):
    async with Client(server, mode="legacy") as client:
        return (await client.call_tool(name, args)).structured_content


async def test_zone_1_runs_and_tools_carry_their_zone():
    server, *_ = build()
    async with Client(server, mode="legacy") as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        out = (await client.call_tool("balance", {})).structured_content
    assert out["status"] == "done" and out["policy"] == ["autonomous"]
    assert tools["pay"].meta["blast_radius/moves_money"] is True
    assert tools["pay"].annotations.destructive_hint is True
    assert tools["balance"].annotations.read_only_hint is True


async def test_money_waits_for_a_human_and_runs_once():
    server, gate, asked, _, paid = build()
    out = await call(server, "pay", {"payee": "electricity board", "rupees": 900})
    assert out["status"] == "pending_approval" and paid == []
    assert asked[0]["id"] == out["request_id"]
    done = await gate.approve(out["request_id"])
    assert done["status"] == "done" and paid == [("electricity board", 900)]
    assert done["policy"] == ["after-approval"]
    with pytest.raises(ApprovalError):
        await gate.approve(out["request_id"])


async def test_never_asks_a_human_to_approve_what_policy_forbids():
    server, _, asked, _, _ = build(spending_cap=5000)
    out = await call(server, "pay", {"payee": "x", "rupees": 5000.5})
    assert out["status"] == "blocked_policy" and out["policy"] == ["spending-cap"]
    assert asked == []


async def test_tripwire_alerts_refuses_and_locks_money_down():
    server, gate, asked, alerts, paid = build()
    attack = await call(server, "pay", {"payee": "bank officer needs OTP", "rupees": 100})
    assert attack["status"] == "blocked_attack" and alerts == [("pay", ["otp"])]
    follow_up = await call(server, "pay", {"payee": "nephew", "rupees": 100})  # no keywords now
    assert follow_up["status"] == "blocked_policy" and "money-locked-down" in follow_up["policy"]
    assert (await call(server, "balance", {}))["status"] == "done"
    gate.lift_lockdown()
    assert (await call(server, "pay", {"payee": "nephew", "rupees": 100}))["status"] == "pending_approval"
    assert asked and paid == []


async def test_lockdown_also_blocks_approving_older_requests():
    server, gate, *_ = build()
    early = await call(server, "pay", {"payee": "shop", "rupees": 300})
    gate.lockdown()
    with pytest.raises(ApprovalError, match="money-locked-down"):
        await gate.approve(early["request_id"])


async def test_approval_fatigue_limit():
    server, *_ = build(max_pending_money=2)
    statuses = [(await call(server, "pay", {"payee": f"p{i}", "rupees": 10 + i}))["status"] for i in range(3)]
    assert statuses == ["pending_approval", "pending_approval", "blocked_too_many_pending"]


async def test_panic_never_waits_even_in_lockdown():
    server, gate, *_ = build()
    gate.lockdown()
    assert (await call(server, "emergency", {"what": "fell"}))["status"] == "done"


async def test_custom_policy():
    policy = """
    @id("only-reads") permit (principal, action, resource) when { context.zone <= 1 && !context.moves_money };
    """
    server, *_ = build(policy=policy)
    assert (await call(server, "balance", {}))["status"] == "done"
    assert (await call(server, "pay", {"payee": "x", "rupees": 1}))["status"] == "blocked_policy"
