"""No-LLM fallback for the simulator: map a sentence to one Raksha tool by keywords.

Only for demos without Bedrock credentials. It is deliberately simple, and it is NOT a
safety layer: the MCP server's gate does all the checking either way.
"""
import re

RULES = [
    (r"(send|pay|transfer).*(₹|rs\.?|rupees|\d{3,})|payment link",
     lambda t: ("create_payment_link", {"amount_inr": _amount(t), "description": t[:120]})),
    (r"otp|pin\b|kyc|scam|fraud|digital arrest|lottery|prize|police|cbi|rbi|customs|courier|bank.*(call|message|asked)|suspicious|someone called",
     lambda t: ("check_scam", {"what_happened": t})),
    (r"chest pain|fell|fallen|can't breathe|cannot breathe|breathing|faint|dizzy|ambulance|emergency",
     lambda t: ("report_emergency", {"description": t})),
    (r"order|refill|run(ning)? out",
     lambda t: ("order_medicine", {"name": _medicine(t) or "Metformin", **({"quantity": q} if (q := _quantity(t)) else {})})),
    (r"(did|have) i (take|taken)|pills? (left|due)|medicines? (today|left|due)|what.*medicine",
     lambda t: ("todays_medicines", {})),
    (r"i (just )?(took|take|had)|taken my",
     lambda t: ("log_dose", {"medicine": _medicine(t) or "Metformin", "taken": True})),
    (r"skip|missed|forgot",
     lambda t: ("log_dose", {"medicine": _medicine(t) or "Metformin", "taken": False})),
    (r"how (am i|have i been) doing|adherence|missed doses",
     lambda t: ("get_adherence", {"days": 7})),
    (r"sugar|bp\b|blood pressure|pulse|temperature|weight",
     lambda t: ("log_vitals", _vitals(t))),
    (r"weather|walk|rain|outside",
     lambda t: ("check_weather", {"activity": "walk"})),
    (r"nearest|near me|nearby|hospital|pharmacy|temple|park|library|cafe|restaurant",
     lambda t: ("find_nearest", {"place_type": _place(t), "share_with_family": "send" in t or "share" in t})),
    (r"news|headlines",
     lambda t: ("read_news", {})),
    (r"call me|ask .* to call|want to talk",
     lambda t: ("request_family_call", {"recipient": _person(t)})),
    (r"tell|message|let .* know",
     lambda t: ("message_family", {"message": t})),
    (r"approv|did .* (say|answer)",
     lambda t: ("check_request_status", {"approval_id": _approval_id(t)})),
]

MEDICINES = ["metformin", "amlodipine", "atorvastatin", "paracetamol", "insulin"]
PLACES = ["hospital", "pharmacy", "temple", "park", "library", "cafe", "restaurant"]
last_approval_id = {"id": ""}


def route(text):
    lowered = (text or "").lower()
    for pattern, build in RULES:
        if re.search(pattern, lowered):
            return build(text.strip())
    return None


def remember_approval(outcome):
    if outcome.get("approval_id"):
        last_approval_id["id"] = outcome["approval_id"]


def _medicine(text):
    lowered = text.lower()
    found = next((m for m in MEDICINES if m in lowered), None)
    if found:
        return found.capitalize()
    if "sugar" in lowered:
        return "Metformin"
    if "bp" in lowered or "pressure" in lowered:
        return "Amlodipine"
    return None


def _quantity(text):
    match = re.search(r"(\d+)\s*(tablets|strips|pills)", text.lower())
    return int(match.group(1)) if match else None


def _amount(text):
    match = re.search(r"(\d[\d,]*)", text)
    return float(match.group(1).replace(",", "")) if match else 500.0


def _place(text):
    lowered = text.lower()
    return next((p for p in PLACES if p in lowered), "hospital")


def _person(text):
    match = re.search(r"ask (\w+)", text.lower())
    return match.group(1).capitalize() if match else "family"


def _vitals(text):
    lowered = text.lower()
    bp = re.search(r"(\d{2,3})\s*(/|over)\s*(\d{2,3})", lowered)
    if bp:
        return {"vital_type": "blood_pressure", "value": f"{bp.group(1)}/{bp.group(3)}"}
    number = re.search(r"(\d{2,3})", lowered)
    kind = "pulse" if "pulse" in lowered else "temperature" if "temperature" in lowered else "weight" if "weight" in lowered else "blood_sugar"
    return {"vital_type": kind, "value": number.group(1) if number else "0"}


def _approval_id(text):
    return last_approval_id["id"] or "unknown"
