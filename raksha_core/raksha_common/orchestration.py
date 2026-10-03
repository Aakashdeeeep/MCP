"""Versioned event contracts for Raksha's future serverless-orchestrator SDK."""
import json


EVENT_SCHEMA_VERSION = "1.0"
TASK_OBSERVED = "raksha.task.observed"


def task_observed_event(plan_id, task_id, task_state):
    """Build a privacy-minimal event for asynchronous integrations.

    Results and transcripts stay in PlanHistory. Consumers receive the outcome metadata and
    fetch only the fields they are authorized to inspect.
    """
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "type": TASK_OBSERVED,
        "plan_id": plan_id,
        "task_id": task_id,
        "attempt": int(task_state.get("attempts", 0)),
        "status": task_state.get("status", "failed"),
        "mocked": bool(task_state.get("mocked", False)),
        "event_id": f"{plan_id}:{task_id}:{int(task_state.get('attempts', 0))}",
    }


def parse_event(body):
    """Validate the stable public envelope before a queue consumer acts on it."""
    event = json.loads(body) if isinstance(body, str) else body
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    required = {"schema_version", "type", "plan_id", "task_id", "attempt", "status", "event_id"}
    missing = required.difference(event)
    if missing:
        raise ValueError(f"event missing fields: {', '.join(sorted(missing))}")
    if event["schema_version"] != EVENT_SCHEMA_VERSION:
        raise ValueError(f"unsupported event schema: {event['schema_version']}")
    if event["type"] != TASK_OBSERVED:
        raise ValueError(f"unsupported event type: {event['type']}")
    return event
