"""Read-only view of one voice memo's progress, used by the elder app and the family dashboard.

PlanHistory item (written by the state machine):
  plan_id, timestamp, stage (reading_document | transcribing | planning | executing | done | failed),
  raw_transcript, document_text, document_key, plan_json, zone_summary, planner_error, error,
  task_state: {task_id: {status, reply_text, mocked, result_json}}
Spoken replies live in S3 at responses/<memo_id>/<task_id>/<request_id>.mp3
"""
import json
import os

import boto3

from raksha_common.speech import AUDIO_BUCKET, presign, s3

dynamodb = boto3.resource("dynamodb")
# TODO: set once AWS account exists (SAM injects this from template.yaml)
plans_table = dynamodb.Table(os.environ.get("PLAN_HISTORY_TABLE", "PlanHistory-TODO"))


def default_status(task):
    if task.get("depends_on"):
        return "waiting_for_earlier_step"  # its Map iteration is waiting on another task's result
    return "preparing" if task.get("zone") == 2 else "running"


def merge_task_state(tasks, task_state, replans=None):
    """Attach live per-task state (written by the Map iterations) to the planned tasks, and any
    re-plan note: the plan shows the original tool, the note says what ran instead and why."""
    replanned = {entry.get("task_id"): entry for entry in (replans or [])}
    merged = []
    for task in tasks:
        state = dict((task_state or {}).get(task["task_id"]) or {})
        if "result_json" in state:
            try:
                state["result"] = json.loads(state.pop("result_json") or "{}")
            except json.JSONDecodeError:
                state["result"] = {}
        state.setdefault("status", default_status(task))
        if task["task_id"] in replanned:
            state["replan"] = replanned[task["task_id"]]
        merged.append({**task, "state": state})
    return merged


def list_replies(memo_id):
    listing = s3.list_objects_v2(Bucket=AUDIO_BUCKET, Prefix=f"responses/{memo_id}/").get("Contents", [])
    replies = []
    for obj in sorted(listing, key=lambda o: o["LastModified"]):
        parts = obj["Key"].split("/")  # responses, memo_id, task_id, file
        replies.append(
            {
                "key": obj["Key"],
                "task_id": parts[2] if len(parts) == 4 else "",
                "audio_url": presign(obj["Key"]),
                "created": obj["LastModified"].isoformat(),
            }
        )
    return replies


def memo_view(item, include_audio=True):
    """Turn a PlanHistory item into the JSON the frontends render."""
    memo_id = item["plan_id"]
    tasks = json.loads(item.get("plan_json") or "[]")
    return {
        "memo_id": memo_id,
        "timestamp": item.get("timestamp", ""),
        "stage": item.get("stage", "done"),
        "error": item.get("error", ""),
        "planner_error": item.get("planner_error", ""),
        "transcript": item.get("raw_transcript", ""),
        # What was read off a photographed paper: already masked, so it is safe to show.
        # The photo itself is presigned on demand, never a public URL.
        "document_text": item.get("document_text", ""),
        "document_url": presign(item["document_key"]) if item.get("document_key") and include_audio else "",
        "zone_summary": item.get("zone_summary", ""),
        "harness": item.get("harness", {}),
        "tasks": merge_task_state(tasks, item.get("task_state"), item.get("replans")),
        "replies": list_replies(memo_id) if include_audio else [],
    }


def get_memo(memo_id):
    item = plans_table.get_item(Key={"plan_id": memo_id}).get("Item")
    return memo_view(item) if item else None


def latest_memo():
    """Most recent memo. A scan is fine at demo scale (a few dozen memos)."""
    items = plans_table.scan(ProjectionExpression="plan_id, #ts", ExpressionAttributeNames={"#ts": "timestamp"})["Items"]
    if not items:
        return None
    newest = max(items, key=lambda i: i.get("timestamp", ""))
    return get_memo(newest["plan_id"])
