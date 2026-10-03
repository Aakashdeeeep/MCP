"""The Cedar policy that decides whether a gated tool may run, and its evaluation.

Every decision is a Cedar authorization request:
  principal  Gate::Assistant::"assistant"
  action     Gate::Action::"RunTool"
  resource   Gate::Tool::"<tool name>"
  context    {zone, moves_money, approved, amount, lockdown}

Cedar denies by default: a tool runs only if some `permit` matches and no `forbid` does.
Pass your own policy text to BlastRadius(policy=...) to change the rules; the context
fields above are what you can write conditions on.
"""
import re

import cedarpy

DEFAULT_SPENDING_CAP = 5000

DEFAULT_POLICY = """
// Zone 0-1: conversation, read-only or internal. Runs on its own.
@id("autonomous")
permit (principal, action == Gate::Action::"RunTool", resource)
when { context.zone <= 1 };

// Zone 2: only after a human approved this exact call.
@id("after-approval")
permit (principal, action == Gate::Action::"RunTool", resource)
when { context.zone == 2 && context.approved };

// Zone 3: emergencies. Delay is the risk, so they never wait.
@id("panic-override")
permit (principal, action == Gate::Action::"RunTool", resource)
when { context.zone == 3 };

// Money never moves on the model's say-so.
@id("money-needs-approval")
forbid (principal, action == Gate::Action::"RunTool", resource)
when { context.moves_money && !context.approved };

// After a suspected attack, money stays locked until a human lifts the lockdown.
@id("money-locked-down")
forbid (principal, action == Gate::Action::"RunTool", resource)
when { context.moves_money && context.lockdown };

// A ceiling even a human approval can't exceed.
@id("spending-cap")
forbid (principal, action == Gate::Action::"RunTool", resource)
when { context.moves_money && context.amount > {{SPENDING_CAP}} };
"""


def default_policy(spending_cap=DEFAULT_SPENDING_CAP):
    return DEFAULT_POLICY.replace("{{SPENDING_CAP}}", str(int(spending_cap)))


def _policy_names(policy_text):
    """Cedar names policies policy0, policy1, ... in file order; map them to their @id."""
    code = re.sub(r"//[^\n]*", "", policy_text)
    ids = re.findall(r'(?:@id\("([^"]+)"\)\s*)?(?:permit|forbid)\s*\(', code)
    return {f"policy{i}": name or f"policy{i}" for i, name in enumerate(ids)}


class Policy:
    def __init__(self, text):
        self.text = text
        self.names = _policy_names(text)

    def decide(self, tool, *, zone, moves_money, approved, amount, lockdown):
        """Returns (allowed, [ids of the policies that decided])."""
        request = {
            "principal": 'Gate::Assistant::"assistant"',
            "action": 'Gate::Action::"RunTool"',
            "resource": f'Gate::Tool::"{tool}"',
            "context": {
                "zone": int(zone),
                "moves_money": bool(moves_money),
                "approved": bool(approved),
                "amount": int(amount),
                "lockdown": bool(lockdown),
            },
        }
        entities = [
            {"uid": {"__entity": {"type": "Gate::Assistant", "id": "assistant"}}, "attrs": {}, "parents": []},
            {"uid": {"__entity": {"type": "Gate::Tool", "id": tool}}, "attrs": {}, "parents": []},
        ]
        result = cedarpy.is_authorized(request, self.text, entities)
        if result.diagnostics.errors:
            raise RuntimeError(f"Cedar evaluation errors: {result.diagnostics.errors}")
        return result.allowed, [self.names.get(r, r) for r in result.diagnostics.reasons]
