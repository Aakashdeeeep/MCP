"""What Alexa says out loud.

Raksha's agents answer in Hindi (Polly's Kajal voice). Alexa+ speaks English, so every
outcome gets a short English line built here from the agent's structured result. The
agent's Hindi line travels alongside it unchanged. Wording is fixed in code, never
written by a model, for the same reason scam-shield's replies are fixed: an elder hearing
"hang up, you're safe" must hear exactly that.
"""

VITAL_NAMES = {
    "blood_sugar": "blood sugar",
    "blood_pressure": "blood pressure",
    "weight": "weight",
    "temperature": "temperature",
    "pulse": "pulse",
}

WEATHER_WORDS = {
    "Rain": "rainy",
    "Drizzle": "drizzling",
    "Thunderstorm": "stormy",
    "Snow": "snowing",
    "Clear": "clear",
    "Clouds": "cloudy",
    "Haze": "hazy",
    "Mist": "misty",
}

SCAM_EN = (
    "You did the right thing telling me. You are safe. Please hang up and do not share any OTP, "
    "PIN or money: no real bank or police officer asks for that on the phone. I'm alerting your "
    "family right now. You can also call 1930, the cyber fraud helpline."
)
EMERGENCY_EN = (
    "I've alerted your family right now. Please sit down and stay calm. "
    "If it feels serious, call 112 immediately."
)


def _join(items):
    items = [str(i) for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def done_line(tool, args, data):
    """English sentence for a tool that ran. data = the agent's `result` dict."""
    if tool == "log_dose":
        if args.get("taken"):
            return f"Got it. I've noted that you took your {args['medicine']}."
        return f"Okay, I've noted that you skipped your {args['medicine']}. Try to take the next dose on time."
    if tool == "get_adherence":
        if "expected" not in data:
            return "I couldn't find your doctor's medicine list yet."
        return (
            f"In the last {data['days']} days you took {data['taken']} of {data['expected']} doses"
            + (f", and {data['missed']} were missed." if data["missed"] else ". You didn't miss any. Well done!")
        )
    if tool == "todays_medicines":
        if data.get("no_plan"):
            return "I couldn't find your doctor's medicine list yet."
        if not data.get("due"):
            return "You've taken all of today's medicines. Well done!"
        due = _join(f"{m['name']} at {_join(m['remaining_times'])}" for m in data["due"])
        taken = _join(m["name"] for m in data.get("taken", []))
        return f"Still to take today: {due}." + (f" Already taken: {taken}." if taken else "")
    if tool == "log_vitals":
        unit = f" {data.get('unit')}" if data.get("unit") else ""
        return f"I've noted your {VITAL_NAMES.get(data.get('vital_type'), data.get('vital_type'))} reading of {data.get('value')}{unit}."
    if tool == "get_history":
        readings = [r["value"] if isinstance(r, dict) else r for r in data.get("readings", [])]
        if not readings:
            return "There are no readings logged for that period."
        return f"Your recent readings are: {_join(readings)}."
    if tool == "check_weather":
        condition, temp = data.get("condition", ""), data.get("temp_c")
        if condition in {"Rain", "Drizzle", "Thunderstorm", "Snow"}:
            advice = "Better to walk indoors today."
        elif temp is not None and temp >= 38:
            advice = "It's very hot, so go early in the morning or in the evening, and keep drinking water."
        else:
            advice = "It's a good day for your walk."
        sky = WEATHER_WORDS.get(condition, condition.lower() or "unclear")
        return f"It's {sky} and about {temp:g} degrees. {advice}"
    if tool == "find_nearest":
        line = f"The nearest {args.get('place_type', 'place')} is {data.get('name')}, {data.get('distance_km')} kilometres away."
        if data.get("open_now") is False:
            line += " It looks closed right now, so call before you go."
        if args.get("share_with_family"):
            line += " I've sent the details to your family."
        return line
    if tool == "lookup_pincode":
        if "area" not in data:
            return "That pincode doesn't look right. Please tell me all six digits."
        return f"{data['pincode']} is {data['area']}, in {data['district']}, {data['state']}."
    if tool == "request_call":
        return f"I've asked {args.get('recipient', 'your family')} to call you back soon."
    if tool == "share_update":
        return "I've sent your message to your family."
    if tool == "fetch_news":
        return "Here are today's headlines. " + ". ".join(data.get("headlines", [])) + "."
    if tool == "check_stock":
        return f"{data.get('medicine')} is {'in stock' if data.get('in_stock') else 'out of stock'} at the pharmacy."
    if tool == "order_medicine":
        return f"Your {data.get('medicine')} order is placed. It should arrive in about {data.get('eta_hours', 4)} hours."
    if tool == "create_payment_link":
        return f"A payment link for {data.get('amount_inr', 0):g} rupees has been sent to your family. Nobody pays without them."
    if tool == "verify_transaction":
        return "That payment is complete." if data.get("status") == "paid" else "That payment is still pending."
    if tool == "list_events":
        events = data.get("events", [])
        if not events:
            return "I couldn't find anything on your calendar."
        return "Coming up: " + _join(f"{e['summary']} on {e['start']}" for e in events[:3]) + "."
    if tool in ("create_event", "create_video_call"):
        return f"Done. {args.get('summary') or 'It'} is on the family calendar."
    if tool == "report_scam":
        return SCAM_EN
    if tool == "report_emergency":
        return EMERGENCY_EN
    if tool == "check_scam":
        if data.get("verdict") == "suspicious":
            return (
                "That sounds suspicious. Please don't send money or share any details yet. "
                "Talk to your family first. I can let them know if you like."
            )
        return (
            "I don't see clear signs of a scam. Still, never share an OTP, PIN or money with a caller, "
            "and check with your family if anything feels off."
        )
    if tool == "check_request_status":
        if data.get("status") == "done":
            return f"Good news: your family approved it. {data.get('outcome_speech', '')}".strip()
        return {
            "running": "Your family said yes. It's being done right now.",
            "pending": "Your family hasn't answered yet. It will happen as soon as they approve.",
            "rejected": "Your family said no this time. Maybe have a word with them.",
            "expired": "Your family didn't answer in time, so that request was cancelled.",
            "failed": "Your family approved it, but it couldn't be completed. I've let them know.",
            "unknown": "I couldn't find that request.",
        }.get(data.get("status"), "Your family approved it and it's done.")
    if tool == "verify_caller":
        if data.get("match") == "number":
            return f"That number is saved as {data['contact']}, your {data['relation']}. Even so, never share an OTP or PIN on a call."
        if data.get("match") == "name_only":
            return (
                f"I can't confirm that's really {data['contact']}. Please hang up and call {data['contact']} back "
                f"yourself on the saved number, {data['call_back_number']}. Don't send any money until you've spoken to them."
            )
        return (
            "That person isn't in your family's trusted list. Please don't give them money, an OTP or any details. "
            "Let's check with your family first."
        )
    if tool == "family_summary":
        parts = []
        a = data.get("adherence")
        if a:
            parts.append(f"In the last {data['days']} days, {a['taken']} of {a['expected']} medicine doses were taken.")
        if data.get("most_missed"):
            m = data["most_missed"]
            parts.append(f"{m['medicine']} is the one most often missed, {m['missed']} times.")
        vitals = data.get("latest_vitals") or {}
        if vitals:
            parts.append("Latest readings: " + _join(f"{VITAL_NAMES.get(k, k)} {v}" for k, v in vitals.items()) + ".")
        alerts = data.get("alerts") or []
        parts.append(f"{len(alerts)} safety alert{'s' if len(alerts) != 1 else ''}." if alerts else "No safety alerts.")
        if data.get("pending_approvals"):
            parts.append(f"{data['pending_approvals']} request{'s' if data['pending_approvals'] != 1 else ''} waiting for your approval.")
        if data.get("scam_watch"):
            parts.append("Money is paused right now after a scam alert.")
        return " ".join(parts)
    if tool in ("reply", "ask_followup"):
        return "I'm here with you."
    return "Done."


def pending_line(summary_en, family_name):
    return (
        f"That needs {family_name}'s okay, so I've sent them the request: {summary_en}. "
        "I'll tell you as soon as they answer."
    )


def describe(tool, args):
    """One-line English description of a gated request, for the elder and the family."""
    if tool == "order_medicine":
        quantity = args.get("quantity")
        return f"order {quantity or ''} {args['name']} {args.get('dosage') or ''}".replace("  ", " ").strip()
    if tool == "create_payment_link":
        return f"a payment link for {args['amount_inr']:g} rupees for {args['description']}"
    if tool == "create_event":
        return f"add '{args['summary']}' on {args['start']} to the family calendar"
    if tool == "create_video_call":
        return f"set up a video call with {args['recipient']} on {args['start']}"
    if tool == "fill_form":
        return f"fill the {args['form']} form"
    readable = ", ".join(f"{k}: {v}" for k, v in args.items())
    return f"{tool.replace('_', ' ')}" + (f" ({readable})" if readable else "")
