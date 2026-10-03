"""Blast-radius authorization: evaluate policies/blast_radius.cedar before any tool runs.

Cedar (AWS's open-source policy language) keeps the safety rules in one readable file
instead of scattered if-statements. The tool's zone and moves_money flag come from the
registry; approval and amount come from the running task.

If the Cedar engine can't be loaded (e.g. a packaging problem in Lambda), the same rules
run in plain Python (`python_decision`) so the demo still enforces them. Tests prove the
two agree on every combination.
"""
import json
import math
import re
from pathlib import Path

from raksha_common.tool_registry import get_tool

try:
    import cedarpy
except ImportError:  # pragma: no cover - exercised only when the wheel is missing
    cedarpy = None

POLICY_DIR = Path(__file__).parent / "policies"
POLICIES = (POLICY_DIR / "blast_radius.cedar").read_text(encoding="utf-8")
SCHEMA = json.loads((POLICY_DIR / "schema.cedarschema.json").read_text(encoding="utf-8"))
SPENDING_CAP_INR = 5000


def policy_ids(policy_text):
    """Cedar names policies policy0, policy1... in file order; map those to the @id annotations."""
    code = re.sub(r"//[^\n]*", "", policy_text)
    ids = re.findall(r'(?:@id\("([^"]+)"\)\s*)?(?:permit|forbid)\s*\(', code)
    return {f"policy{i}": name or f"policy{i}" for i, name in enumerate(ids)}


POLICY_NAMES = policy_ids(POLICIES)


def build_request(task, event):
    """Returns (resource facts, context) for this task, or raises ValueError for an unknown tool."""
    spec = get_tool(task.get("agent"), task.get("tool"))
    if spec is None:
        raise ValueError(f"unknown tool {task.get('agent')}.{task.get('tool')}")
    amount = (task.get("args") or {}).get("amount_inr") or 0
    resource = {
        "agent": task["agent"],
        "zone": spec["zone"],
        "moves_money": bool(spec.get("moves_money")),
    }
    context = {
        "effective_zone": int(task.get("zone", spec["zone"])),
        "approved": bool((event.get("approval") or {}).get("approved")),
        "amount_inr": int(math.ceil(amount)) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else 0,
    }
    return resource, context


def cedar_decision(resource, context, tool_uid):
    request = {
        "principal": 'Raksha::Elder::"elder"',
        "action": 'Raksha::Action::"RunTool"',
        "resource": f'Raksha::Tool::"{tool_uid}"',
        "context": context,
    }
    entities = [
        {"uid": {"__entity": {"type": "Raksha::Elder", "id": "elder"}}, "attrs": {}, "parents": []},
        {"uid": {"__entity": {"type": "Raksha::Tool", "id": tool_uid}}, "attrs": resource, "parents": []},
    ]
    result = cedarpy.is_authorized(request, POLICIES, entities, schema=SCHEMA)
    if result.diagnostics.errors:
        raise RuntimeError(f"Cedar evaluation errors: {result.diagnostics.errors}")
    return result.allowed, [POLICY_NAMES.get(r, r) for r in result.diagnostics.reasons]


def python_decision(resource, context):
    """Same rules as blast_radius.cedar, in Python. Used only if Cedar isn't available."""
    reasons = []
    if resource["zone"] <= 1 and context["effective_zone"] <= 1:
        reasons.append("autonomous-when-safe-and-clear")
    if resource["zone"] <= 2 and context["approved"]:
        reasons.append("human-gated-after-approval")
    if resource["zone"] == 3:
        reasons.append("panic-override")
    forbids = []
    if resource["moves_money"] and not context["approved"]:
        forbids.append("money-needs-approval")
    if resource["moves_money"] and context["amount_inr"] > SPENDING_CAP_INR:
        forbids.append("demo-spending-cap")
    if forbids:
        return False, forbids
    return bool(reasons), reasons


def authorize(task, event):
    """Returns {"allowed", "reasons", "engine"}. Raises nothing for a normal deny."""
    resource, context = build_request(task, event)
    if cedarpy is not None:
        allowed, reasons = cedar_decision(resource, context, f"{task['agent']}.{task['tool']}")
        engine = "cedar"
    else:
        allowed, reasons = python_decision(resource, context)
        engine = "python-fallback"
    return {"allowed": allowed, "reasons": reasons, "engine": engine}
