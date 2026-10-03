# mcp-blast-radius

**Put a policy between an AI assistant and real-world actions.**

An MCP server lets *someone else's model* call your tools. That model can be confused,
prompt-injected, or talked into things by a scammer on the other end of the conversation.
`mcp-blast-radius` gates every tool call:

- **Zones, fixed in code.** 0 talk · 1 read-only/internal · 2 a human approves each call ·
  3 emergencies, which never wait. The model never chooses the zone.
- **A Cedar policy decides.** Deny by default. Money needs approval, there's a spending cap no
  approval can exceed, and money is refused during a lockdown. You can read it, test it, and
  replace it.
- **Tripwire + lockdown.** Attack signals in any argument raise an alert and lock money down
  across turns, so the attacker's keyword-free follow-up is refused too.
- **No approval fatigue.** At most N money requests wait for a human at once.
- **Exactly once.** `approve(id)` re-checks the policy *at approval time* and runs the stored
  call once, however many times the button is tapped.

It was extracted from [Raksha](https://github.com/Aakashdeeeep/MCP), an Alexa+ MCP server that
protects elders from phone scams. Its red-team suite runs 16 attacks with a fully compromised
assistant and moves 0 rupees.

## Install

```bash
pip install mcp-blast-radius        # or: pip install -e packages/mcp-blast-radius
```

Requires the official MCP Python SDK 2.x (`MCPServer`) and `cedarpy`.

## Use

```python
from mcp.server.mcpserver import MCPServer
from mcp_blast_radius import BlastRadius, Zone

server = MCPServer("family-bank")
gate = BlastRadius(
    server,
    spending_cap=5000,
    tripwire=lambda text: ["otp"] if "otp" in text.lower() else [],
    on_approval_needed=lambda req: send_sms(daughter, f"Approve {req['tool']}? id {req['id']}"),
)

@gate.tool(zone=Zone.AUTO)
def check_balance() -> str:
    """How much money is in the account."""
    ...

@gate.tool(zone=Zone.APPROVE, moves_money=True, amount_arg="rupees")
def pay_bill(payee: str, rupees: float) -> str:
    """Pay a bill. A family member approves every payment."""
    ...

# later, from your approval webhook:
await gate.approve(request_id)      # runs pay_bill once, the policy checked again now
gate.reject(request_id)
gate.lift_lockdown()                # only a human, never the model
```

Every result carries a short text for the assistant and `structuredContent` with the
`status` (`done`, `pending_approval`, `blocked_policy`, `blocked_attack`,
`blocked_too_many_pending`) and the ids of the Cedar policies that decided. Tools are
registered with `readOnlyHint` / `destructiveHint` annotations and the zone in `_meta`.

## The default policy

```cedar
@id("autonomous")           permit when { context.zone <= 1 };
@id("after-approval")       permit when { context.zone == 2 && context.approved };
@id("panic-override")       permit when { context.zone == 3 };
@id("money-needs-approval") forbid when { context.moves_money && !context.approved };
@id("money-locked-down")    forbid when { context.moves_money && context.lockdown };
@id("spending-cap")         forbid when { context.moves_money && context.amount > 5000 };
```

(Abbreviated; see `policy.py`.) Pass `policy="..."` to use your own. The context fields are
`zone`, `moves_money`, `approved`, `amount` and `lockdown`.

## Serverless

`MemoryStore` keeps requests in-process. For Lambda or several replicas, implement `Store` on
a shared database. `claim()` must be a conditional write: it is what makes approvals run
exactly once. Raksha's DynamoDB ledger is an example.

## Example and tests

```bash
python examples/family_bank.py      # Streamable HTTP on :8100/mcp; try it with MCP Inspector
pytest                              # 8 tests: approval once-only, cap pre-check, tripwire lockdown, fatigue, panic
```

MIT licensed.
