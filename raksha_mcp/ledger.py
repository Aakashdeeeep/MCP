"""One small DynamoDB table for everything the MCP layer has to remember between requests.

  pk = "FEED"              sk = "<iso time>#<id>"   one line of the family feed (gate decisions,
                                                    alerts, approvals). The dashboard reads these.
  pk = "APPROVAL#<id>"     sk = "META"              a Zone 2 request waiting for the family.

Payloads are stored as JSON strings so floats and nested args survive DynamoDB untouched.
Lambda instances come and go; keeping this state in DynamoDB (moto locally) means an
approval made on one instance is seen by the next request on another.
"""
import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from raksha_mcp import config

FEED_LIMIT = 60

_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ.get("LEDGER_TABLE", config.LEDGER_TABLE))
    return _table


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def record(kind, title, **detail):
    """Append one line to the family feed and return it."""
    entry = {"id": uuid.uuid4().hex[:12], "at": now_iso(), "kind": kind, "title": title, **detail}
    table().put_item(Item={"pk": "FEED", "sk": f"{entry['at']}#{entry['id']}", "data": json.dumps(entry, default=str)})
    return entry


def feed(limit=FEED_LIMIT, after=None):
    """Newest first. `after` (an ISO time) returns only newer entries, for polling."""
    condition = Key("pk").eq("FEED")
    if after:
        condition = condition & Key("sk").gt(after)
    items = table().query(KeyConditionExpression=condition, ScanIndexForward=False, Limit=limit)["Items"]
    return [json.loads(item["data"]) for item in items]


def put_approval(approval, expect_status=None):
    """Save an approval. With expect_status, only if it is still in that status (so two
    family members tapping Approve at once can't run the same order twice).
    Returns False if the condition failed."""
    item = {
        "pk": f"APPROVAL#{approval['id']}",
        "sk": "META",
        "status": approval["status"],
        "data": json.dumps(approval, default=str),
    }
    kwargs = {}
    if expect_status:
        kwargs = {
            "ConditionExpression": "#s = :expected",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":expected": expect_status},
        }
    try:
        table().put_item(Item=item, **kwargs)
    except table().meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True


def get_approval(approval_id):
    item = table().get_item(Key={"pk": f"APPROVAL#{approval_id}", "sk": "META"}).get("Item")
    return json.loads(item["data"]) if item else None
