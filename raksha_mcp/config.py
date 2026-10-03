"""Runtime settings, all from environment variables.

RAKSHA_MODE=local (default) runs everything in-process: DynamoDB and SNS are simulated with
moto, notifications land in the family feed, and no AWS account is needed.
RAKSHA_MODE=aws uses the real tables, SNS topic and Bedrock in the deploy region.
"""
import os

MODE = os.environ.get("RAKSHA_MODE", "local").lower()
LOCAL = MODE != "aws"

ELDER_NAME = os.environ.get("RAKSHA_ELDER_NAME", "Kamala")
FAMILY_NAME = os.environ.get("RAKSHA_FAMILY_NAME", "Priya")

# Shared secret Alexa+ (or any MCP client) sends as "Authorization: Bearer <token>".
# Empty = no auth, which is only acceptable locally.
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

# Where the family opens approval links. In AWS mode this is the Function URL.
# Unset on Lambda: web.LearnBaseUrl fills it in from the first request (the Function URL).
PUBLIC_BASE_URL_FIXED = bool(os.environ.get("PUBLIC_BASE_URL"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
APPROVAL_PASSCODE = os.environ.get("APPROVAL_PASSCODE", "")
APPROVAL_TTL_SECONDS = int(os.environ.get("APPROVAL_TTL_SECONDS", "3600"))

LEDGER_TABLE = os.environ.get("LEDGER_TABLE", "RakshaMcpLedger")

# Bedrock (Claude via the Messages-API "Mantle" endpoint). Used by check_scam to judge the
# situations the keyword tripwire can't. Off unless RAKSHA_BEDROCK=1, so tests stay offline.
BEDROCK_ENABLED = os.environ.get("RAKSHA_BEDROCK", "0") == "1"
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "us-east-1"))
SCAM_MODEL_ID = os.environ.get("SCAM_MODEL_ID", "anthropic.claude-haiku-4-5")

# 0.0.0.0 when hosted (Lambda Web Adapter); localhost keeps the SDK's DNS-rebinding guard on.
HOST = os.environ.get("RAKSHA_HOST", "127.0.0.1")
# Stateless Streamable HTTP suits Lambda: any instance can answer any request. A stateless
# 2025-11-25 connection has no back-channel for server-to-client requests, so elicitation is
# then only used on 2026-07-28 connections (where it rides InputRequiredResult) and the
# family's approval remains the gate either way.
STATELESS = os.environ.get("RAKSHA_STATELESS", "0" if LOCAL else "1") == "1"

# /mcp needs a bearer token: the static MCP_AUTH_TOKEN (simulator, MCP Inspector) or an
# OAuth access token from Alexa+ account linking. Always on in AWS mode.
REQUIRE_AUTH = os.environ.get("RAKSHA_REQUIRE_AUTH", "1" if (not LOCAL or MCP_AUTH_TOKEN) else "0") == "1"
# Optional allowlist of OAuth redirect hosts (comma separated). Empty = any https host, since
# the consent page itself is guarded by the family passcode.
OAUTH_REDIRECT_HOSTS = [h.strip() for h in os.environ.get("OAUTH_REDIRECT_HOSTS", "").split(",") if h.strip()]
# Browser origins allowed to call /mcp (server-to-server calls send no Origin and pass).
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("RAKSHA_ALLOWED_ORIGINS", "").split(",") if o.strip()]

# After a scam alert, block every money-moving tool for this long (the family can lift it).
SCAM_WATCH_MINUTES = int(os.environ.get("SCAM_WATCH_MINUTES", "120"))
# Approval fatigue: at most this many money requests may wait for the family at once.
MAX_PENDING_MONEY = int(os.environ.get("MAX_PENDING_MONEY", "2"))
# Extra public hostnames (custom domain in front of the Function URL) trusted for links.
ALLOWED_HOSTS = [h.strip().lower() for h in os.environ.get("RAKSHA_ALLOWED_HOSTS", "").split(",") if h.strip()]
