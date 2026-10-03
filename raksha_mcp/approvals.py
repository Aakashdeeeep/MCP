"""The family's side of a Zone 2 request.

Raksha OS paused a Step Functions execution on .waitForTaskToken and resumed it from the
approval link. An MCP tool call can't stay open for an hour, so here the request is saved
in the ledger, and the family's Approve runs the task directly, with approval=true, through
the same agent code and the same Cedar policy. The elder hears the result the next time
they ask ("Alexa, did my family approve the medicine?" -> check_request_status).
"""
from datetime import datetime, timezone

from raksha_mcp import agents, config, ledger, voice


class ApprovalError(Exception):
    pass


def current(approval_id):
    """The approval, with an overdue pending request marked expired."""
    approval = ledger.get_approval(approval_id)
    if approval and approval["status"] == "pending":
        if datetime.fromisoformat(approval["expires_at"]) < datetime.now(timezone.utc):
            expired = {**approval, "status": "expired"}
            if ledger.put_approval(expired, expect_status="pending"):
                ledger.record("approval_expired", f"Expired: {approval['summary_en']}", approval_id=approval_id)
            approval = ledger.get_approval(approval_id)
    return approval


def decide(approval_id, approve, passcode=""):
    """Record the family's decision; on approve, run the task. Returns the updated approval."""
    if config.APPROVAL_PASSCODE and passcode != config.APPROVAL_PASSCODE:
        raise ApprovalError("Wrong family passcode.")
    approval = current(approval_id)
    if approval is None:
        raise ApprovalError("Request not found.")
    if approval["status"] != "pending":
        raise ApprovalError(f"Already {approval['status']}.")

    decided_at = datetime.now(timezone.utc).isoformat()
    if not approve:
        rejected = {**approval, "status": "rejected", "decided_at": decided_at}
        if not ledger.put_approval(rejected, expect_status="pending"):
            raise ApprovalError("Someone else already answered this request.")
        ledger.record("approval_rejected", f"Rejected: {approval['summary_en']}", approval_id=approval_id)
        return rejected

    # Claim the request before running it, so a double tap can't order twice.
    running = {**approval, "status": "running", "decided_at": decided_at}
    if not ledger.put_approval(running, expect_status="pending"):
        raise ApprovalError("Someone else already answered this request.")

    task = {
        "task_id": f"approval-{approval_id}",
        "agent": approval["agent"],
        "tool": approval["tool"],
        "args": approval["args"],
        "zone": 2,
        "confidence": approval.get("confidence", 1.0),
        "summary_en": approval["summary_en"],
    }
    try:
        output = agents.run(task, approval.get("utterance", ""), f"approval-{approval_id}", approval={"approved": True})
        finished = {
            **running,
            "status": "done",
            "outcome": {
                "reply_text": output.get("reply_text", ""),
                "speech": voice.done_line(approval["tool"], approval["args"], output.get("result") or {}),
                "result": output.get("result") or {},
                "policy": output.get("policy"),
                "mocked": bool(output.get("mocked")),
            },
        }
        ledger.record("approval_done", f"Approved and done: {approval['summary_en']}", approval_id=approval_id, policy=output.get("policy"), mocked=bool(output.get("mocked")))
    except Exception as error:  # noqa: BLE001 - recorded, and the elder is told it failed
        finished = {**running, "status": "failed", "error": str(error)}
        ledger.record("approval_failed", f"Approved but failed: {approval['summary_en']}", approval_id=approval_id, error=str(error))
    ledger.put_approval(finished)
    return finished
