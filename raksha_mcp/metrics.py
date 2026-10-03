"""Gate decisions as CloudWatch metrics, with no SDK calls and no extra latency.

On Lambda, a log line in CloudWatch Embedded Metric Format becomes a metric automatically.
One line per tool call gives the family's operators a live picture: how many calls Alexa
made, how many money actions were refused and why, and how many alerts reached the family.
The dashboard in infra/template.yaml charts these. Locally nothing is printed.
"""
import json
import time

from raksha_mcp import config

NAMESPACE = "Raksha/Gate"
BLOCKED = {"blocked_scam", "blocked_scam_watch", "blocked_policy", "blocked_too_many"}


def emit(status, tool, alerts):
    if config.LOCAL:
        return None
    record = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                "Dimensions": [["Status"], []],
                "Metrics": [
                    {"Name": "ToolCalls", "Unit": "Count"},
                    {"Name": "Blocked", "Unit": "Count"},
                    {"Name": "FamilyAlerts", "Unit": "Count"},
                    {"Name": "SentForApproval", "Unit": "Count"},
                ],
            }],
        },
        "Status": status,
        "Tool": tool,  # a property, not a dimension: searchable in Logs Insights, no metric explosion
        "ToolCalls": 1,
        "Blocked": int(status in BLOCKED),
        "FamilyAlerts": alerts,
        "SentForApproval": int(status == "pending_family_approval"),
    }
    line = json.dumps(record)
    print(line)
    return line
