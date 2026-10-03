"""Pure state transitions for Raksha's bounded serverless execution harness.

The planner may choose tasks, but it never owns execution state.  DynamoDB does: the
workflow harness records the plan, each task's latest outcome, and only a small recent
observation history.  This gives every retry and re-plan durable context without creating
an open-ended autonomous loop.
"""
from datetime import datetime, timezone


MAX_TASK_OBSERVATIONS = 3


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def initial_task_state(tasks):
    """Create the durable work queue. Dependencies start visibly blocked on their input."""
    return {
        task["task_id"]: {
            "status": "waiting_for_earlier_step" if task.get("depends_on") else "queued",
            "attempts": 0,
            "observations": [],
        }
        for task in tasks
    }


def initial_harness(tasks, now=None):
    return {
        "version": 1,
        "status": "executing",
        "started_at": now or utc_now(),
        "limits": {"max_replans_per_task": 1, "max_task_observations": MAX_TASK_OBSERVATIONS},
        "task_count": len(tasks),
    }


def record_task_outcome(previous, outcome, now=None):
    """Return one task's next durable state with only the latest few observations retained."""
    previous = previous or {}
    outcome = outcome or {}
    timestamp = now or utc_now()
    observation = {
        "at": timestamp,
        "status": outcome.get("status", "failed"),
        "mocked": bool(outcome.get("mocked", False)),
        "reply_text": outcome.get("reply_text", ""),
    }
    observations = [*(previous.get("observations") or []), observation][-MAX_TASK_OBSERVATIONS:]
    return {
        **previous,
        "status": observation["status"],
        "reply_text": observation["reply_text"],
        "mocked": observation["mocked"],
        "result_json": outcome.get("result_json", "{}"),
        "attempts": int(previous.get("attempts", 0)) + 1,
        "observations": observations,
        "updated_at": timestamp,
    }
