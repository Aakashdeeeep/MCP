"""Deterministic safety tripwire: keyword patterns that force a Zone 3 alert even if the LLM
misses a scam or emergency, or the LLM is unavailable.

This is a backstop, not the detector. The LLM handles nuance; the tripwire guarantees the
obvious cases (OTP requests, "digital arrest", remote-access apps, heart attack...) always
reach the caregiver. False positives cost one extra alert; false negatives cost savings.

Patterns cover Hinglish (Latin script) and Devanagari. Devanagari has no reliable \\b word
boundaries in Python regex, so those are plain substrings.
"""
import re

# Any one of these is enough
STRONG_SCAM = {
    "otp_request": r"\bo\.?\s?t\.?\s?p\b|ओटीपी",
    "pin_or_cvv": r"\bcvv\b|\batm\s*pin\b|\bupi\s*pin\b|पिन\s*नंबर|सीवीवी",
    "digital_arrest": r"digital\s*arrest|डिजिटल\s*अरेस्ट",
    "remote_access_app": r"any\s*desk|team\s*viewer|screen\s*shar|एनीडेस्क|स्क्रीन\s*शेयर",
    "safe_account": r"safe\s*account|सेफ\s*अकाउंट",
    "kyc_threat": r"\bkyc\b|केवाईसी",
}

# These only count together with a money / threat word (e.g. "police ... paise bhejo")
AUTHORITY = r"\b(rbi|cbi|police|customs|courier|income\s*tax|ed\s*officer)\b|आरबीआई|सीबीआई|पुलिस|कस्टम|कूरियर|लॉटरी|lottery"
MONEY_OR_THREAT = r"paise|paisa|rupay|transfer|bhej|arrest|jail|account|khata|पैसे|रुपये|ट्रांसफर|भेज|गिरफ्तार|जेल|खाता|अकाउंट"

EMERGENCY = {
    "chest_pain": r"chest\s*pain|seene\s*(me|mein)\s*dard|सीने\s*में\s*दर्द|छाती\s*में\s*दर्द",
    "heart_attack": r"heart\s*attack|हार्ट\s*अटैक|दिल\s*का\s*दौरा",
    "breathing": r"saans\s*nahi|सांस\s*नहीं|साँस\s*नहीं|सांस\s*लेने\s*में\s*तकलीफ",
    "unconscious": r"behosh|बेहोश",
    "ambulance": r"ambulance|एम्बुलेंस|एंबुलेंस",
}


def _matches(patterns, text):
    return sorted(label for label, pattern in patterns.items() if re.search(pattern, text, re.IGNORECASE))


def scam_signals(transcript):
    text = transcript or ""
    hits = _matches(STRONG_SCAM, text)
    if re.search(AUTHORITY, text, re.IGNORECASE) and re.search(MONEY_OR_THREAT, text, re.IGNORECASE):
        hits.append("authority_plus_money")
    return hits


def emergency_signals(transcript):
    return _matches(EMERGENCY, transcript or "")


def tripwire_task(tool, task_id, signals, where="voice memo"):
    if tool == "report_scam":
        args = {"scam_type": signals[0], "description": f"Scam keywords detected in {where}", "indicators": signals}
        summary = f"Scam keywords detected in {where}: {', '.join(signals)}"
    else:
        args = {"description": f"Emergency keywords detected in {where}: {', '.join(signals)}"}
        summary = f"Emergency keywords detected in {where}: {', '.join(signals)}"
    return {
        "task_id": task_id,
        "agent": "scam-shield",
        "tool": tool,
        "args": args,
        "confidence": 1.0,
        "zone": 3,
        "registry_zone": 3,
        "llm_zone": None,
        "forced_by_confidence": False,
        "source": "tripwire",
        "summary_en": summary,
        "reply_text_hi": "",
    }


def where_from(spoken, printed):
    """Tell the caregiver where the keywords were: their words, the paper, or both."""
    if spoken and printed:
        return "voice memo and photographed paper"
    return "photographed paper" if printed else "voice memo"


def apply_tripwire(tasks, transcript, document_text=""):
    """Add a Zone 3 task for each signal type the plan doesn't already cover.

    A photographed paper is scanned as well as the transcript: a fake KYC notice or a
    threatening demand letter must reach the caregiver even if the elder says nothing."""
    planned_tools = {t["tool"] for t in tasks if t["agent"] == "scam-shield"}
    extra = []
    for tool, task_id, detect in (
        ("report_scam", "tripwire-scam", scam_signals),
        ("report_emergency", "tripwire-emergency", emergency_signals),
    ):
        spoken, printed = detect(transcript), detect(document_text)
        signals = sorted(set(spoken) | set(printed))
        if signals and tool not in planned_tools:
            extra.append(tripwire_task(tool, task_id, signals, where_from(spoken, printed)))
    return extra + tasks
