"""Agent: health-log (Zone 1). Record and read back the elder's vitals in VitalsLog."""
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

from raksha_common.agent import PATIENT_ID, result, run_tool

dynamodb = boto3.resource("dynamodb")
# TODO: set once AWS account exists (SAM injects this from template.yaml)
vitals_table = dynamodb.Table(os.environ.get("VITALS_TABLE", "VitalsLog-TODO"))

VITAL_NAMES_HI = {
    "blood_sugar": "शुगर",
    "blood_pressure": "बीपी",
    "weight": "वज़न",
    "temperature": "तापमान",
    "pulse": "पल्स",
}


def log_vitals(args, event):
    vital_type = args["vital_type"]
    value = str(args["value"]).strip()  # string, so blood pressure "130/85" fits too
    unit = args.get("unit") or ""
    vitals_table.put_item(
        Item={
            "patient_id": PATIENT_ID,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vital_type": vital_type,
            "value": value,
            "unit": unit,
            "plan_id": event.get("plan_id", ""),
        }
    )
    name = VITAL_NAMES_HI.get(vital_type, vital_type)
    return result(f"जी, मैंने आपकी {name} {value} लिख ली है।", {"vital_type": vital_type, "value": value, "unit": unit})


def get_history(args, event):
    days = args.get("days") or 7
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    items = vitals_table.query(
        KeyConditionExpression=Key("patient_id").eq(PATIENT_ID) & Key("timestamp").gte(since),
        ScanIndexForward=False,
    )["Items"]
    if args.get("vital_type"):
        items = [i for i in items if i["vital_type"] == args["vital_type"]]
    readings = [i["value"] for i in items[:5]]
    if not readings:
        return result(f"पिछले {days} दिनों में कोई रीडिंग दर्ज नहीं है।", {"readings": []})
    name = VITAL_NAMES_HI.get(args.get("vital_type"), "")
    return result(f"आपकी पिछली {name} रीडिंग: {', '.join(readings)}।", {"readings": items[:5]})


TOOLS = {"log_vitals": log_vitals, "get_history": get_history}


def handler(event, context):
    return run_tool("health-log", TOOLS, event)
