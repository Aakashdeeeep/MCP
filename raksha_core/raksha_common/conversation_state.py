"""The elder's open follow-up question, so their NEXT voice memo is planned with context.

Each voice memo is still its own execution, planned once. When the planner can't act on a
request without guessing (which medicine?), conversation.ask_followup speaks a question and
saves it here. The next memo's planner reads it, plans with both memos, and clears it.
Questions expire after 10 minutes, so an old question never confuses a new conversation.
"""
import os
import time

import boto3

dynamodb = boto3.resource("dynamodb")
# TODO: set once AWS account exists (SAM injects this from template.yaml)
table = dynamodb.Table(os.environ.get("CONVERSATION_TABLE", "ConversationState-TODO"))

TTL_SECONDS = 600


def save_open_question(patient_id, memo_id, question_hi, about, history, followup_round):
    now = int(time.time())
    table.put_item(
        Item={
            "patient_id": patient_id,
            "memo_id": memo_id,
            "question_hi": question_hi,
            "about": about,
            "history": history,  # everything the elder has said in this conversation so far
            "round": int(followup_round),
            "asked_at": now,
            "expires_at": now + TTL_SECONDS,  # DynamoDB TTL deletes it eventually; code checks it exactly
        }
    )


def get_open_question(patient_id, now=None):
    item = table.get_item(Key={"patient_id": patient_id}).get("Item")
    if not item or int(item["expires_at"]) <= (now if now is not None else time.time()):
        return None
    return {**item, "round": int(item["round"])}


def clear_open_question(patient_id):
    table.delete_item(Key={"patient_id": patient_id})
