"""Medicine adherence: doses expected by the doctor's care plan vs doses the elder logged."""
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")

# TODO: set once AWS account exists (SAM injects these from template.yaml)
care_plans_table = dynamodb.Table(os.environ.get("CARE_PLANS_TABLE", "CarePlans-TODO"))
adherence_table = dynamodb.Table(os.environ.get("ADHERENCE_TABLE", "AdherenceLog-TODO"))


def expected_doses(plan, days):
    """Doses per day from the plan x number of days the plan has been active (max `days`)."""
    per_day = sum(len(m.get("times") or []) for m in plan.get("medicines") or [])
    created = datetime.fromisoformat(plan["created_at"])
    active_days = max(1, min(days, (datetime.now(timezone.utc) - created).days + 1))
    return per_day * active_days


def summarize(plan, dose_logs, days):
    expected = expected_doses(plan, days)
    taken = sum(1 for log in dose_logs if log.get("taken"))
    return {"days": days, "expected": expected, "taken": taken, "missed": max(0, expected - taken)}


def adherence_summary(patient_id, days=7):
    plan = care_plans_table.get_item(Key={"patient_id": patient_id}).get("Item")
    if not plan:
        return None
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    logs = adherence_table.query(
        KeyConditionExpression=Key("patient_id").eq(patient_id) & Key("timestamp").gte(since)
    )["Items"]
    return summarize(plan, logs, days)
