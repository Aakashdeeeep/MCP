"""Agent: pharmacy-order. order_medicine is Zone 2 (runs only after caregiver approval).

# MOCKED — there is no free public pharmacy API, so no real pharmacy is contacted and no
# payment happens. Responses are hardcoded so the demo is repeatable.
"""
import uuid

from raksha_common.agent import result, run_tool

MOCK_PRICE_INR = 250


def order_medicine(args, event):
    name = args["name"]
    dosage = args.get("dosage") or ""
    # MOCKED: pretend the pharmacy accepted the order
    order = {
        "status": "success",
        "order_id": f"MOCK-{uuid.uuid4().hex[:8].upper()}",
        "medicine": f"{name} {dosage}".strip(),
        "quantity": args.get("quantity") or 1,
        "price": MOCK_PRICE_INR,
        "eta_hours": 4,
    }
    return result(
        f"आपकी {name} दवाई का ऑर्डर हो गया है। लगभग चार घंटे में आ जाएगी।",
        order,
        mocked=True,
        mock_reason="no real pharmacy API; hardcoded order confirmation",
    )


def check_stock(args, event):
    # MOCKED: every medicine is "in stock"
    return result(
        f"{args['name']} दवाई दुकान पर उपलब्ध है।",
        {"medicine": args["name"], "in_stock": True},
        mocked=True,
        mock_reason="no real pharmacy API; hardcoded stock response",
    )


TOOLS = {"order_medicine": order_medicine, "check_stock": check_stock}


def handler(event, context):
    return run_tool("pharmacy-order", TOOLS, event)
