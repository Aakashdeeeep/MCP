"""Run Raksha's own agent code, unchanged, in-process.

Each agent module exposes handler(event, context) and takes the same event the Step
Functions Map state builds: {"task", "plan_id", "transcript", "approval"?}. Calling it here
means every tool still goes through raksha_common.agent.run_tool, which re-checks the
registry and asks the Cedar policy before anything runs. The MCP gate is the first check;
the agent's own Cedar call is the second.
"""
import importlib

from raksha_mcp import ledger

AGENT_MODULES = {
    "conversation": "agents.conversation",
    "health-log": "agents.health_log",
    "pharmacy-order": "agents.pharmacy_order",
    "scam-shield": "agents.scam_shield",
    "family-bridge": "agents.family_bridge",
    "care-coordinator": "agents.care_coordinator",
    "location-finder": "agents.location_finder",
    "calendar-assistant": "agents.calendar_assistant",
    "payment-assistant": "agents.payment_assistant",
    "raksha-voice": "raksha_mcp.voice_agent",  # new for Alexa+, same contract
}

_loaded = {}


def _with_feed(notify):
    """Every message the family gets also shows up in the live family feed."""

    def notify_caregiver(subject, body):
        sent = notify(subject, body)
        ledger.record("family_message", subject, body=body, channels=sent)
        return sent

    notify_caregiver.raksha_feed = True
    return notify_caregiver


def module_for(agent):
    if agent not in _loaded:
        module = importlib.import_module(AGENT_MODULES[agent])
        notify = getattr(module, "notify_caregiver", None)
        if notify is not None and not getattr(notify, "raksha_feed", False):
            module.notify_caregiver = _with_feed(notify)
        _loaded[agent] = module
    return _loaded[agent]


def run(task, utterance, request_id, approval=None):
    """Invoke the agent for one task. Raises PermissionError if Cedar says no."""
    event = {"task": task, "plan_id": request_id, "transcript": utterance}
    if approval is not None:
        event["approval"] = approval
    return module_for(task["agent"]).handler(event, None)
