"""Make the vendored Raksha core importable, and in local mode stand up simulated AWS.

Raksha's modules create boto3 resources at import time and read table names from the
environment, so this must run before any of them is imported. raksha_mcp/__init__.py
calls setup() first thing.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from raksha_mcp import config

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "raksha_core"

TABLES = {
    # env var            local name          hash key      range key
    "VITALS_TABLE": ("VitalsLog", "patient_id", "timestamp"),
    "ALERTS_TABLE": ("CaregiverAlerts", "alert_id", None),
    "CARE_PLANS_TABLE": ("CarePlans", "patient_id", None),
    "ADHERENCE_TABLE": ("AdherenceLog", "patient_id", "timestamp"),
    "CONVERSATION_TABLE": ("ConversationState", "patient_id", None),
    "LEDGER_TABLE": (config.LEDGER_TABLE, "pk", "sk"),
}

DEMO_PATIENT_ID = "demo-elder-001"
DEMO_CARE_PLAN = {
    "patient_id": DEMO_PATIENT_ID,
    "doctor_name": "Dr. Rao",
    "medicines": [
        {"name": "Metformin", "dosage": "500 mg", "times": ["08:00", "20:00"]},
        {"name": "Amlodipine", "dosage": "5 mg", "times": ["08:00"]},
        {"name": "Atorvastatin", "dosage": "10 mg", "times": ["21:00"]},
    ],
    "vitals_to_track": ["blood_sugar", "blood_pressure"],
    "exercises": ["20 minute morning walk"],
}

_started = False


def setup():
    global _started
    if _started:
        return
    _started = True
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    if config.LOCAL:
        _start_local_aws()


def _start_local_aws():
    for name, value in {
        "AWS_DEFAULT_REGION": "ap-south-1",
        "AWS_REGION": "ap-south-1",
        "AWS_ACCESS_KEY_ID": "local",
        "AWS_SECRET_ACCESS_KEY": "local",
        "DEMO_PATIENT_ID": DEMO_PATIENT_ID,
    }.items():
        os.environ[name] = value
    for env, (table, _, _) in TABLES.items():
        os.environ[env] = table

    from moto import mock_aws

    mock_aws().start()  # stays active for the life of the process
    import boto3

    dynamodb = boto3.resource("dynamodb")
    for table, hash_key, range_key in TABLES.values():
        keys = [{"AttributeName": hash_key, "KeyType": "HASH"}]
        attrs = [{"AttributeName": hash_key, "AttributeType": "S"}]
        if range_key:
            keys.append({"AttributeName": range_key, "KeyType": "RANGE"})
            attrs.append({"AttributeName": range_key, "AttributeType": "S"})
        dynamodb.create_table(TableName=table, KeySchema=keys, AttributeDefinitions=attrs, BillingMode="PAY_PER_REQUEST")
    seed_demo_data(dynamodb)


def seed_demo_data(dynamodb):
    """A believable week for the demo elder: a care plan and a few missed doses."""
    now = datetime.now(timezone.utc)
    plan = {**DEMO_CARE_PLAN, "created_at": (now - timedelta(days=6)).isoformat()}
    dynamodb.Table(TABLES["CARE_PLANS_TABLE"][0]).put_item(Item=plan)

    adherence = dynamodb.Table(TABLES["ADHERENCE_TABLE"][0])
    for days_ago in range(1, 7):
        day = now - timedelta(days=days_ago)
        for index, medicine in enumerate(plan["medicines"]):
            for slot, _ in enumerate(medicine["times"]):
                # Evening Metformin is the one she tends to forget
                if medicine["name"] == "Metformin" and slot == 1 and days_ago % 2 == 0:
                    continue
                # timestamp is the sort key, so each dose needs its own
                stamp = day.replace(hour=3 + slot * 11, minute=index, second=0, microsecond=0).isoformat()
                adherence.put_item(
                    Item={"patient_id": DEMO_PATIENT_ID, "timestamp": stamp, "medicine": medicine["name"], "taken": True}
                )
