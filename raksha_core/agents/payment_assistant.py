"""Agent: payment-assistant. create_payment_link is Zone 2 (runs only after caregiver approval).

Creates a Razorpay payment link in TEST MODE and sends it to the caregiver, who pays.
Raksha itself never moves money. Without Razorpay test keys, or if the call fails, it
returns a MOCKED link.
"""
import os
import uuid

from raksha_common.agent import result, run_tool
from raksha_common.http import request_json
from raksha_common.notify import notify_caregiver

# TODO: set in template parameters. Use rzp_test_ keys only.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
MAX_AMOUNT_INR = 5000  # demo safety cap


def razorpay_enabled():
    # Refuse live keys: this demo must only ever use test mode
    return RAZORPAY_KEY_ID.startswith("rzp_test_") and bool(RAZORPAY_KEY_SECRET)


def create_payment_link(args, event):
    amount = args["amount_inr"]
    if not 0 < amount <= MAX_AMOUNT_INR:
        raise ValueError(f"amount_inr {amount} outside the demo limit (1-{MAX_AMOUNT_INR})")

    link, mocked = None, True
    if razorpay_enabled():
        try:
            data = request_json(
                "https://api.razorpay.com/v1/payment_links",
                method="POST",
                basic_auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
                body={
                    "amount": int(round(amount * 100)),  # paise
                    "currency": "INR",
                    "description": args["description"][:200],
                    "reminder_enable": False,
                    "notify": {"sms": False, "email": False},
                },
            )
            link, mocked = {"payment_link_id": data["id"], "short_url": data["short_url"], "status": data["status"]}, False
        except Exception as e:  # noqa: BLE001 - fall back to the mock
            print(f"Razorpay failed, using mock: {e}")
    if link is None:
        # MOCKED: fake link, nothing is payable
        link = {"payment_link_id": f"plink_MOCK{uuid.uuid4().hex[:10]}", "short_url": "https://rzp.io/MOCK", "status": "created"}

    notify_caregiver(
        "Raksha: payment link ready",
        f"Approved payment of Rs {amount:g} for: {args['description']}\nPay here: {link['short_url']}"
        + ("\n(DEMO: mocked link, not payable)" if mocked else "\n(Razorpay TEST MODE)"),
    )
    return result(
        f"₹{amount:g} का पेमेंट लिंक बना कर आपके परिवार को भेज दिया है।",
        {**link, "amount_inr": amount},
        mocked=mocked,
        mock_reason="Razorpay test keys not set or Razorpay call failed" if mocked else None,
    )


def verify_transaction(args, event):
    link_id = args["payment_link_id"]
    if razorpay_enabled() and not link_id.startswith("plink_MOCK"):
        data = request_json(
            f"https://api.razorpay.com/v1/payment_links/{link_id}", basic_auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
        )
        status, mocked = data["status"], False
    else:
        status, mocked = "paid", True  # MOCKED
    reply = "पेमेंट हो चुका है।" if status == "paid" else "पेमेंट अभी बाकी है।"
    return result(reply, {"payment_link_id": link_id, "status": status}, mocked=mocked)


TOOLS = {"create_payment_link": create_payment_link, "verify_transaction": verify_transaction}


def handler(event, context):
    return run_tool("payment-assistant", TOOLS, event)
