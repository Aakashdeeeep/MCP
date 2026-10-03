"""Tests run fully offline: local mode (moto DynamoDB), no Bedrock, no network keys."""
import os

os.environ["RAKSHA_MODE"] = "local"
os.environ["RAKSHA_BEDROCK"] = "0"
os.environ.pop("MCP_AUTH_TOKEN", None)
os.environ.pop("APPROVAL_PASSCODE", None)

import pytest  # noqa: E402

import raksha_mcp  # noqa: E402,F401 - starts simulated AWS before any Raksha module loads


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_safety_state():
    """Scam watch and pending money requests are global state; every test starts clean."""
    from boto3.dynamodb.conditions import Key

    from raksha_mcp import ledger

    ledger.clear_scam_watch()
    for item in ledger.table().query(KeyConditionExpression=Key("pk").eq("PENDING_MONEY"))["Items"]:
        ledger.remove_pending_money(item["sk"])
    yield
