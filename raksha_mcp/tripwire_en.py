"""English scam patterns for an English-speaking front door.

Raksha's tripwire (raksha_core/tripwire.py) was written for Hindi and Hinglish voice memos.
Alexa+ talks to the elder in English, so this adds the English shapes of the same frauds
that Indian police and banks warn about. Like the original it is a backstop: it forces a
Zone 3 alert on the obvious cases, and the Bedrock classifier in check_scam handles nuance.
Pure functions, no state.
"""
import re

import tripwire

# Any one of these is enough
STRONG = {
    "gift_card_payment": r"gift\s*cards?|google\s*play\s*(card|code)|amazon\s*(pay\s*)?(card|voucher)",
    "remote_access_app": r"\b(quick\s*support|rust\s*desk|ammyy|install\w*\s+(an?\s+)?app\s+(so|to)\s+(he|she|they)\s+can)",
    "refund_scam": r"refund.{0,40}(app|screen|access|install|otp)|(app|screen|access|install|otp).{0,40}refund",
    "disconnection_threat": r"(electricity|power|gas|sim|number|connection).{0,30}(cut|disconnect|block|deactivat)\w*.{0,30}(tonight|today|hours?|immediately)",
    "fake_prize_fee": r"(lottery|prize|won|winner|lucky\s*draw|reward).{0,60}(fee|charges?|tax|pay|deposit|processing)",
    "parcel_customs": r"(parcel|package|courier|fedex|dhl).{0,60}(drugs|illegal|seized|customs|narcotics)",
    "guaranteed_returns": r"(guaranteed|double|assured)\s+(returns?|profit|money)|(invest|trading).{0,40}(guaranteed|double)",
    "secrecy_demand": r"(don'?t|do\s*not)\s+tell\s+(anyone|your\s*(family|son|daughter|children))",
    "card_details": r"\b(card\s*number|expiry\s*date|cvv|net\s*banking\s*password|mpin)\b",
}

# All three together, in any order: "your grandson ... accident ... send money now".
# Money must be explicit, so "my daughter is in hospital, send her a message" stays quiet.
RELATIVE = r"\b(grandson|granddaughter|son|daughter|nephew|niece|relative|grandchild)\b"
TROUBLE = r"\b(accident|arrest(ed)?|hospital|trouble|jail|police|kidnap\w*)\b"
MONEY = r"money|\bpay(ment)?\b|transfer|\bupi\b|rupees|₹|\brs\.?\b|\bbail\b|\b\d{3,}\b"


def scam_signals(text):
    """Raksha's original signals plus the English ones, sorted and de-duplicated."""
    text = text or ""
    hits = set(tripwire.scam_signals(text))
    hits.update(label for label, pattern in STRONG.items() if re.search(pattern, text, re.IGNORECASE))
    if all(re.search(p, text, re.IGNORECASE) for p in (RELATIVE, TROUBLE, MONEY)):
        hits.add("relative_in_trouble")
    return sorted(hits)


def emergency_signals(text):
    text = text or ""
    hits = set(tripwire.emergency_signals(text))
    for label, pattern in {
        "fall": r"\b(i\s+(have\s+)?fell|i\s+(have\s+)?fallen|had\s+a\s+fall|can'?t\s+get\s+up)\b",
        "stroke_signs": r"face\s+(is\s+)?droop|slurred|can'?t\s+(move|feel)\s+my\s+(arm|leg|face)",
        "breathing": r"can'?t\s+breathe|cannot\s+breathe|short(ness)?\s+of\s+breath",
        "fainting": r"\bfaint(ed|ing)?\b|passed\s+out|blacked\s+out",
    }.items():
        if re.search(pattern, text, re.IGNORECASE):
            hits.add(label)
    return sorted(hits)
