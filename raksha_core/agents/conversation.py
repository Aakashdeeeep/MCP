"""Agent: conversation (Zone 0). Warm reply for chit-chat, complaints, unclear statements,
and a follow-up question when a request is missing a detail.

Takes no action and never diagnoses. May leave a low-priority note for the caregiver.
"""
import os
import uuid
from datetime import datetime, timezone

import boto3

from raksha_common.agent import PATIENT_ID, result, run_tool
from raksha_common.conversation_state import save_open_question

dynamodb = boto3.resource("dynamodb")
# TODO: set once AWS account exists (SAM injects this from template.yaml)
alerts_table = dynamodb.Table(os.environ.get("ALERTS_TABLE", "CaregiverAlerts-TODO"))

DEFAULT_REPLY = "मैं आपकी बात सुन रही हूँ। आप चिंता मत कीजिए, मैं यहीं हूँ।"


def reply(args, event):
    text = (event["task"].get("reply_text_hi") or "").strip() or DEFAULT_REPLY
    note = (args.get("caregiver_note") or "").strip()
    if note:
        alerts_table.put_item(
            Item={
                "alert_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "alert_type": "note",
                "summary": note,
                "status": "pending",
                "plan_id": event.get("plan_id", ""),
            }
        )
    return result(text, {"note_logged": bool(note)})


def ask_followup(args, event):
    """Speak one question and remember it, so the elder's next memo is planned with context."""
    task = event["task"]
    followup_round = int(task.get("followup_round") or 1)
    save_open_question(
        PATIENT_ID,
        event.get("plan_id", ""),
        args["question_hi"],
        args["about"],
        task.get("followup_history") or event.get("transcript", ""),
        followup_round,
    )
    return result(args["question_hi"], {"asked_about": args["about"], "round": followup_round})


TOOLS = {"reply": reply, "ask_followup": ask_followup}


def handler(event, context):
    return run_tool("conversation", TOOLS, event)
