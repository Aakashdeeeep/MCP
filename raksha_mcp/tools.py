"""Which Raksha tools Alexa+ can see, and how each becomes an MCP tool.

The argument names, types and required flags come from Raksha's tool registry, so the MCP
schema can't drift from what the agents and the planner validate. This file adds only what
a voice assistant needs on top: an Alexa-facing name and description, a sentence per
argument, and two arguments every tool takes:

  utterance   the elder's exact words. The scam/emergency tripwire reads these, so a scam
              phrase reaches the family even if Alexa's model paraphrased it away.
  confidence  how sure Alexa is that it understood. Below 0.75, a Zone 0/1 action needs
              the family's okay, exactly as with Raksha's own planner.
"""
from dataclasses import dataclass, field

from raksha_common.tool_registry import get_tool

ZONE_LABELS = {
    0: "Zone 0: conversation only",
    1: "Zone 1: runs on its own (internal or read-only)",
    2: "Zone 2: needs the family's approval before it runs",
    3: "Zone 3: panic override, alerts the family immediately",
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    agent: str
    tool: str
    title: str
    description: str
    arg_docs: dict = field(default_factory=dict)
    open_world: bool = False  # talks to something outside Raksha (pharmacy, maps, news...)

    @property
    def registry(self):
        return get_tool(self.agent, self.tool)


TOOLS = [
    # --- medicines -------------------------------------------------------------------
    ToolSpec(
        "todays_medicines", "raksha-voice", "todays_medicines", "Today's medicines",
        "Which of today's medicines from the doctor's plan are taken and which are still due. "
        "Use for 'did I take my pills?', 'what medicine is left today?'.",
    ),
    ToolSpec(
        "log_dose", "care-coordinator", "log_dose", "Log a medicine dose",
        "Record that the elder just took, or skipped, a dose of a medicine.",
        {"medicine": "Medicine name as in the care plan, e.g. Metformin.", "taken": "true if taken, false if skipped."},
    ),
    ToolSpec(
        "get_adherence", "care-coordinator", "get_adherence", "Medicine adherence",
        "How many doses were taken versus missed recently.",
        {"days": "How many days to look back. Default 7."},
    ),
    ToolSpec(
        "check_medicine_stock", "pharmacy-order", "check_stock", "Check medicine stock",
        "Check whether the pharmacy has a medicine in stock.", {"name": "Medicine name."}, open_world=True,
    ),
    ToolSpec(
        "order_medicine", "pharmacy-order", "order_medicine", "Order medicine (family approves)",
        "Order a medicine refill. Always waits for the family's approval; tell the elder it has "
        "been sent to the family, never that it has been ordered.",
        {"name": "Medicine name.", "dosage": "Strength, e.g. 500 mg.", "quantity": "Number of tablets or strips."},
        open_world=True,
    ),
    # --- health ----------------------------------------------------------------------
    ToolSpec(
        "log_vitals", "health-log", "log_vitals", "Log a health reading",
        "Record a reading the elder tells you.",
        {
            "vital_type": "One of blood_sugar, blood_pressure, weight, temperature, pulse.",
            "value": "The reading as spoken, e.g. '130/85' or '142'.",
            "unit": "Optional unit, e.g. mg/dL.",
        },
    ),
    ToolSpec(
        "get_vitals_history", "health-log", "get_history", "Recent health readings",
        "Read back recent readings.",
        {"vital_type": "Optional: blood_sugar, blood_pressure, weight, temperature or pulse.", "days": "Days to look back."},
    ),
    # --- safety ----------------------------------------------------------------------
    ToolSpec(
        "check_scam", "raksha-voice", "check_scam", "Is this a scam?",
        "Call this whenever the elder mentions a call, SMS, WhatsApp, letter or visitor asking for "
        "money, an OTP, PIN, KYC, bank details, a fine, a prize, or claiming to be bank, police, "
        "RBI, courier or customs. Raksha judges it, alerts the family if it's a scam, and returns "
        "calm advice to read out.",
        {"what_happened": "What the elder says happened, in their words."},
    ),
    ToolSpec(
        "verify_caller", "raksha-voice", "verify_caller", "Is this caller who they say?",
        "When someone calls claiming to be a relative, the bank, police or the doctor, check them "
        "against the family's trusted contacts and get the safe number to call back on.",
        {
            "claimed_identity": "Who the caller says they are, e.g. 'my grandson Rahul', 'SBI bank'.",
            "phone_number": "The number they called from, if the elder knows it.",
        },
    ),
    ToolSpec(
        "report_emergency", "scam-shield", "report_emergency", "Alert family: emergency",
        "Possible medical emergency (fall, chest pain, breathing trouble, fainting). Alerts the "
        "family immediately. Never diagnose; tell the elder to call 112 if it is serious.",
        {"description": "What is happening, in plain words."},
    ),
    # --- family ----------------------------------------------------------------------
    ToolSpec(
        "request_family_call", "family-bridge", "request_call", "Ask family to call",
        "Ask a family member to call the elder back.", {"recipient": "Who should call, e.g. Priya, my son."},
    ),
    ToolSpec(
        "message_family", "family-bridge", "share_update", "Message the family",
        "Pass a short message from the elder to the family.", {"message": "The message, in the elder's words."},
    ),
    ToolSpec(
        "family_summary", "raksha-voice", "family_summary", "How is she doing? (for family)",
        "For a family member asking how the elder is doing: medicines taken and missed, latest "
        "readings, safety alerts and requests waiting for approval.",
        {"days": "How many days to cover. Default 7."},
    ),
    ToolSpec(
        "check_request_status", "raksha-voice", "check_request_status", "Family approval status",
        "Check whether the family approved an earlier request (order, payment, calendar). "
        "Use the approval_id returned when the request was sent.",
        {"approval_id": "The approval_id from the earlier tool result."},
    ),
    # --- money -----------------------------------------------------------------------
    ToolSpec(
        "create_payment_link", "payment-assistant", "create_payment_link", "Payment link (family approves)",
        "Create a UPI payment link (e.g. a doctor's fee) that the family pays. Never pays by itself; "
        "always waits for the family's approval; capped by policy.",
        {"amount_inr": "Amount in rupees.", "description": "What it is for."},
        open_world=True,
    ),
    ToolSpec(
        "check_payment", "payment-assistant", "verify_transaction", "Check a payment",
        "Check whether an earlier payment link has been paid.", {"payment_link_id": "The payment_link_id."},
        open_world=True,
    ),
    # --- outside world ---------------------------------------------------------------
    ToolSpec(
        "check_weather", "care-coordinator", "check_weather", "Weather for a walk",
        "Weather at home, with advice for an outdoor activity.", {"activity": "e.g. walk, temple visit."},
        open_world=True,
    ),
    ToolSpec(
        "find_nearest", "location-finder", "find_nearest", "Find a nearby place",
        "Nearest hospital, pharmacy, restaurant, cafe, library, temple or park to home.",
        {
            "place_type": "One of hospital, pharmacy, restaurant, cafe, library, temple, park.",
            "share_with_family": "true to also send the place to the family.",
        },
        open_world=True,
    ),
    ToolSpec(
        "read_news", "family-bridge", "fetch_news", "Today's headlines",
        "Read out today's top Indian news headlines.", {"topic": "Optional topic, e.g. cricket."}, open_world=True,
    ),
    ToolSpec(
        "list_plans", "calendar-assistant", "list_events", "Upcoming plans",
        "Read upcoming outings and appointments from the family calendar.", {"days": "Days ahead to look."},
        open_world=True,
    ),
    ToolSpec(
        "schedule_outing", "calendar-assistant", "create_event", "Plan an outing (family approves)",
        "Add an outing or appointment to the family calendar after the family approves. start/end are "
        "ISO 8601 with the India offset, e.g. 2026-10-05T10:00:00+05:30.",
        {
            "summary": "What it is, e.g. Temple visit.",
            "start": "Start time, ISO 8601 with +05:30.",
            "end": "Optional end time.",
            "location": "Optional place.",
            "description": "Optional notes.",
        },
        open_world=True,
    ),
]

BY_NAME = {spec.name: spec for spec in TOOLS}
