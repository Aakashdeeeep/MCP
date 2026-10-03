"""Agent: scam-shield (Zone 3, panic override). Alert the caregiver immediately about a
suspected scam or emergency, and give the elder calm, fixed reassurance.

It skips approval and queues. Replies are fixed text, not written by the LLM, and never
ask the elder to keep talking to a suspicious caller.
"""
import os
import uuid
from datetime import datetime, timezone

import boto3

from raksha_common.agent import result, run_tool
from raksha_common.emergency import nearest_hospital
from raksha_common.notify import notify_caregiver

dynamodb = boto3.resource("dynamodb")
# TODO: set once AWS account exists (SAM injects this from template.yaml)
alerts_table = dynamodb.Table(os.environ.get("ALERTS_TABLE", "CaregiverAlerts-TODO"))

SCAM_REPLY_HI = (
    "आपने बिल्कुल सही किया जो मुझे बताया। घबराइए मत, आप सुरक्षित हैं। "
    "कोई भी असली बैंक या पुलिस फ़ोन पर OTP नहीं माँगती। वह कॉल काट दीजिए और कोई जानकारी मत दीजिए। "
    "मैं अभी आपके परिवार को बता रही हूँ।"
)
EMERGENCY_REPLY_HI = (
    "मैंने आपके परिवार को तुरंत ख़बर कर दी है। आप आराम से बैठ जाइए। "
    "अगर हालत गंभीर लगे तो तुरंत 112 पर फ़ोन कीजिए।"
)


def alert(alert_kind, summary, event):
    """Notify first (the part that matters most), then record the alert."""
    body = f"{summary}\n\nWhat Raksha heard: \"{event.get('transcript', '')}\"\n\nPlease call them now."
    sent = notify_caregiver(f"URGENT: Raksha {alert_kind}", body)
    alerts_table.put_item(
        Item={
            "alert_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert_type": "urgent",
            "summary": summary,
            "status": "pending",
            "plan_id": event.get("plan_id", ""),
            "task_id": event["task"].get("task_id", ""),
        }
    )
    return sent


def report_scam(args, event):
    indicators = ", ".join(args.get("indicators") or [])
    summary = f"Possible scam ({args['scam_type']}): {args['description']}" + (f" [{indicators}]" if indicators else "")
    return result(SCAM_REPLY_HI, {"summary": summary, **alert("detected a possible scam", summary, event)})


def report_emergency(args, event):
    summary = f"Possible emergency: {args['description']}"
    # Notify before any network call. A hospital lookup is useful context for family, never a
    # replacement for dialing 112 or a claim that Raksha has dispatched medical help.
    sent = alert("possible emergency", summary, event)
    hospital, lookup_unavailable = nearest_hospital()
    if hospital:
        notify_caregiver(
            "Raksha: nearest hospital reference",
            f"For the emergency alert about {event.get('plan_id', 'this memo')}:\n\n"
            f"{hospital['name']}\n{hospital['address']}\n"
            f"Distance: {hospital['distance_km']} km\n"
            f"Phone: {hospital.get('phone') or 'not listed'}\n"
            f"Map: {hospital.get('maps_url') or 'not listed'}\n\n"
            "Reference only. Raksha has not dispatched an ambulance; call 112 for urgent help.",
        )
    return result(
        EMERGENCY_REPLY_HI,
        {
            "summary": summary,
            "emergency_number": "112",
            "nearest_hospital": hospital,
            "hospital_lookup_unavailable": lookup_unavailable,
            **sent,
        },
    )


TOOLS = {"report_scam": report_scam, "report_emergency": report_emergency}


def handler(event, context):
    return run_tool("scam-shield", TOOLS, event)
