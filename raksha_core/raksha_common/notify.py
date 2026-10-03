"""Send a message to the caregiver.

WhatsApp via Twilio when credentials are configured (sandbox is fine), and ALWAYS by
SNS email as well. Email is the reliable fallback: SMS to Indian numbers needs DLT
registration, and the Twilio WhatsApp sandbox only reaches numbers that have joined it.
"""
import base64
import json
import os
import urllib.parse
import urllib.request

import boto3

sns = boto3.client("sns")

# TODO: set once AWS account exists (SAM injects these from template.yaml)
TOPIC_ARN = os.environ.get("CAREGIVER_TOPIC_ARN", "")
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_API_KEY_SID = os.environ.get("TWILIO_API_KEY_SID", "")
TWILIO_API_KEY_SECRET = os.environ.get("TWILIO_API_KEY_SECRET", "")
TWILIO_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # Twilio sandbox number
CAREGIVER_WHATSAPP_TO = os.environ.get("CAREGIVER_WHATSAPP_TO", "")  # e.g. whatsapp:+9198XXXXXXXX
TWILIO_CONTENT_SID = os.environ.get("TWILIO_CONTENT_SID", "")


def send_whatsapp(body):
    """Returns the Twilio message SID, or None if WhatsApp isn't configured."""
    has_account_auth = bool(TWILIO_SID and TWILIO_TOKEN)
    has_api_key_auth = bool(TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET)
    if not (TWILIO_SID and (has_account_auth or has_api_key_auth) and CAREGIVER_WHATSAPP_TO):
        return None
    payload = {"From": TWILIO_FROM, "To": CAREGIVER_WHATSAPP_TO}
    if TWILIO_CONTENT_SID:
        payload["ContentSid"] = TWILIO_CONTENT_SID
    else:
        payload["Body"] = body[:1500]
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json", data=data, method="POST"
    )
    # Twilio supports either Account SID + Auth Token or API Key SID (SK...) + secret.
    username, password = (TWILIO_SID, TWILIO_TOKEN) if has_account_auth else (TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET)
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())["sid"]


def notify_caregiver(subject, body):
    """Send on every configured channel. A WhatsApp failure never blocks the email."""
    result = {"whatsapp_sid": None, "email_sent": False}
    try:
        result["whatsapp_sid"] = send_whatsapp(f"*{subject}*\n{body}")
    except Exception as e:  # noqa: BLE001 - keep going to email
        print(f"WhatsApp send failed, email only: {e}")
    if TOPIC_ARN:
        sns.publish(TopicArn=TOPIC_ARN, Subject=subject[:100], Message=body)
        result["email_sent"] = True
    return result
