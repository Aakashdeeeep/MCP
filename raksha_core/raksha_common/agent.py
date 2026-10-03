"""Small helpers every agent Lambda uses: tool dispatch, blast-radius policy check, env config.

Agent contract (MCP-style):
  input  {"task": {"agent", "tool", "args", "zone", ...}, "plan_id", "transcript", "approval"?}
  output {"reply_text": <Hindi sentence to speak>, "result": {...}, "mocked": bool, "policy": {...}}
"""
import os

from raksha_common.policy import authorize
from raksha_common.tool_registry import get_tool

# TODO: set once AWS account exists (SAM injects these from template.yaml)
PATIENT_ID = os.environ.get("DEMO_PATIENT_ID", "demo-elder-001")
HOME_LAT = float(os.environ.get("HOME_LAT", "17.4239"))  # demo home location (Hyderabad)
HOME_LNG = float(os.environ.get("HOME_LNG", "78.4738"))


def run_tool(agent_id, tools, event):
    """Dispatch event["task"] to its tool function, after re-checking the registry and asking the
    Cedar blast-radius policy. Defence in depth: the state machine already gates by zone."""
    task = event["task"]
    tool = task["tool"]
    spec = get_tool(agent_id, tool)
    if task.get("agent") != agent_id or spec is None or tool not in tools:
        raise ValueError(f"{agent_id} cannot run tool {task.get('agent')}.{tool}")

    decision = authorize(task, event)
    print(f"policy {decision['engine']}: {agent_id}.{tool} allowed={decision['allowed']} reasons={decision['reasons']}")
    if not decision["allowed"]:
        blocked_by = ", ".join(decision["reasons"]) or "no permit matched"
        raise PermissionError(f"Blocked by blast-radius policy ({blocked_by})")

    output = tools[tool](task.get("args") or {}, event)
    return {**output, "policy": decision}


def result(reply_text, data=None, mocked=False, mock_reason=None):
    out = {"reply_text": reply_text, "result": data or {}, "mocked": mocked}
    if mocked:
        out["mock_reason"] = mock_reason or "hardcoded demo response"
    return out
