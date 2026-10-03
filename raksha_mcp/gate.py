"""The gate: every Alexa+ tool call passes through here before any Raksha agent runs.

In Raksha OS our own planner proposed tasks and deterministic code validated them. On
Alexa+ the planner is Alexa's model, which we don't control. So the gate re-applies every
rule Raksha already enforces, in the same order, using Raksha's own code:

  1. registry      unknown tool or malformed args -> nothing runs (planner.check_args)
  2. tripwire      scam / emergency keywords in the elder's words or the args -> Zone 3
                   alert to the family immediately (Raksha's tripwire + tripwire_en for English)
  3. scam lock     a money or Zone 2 request inside a suspected scam is refused outright
     scam watch    after any scam alert, money stays paused across turns (the scammer's
                   keyword-free call-back) until it expires or the family lifts it
     fatigue limit at most MAX_PENDING_MONEY money requests wait for the family at once
  4. confidence    a Zone 0/1 call the assistant wasn't sure about becomes Zone 2
                   (planner.apply_confidence_floor)
  5. zone          0/1 run now; 2 waits for the family; 3 runs now, never waits
  6. Cedar         the agent itself asks policies/blast_radius.cedar before acting
                   (raksha_common.agent.run_tool), and Zone 2 is pre-checked with
                   approved=true so the family is never asked to approve something the
                   policy would forbid anyway (e.g. above the spending cap)

The gate returns an Outcome dict; server.py turns it into an MCP CallToolResult.
"""
import uuid
from datetime import datetime, timedelta, timezone

import planner
import tripwire
from raksha_common.policy import authorize
from raksha_common.tool_registry import get_tool

from raksha_mcp import agents, config, ledger, metrics, tripwire_en, voice
from raksha_mcp import voice_agent  # noqa: F401 - registers the raksha-voice tools

CONFIDENCE_FLOOR = planner.CONFIDENCE_FLOOR

REPEAT_EN = "Sorry, I didn't quite catch that. Could you say it once more?"
REPEAT_HI = planner.CLARIFY_REPLY_HI
SCAM_LOCK_EN = (
    "I won't do that right now, because this sounds like a scam. Please don't send any money. "
)
POLICY_BLOCK_EN = "I can't do that. Raksha's safety rules don't allow it, even with your family's okay."
POLICY_BLOCK_HI = "माफ़ कीजिए, Raksha के सुरक्षा नियम इसकी इजाज़त नहीं देते, परिवार की हाँ के साथ भी नहीं।"
SCAM_WATCH_EN = (
    "Because of the suspicious call earlier, I've paused anything to do with money for now. "
    "{family} can lift the pause after talking with you. Please don't send money to anyone who calls."
)
SCAM_WATCH_HI = "पहले आई संदिग्ध कॉल की वजह से मैंने पैसों से जुड़े सारे काम अभी रोक दिए हैं। परिवार से बात होने के बाद ही ये दोबारा शुरू होंगे।"
TOO_MANY_EN = "There are already requests about money waiting for {family}. Let's wait for their answer first."
TOO_MANY_HI = "परिवार के पास पैसों से जुड़े अनुरोध पहले से रुके हुए हैं। पहले उनका जवाब आने दीजिए।"
CANCELLED_EN = "Okay, I won't send that request."
CANCELLED_HI = "ठीक है, मैंने वह अनुरोध नहीं भेजा।"


def _texts(value):
    """Every string inside the args, so a scam phrase in any field is seen by the tripwire."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)
    elif isinstance(value, list):
        for v in value:
            yield from _texts(v)


def preview(agent, tool, args, confidence, utterance=""):
    """Would handle() send this to the family? Decides whether to ask the elder first.

    Mirrors handle()'s checks without side effects, so the elder is never asked to confirm a
    request the gate is about to refuse (a scam payment, or one over the spending cap)."""
    spec = get_tool(agent, tool)
    if spec is None or planner.check_args(spec, args):
        return {"needs_approval": False}
    if (spec["zone"] == 2 or spec.get("moves_money")) and tripwire_en.scam_signals(" ".join([utterance or "", *_texts(args)])):
        return {"needs_approval": False}
    if spec.get("moves_money") and (ledger.scam_watch() or ledger.pending_money_count() >= config.MAX_PENDING_MONEY):
        return {"needs_approval": False}
    task = planner.apply_confidence_floor(
        {"agent": agent, "tool": tool, "args": args, "zone": spec["zone"], "confidence": _clamp(confidence)}
    )
    if task["zone"] != 2 or not authorize(task, {"approval": {"approved": True}})["allowed"]:
        return {"needs_approval": False}
    return {"needs_approval": True, "summary_en": voice.describe(tool, args)}


def handle(agent, tool, args, utterance="", confidence=1.0, elder_confirmed=True):
    request_id = f"mcp-{uuid.uuid4().hex[:10]}"
    args = {k: v for k, v in (args or {}).items() if v is not None}
    outcome = {
        "request_id": request_id,
        "tool": f"{agent}.{tool}",
        "status": None,
        "speech": "",
        "hindi": "",
        "zone": None,
        "effective_zone": None,
        "tripwire": [],
        "alerts": [],
        "policy": None,
        "result": {},
        "mocked": False,
    }

    # 1. registry
    spec = get_tool(agent, tool)
    problems = ["unknown tool"] if spec is None else planner.check_args(spec, args)
    if problems:
        return _finish(outcome, "needs_repeat", REPEAT_EN, REPEAT_HI, problems=problems)
    outcome["zone"] = spec["zone"]

    # 2. tripwire, on the elder's own words and on every string the assistant passed us
    text = " ".join([utterance or "", *_texts(args)])
    signals = {
        "report_scam": tripwire_en.scam_signals(text),
        "report_emergency": tripwire_en.emergency_signals(text),
    }
    for panic_tool, hits in signals.items():
        if hits and not (agent == "scam-shield" and tool == panic_tool):
            outcome["tripwire"].extend(hits)
            task = tripwire.tripwire_task(panic_tool, f"{request_id}-{panic_tool}", hits, where="Alexa conversation")
            outcome["alerts"].append(_run_panic(task, utterance, request_id))

    # 3. scam lock: never ask the family to approve a payment inside a suspected scam
    if signals["report_scam"] and (spec["zone"] == 2 or spec.get("moves_money")):
        return _finish(outcome, "blocked_scam", SCAM_LOCK_EN + voice.SCAM_EN, "", effective_zone=3)

    # 3b. scam watch: a scam alert in an earlier turn still blocks money now. The scammer's
    #     call-back ("just send 5000 to this account, Amma") carries no keywords at all.
    if spec.get("moves_money"):
        watch = ledger.scam_watch()
        if watch:
            return _finish(
                outcome, "blocked_scam_watch", SCAM_WATCH_EN.format(family=config.FAMILY_NAME), SCAM_WATCH_HI,
                effective_zone=3, scam_watch=watch,
            )
        # 3c. approval fatigue: don't let a flood of small requests wear the family down
        if ledger.pending_money_count() >= config.MAX_PENDING_MONEY:
            return _finish(outcome, "blocked_too_many", TOO_MANY_EN.format(family=config.FAMILY_NAME), TOO_MANY_HI)

    # 4. confidence floor
    task = planner.apply_confidence_floor(
        {
            "task_id": request_id,
            "agent": agent,
            "tool": tool,
            "args": args,
            "zone": spec["zone"],
            "confidence": _clamp(confidence),
            "summary_en": voice.describe(tool, args),
        }
    )
    outcome["effective_zone"] = task["zone"]

    # 5. zone 2: ask the family (after a Cedar pre-check)
    if task["zone"] == 2:
        precheck = authorize(task, {"approval": {"approved": True}})
        if not precheck["allowed"]:
            return _finish(outcome, "blocked_policy", POLICY_BLOCK_EN, POLICY_BLOCK_HI, policy=precheck)
        if not elder_confirmed:
            return _finish(outcome, "cancelled", CANCELLED_EN, CANCELLED_HI)
        approval = request_family_approval(task, utterance)
        outcome["approval_id"] = approval["id"]
        return _finish(
            outcome,
            "pending_family_approval",
            voice.pending_line(task["summary_en"], config.FAMILY_NAME),
            "यह काम परिवार की हाँ के बाद होगा। मैंने उन्हें अनुरोध भेज दिया है।",
            policy=precheck,
        )

    # 5. zones 0, 1, 3: run now (Cedar is checked again inside the agent)
    if agent == "scam-shield" and any(a["tool"] == tool for a in outcome["alerts"]):
        # the tripwire already raised this exact alert; don't alert the family twice
        alert = next(a for a in outcome["alerts"] if a["tool"] == tool)
        return _finish(outcome, "alerted", alert["speech"], alert["hindi"], policy=alert["policy"])
    try:
        output = agents.run(task, utterance, request_id)
    except PermissionError as denied:
        return _finish(outcome, "blocked_policy", POLICY_BLOCK_EN, POLICY_BLOCK_HI, policy={"allowed": False, "reasons": [str(denied)]})

    data = output.get("result") or {}
    escalate = data.get("escalate")
    if escalate and not any(a["tool"] == escalate["tool"] for a in outcome["alerts"]):
        panic = {**escalate, "task_id": f"{request_id}-escalate", "zone": 3, "confidence": 1.0, "source": "check_scam"}
        outcome["alerts"].append(_run_panic(panic, utterance, request_id))
    speech = voice.done_line(tool, args, data)
    hindi = output.get("reply_text", "")
    if escalate:
        speech, hindi = voice.SCAM_EN, outcome["alerts"][-1]["hindi"]
    status = "alerted" if spec["zone"] == 3 or escalate else "done"
    return _finish(
        outcome, status, speech, hindi, policy=output.get("policy"), result=data,
        mocked=bool(output.get("mocked")), mock_reason=output.get("mock_reason"),
    )


def _run_panic(task, utterance, request_id):
    """Zone 3. Never waits on anything. Returns a compact record for the outcome."""
    try:
        output = agents.run(task, utterance, request_id)
        ok = True
    except Exception as error:  # noqa: BLE001 - the elder still hears the calm guidance
        print(f"panic alert failed: {error!r}")
        output, ok = {"reply_text": "", "result": {}, "policy": None}, False
    if task["tool"] == "report_scam":
        watch = ledger.set_scam_watch(task["args"].get("description", "scam alert"), config.SCAM_WATCH_MINUTES)
        ledger.record(
            "scam_watch_on", f"Money paused for {config.SCAM_WATCH_MINUTES // 60 or 1}h after a scam alert", until=watch["until"]
        )
    title = "Scam alert sent to family" if task["tool"] == "report_scam" else "Emergency alert sent to family"
    ledger.record(
        "alert", title, tool=task["tool"], zone=3, tripwire=task["args"].get("indicators") or [],
        utterance=utterance, delivered=ok, policy=output.get("policy"),
    )
    return {
        "tool": task["tool"],
        "delivered": ok,
        "speech": voice.done_line(task["tool"], task["args"], output.get("result") or {}),
        "hindi": output.get("reply_text", ""),
        "policy": output.get("policy"),
    }


def request_family_approval(task, utterance):
    now = datetime.now(timezone.utc)
    approval = {
        "id": uuid.uuid4().hex[:12],
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=config.APPROVAL_TTL_SECONDS)).isoformat(),
        "agent": task["agent"],
        "tool": task["tool"],
        "args": task["args"],
        "confidence": task["confidence"],
        "forced_by_confidence": task.get("forced_by_confidence", False),
        "summary_en": task["summary_en"],
        "utterance": utterance,
        "moves_money": bool((get_tool(task["agent"], task["tool"]) or {}).get("moves_money")),
    }
    spec = get_tool(task["agent"], task["tool"]) or {}
    watch = ledger.scam_watch()
    if watch:
        approval["scam_watch"] = watch
    ledger.put_approval(approval)
    if spec.get("moves_money"):
        ledger.add_pending_money(approval["id"], approval["expires_at"])
    link = f"{config.PUBLIC_BASE_URL}/approval/{approval['id']}"
    body = (
        f"{config.ELDER_NAME} asked Alexa for something that needs your approval.\n\n"
        f"Request: {approval['summary_en']}\n"
        f"Exactly what will run ({task['agent']}.{task['tool']}): "
        + "; ".join(f"{k}: {v}" for k, v in task["args"].items())
        + (f"\nWhat they said: \"{utterance}\"" if utterance else "")
        + ("\n(Alexa wasn't sure it understood. Please double-check.)" if approval["forced_by_confidence"] else "")
        + (f"\nWARNING: a scam alert fired at {watch['since'][11:16]} UTC. Please call them before approving." if watch else "")
        + f"\n\nApprove or reject: {link}\nIf you do nothing, it expires in {config.APPROVAL_TTL_SECONDS // 60} minutes."
    )
    from raksha_common.notify import notify_caregiver

    try:
        sent = notify_caregiver("Raksha: approval needed", body)
    except Exception as error:  # noqa: BLE001 - the feed still shows the request
        print(f"approval notification failed: {error!r}")
        sent = {"error": str(error)}
    ledger.record("approval_request", f"Approval needed: {approval['summary_en']}", approval_id=approval["id"], link=link, channels=sent)
    return approval


def _clamp(confidence):
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return 0.0  # unknown confidence is treated as low, exactly like the planner
    return max(0.0, min(1.0, float(confidence)))


def _finish(outcome, status, speech, hindi, **extra):
    alerts = outcome["alerts"]
    if alerts and status not in ("alerted", "blocked_scam"):
        # a panic alert fired alongside the request: lead with the calm guidance
        speech = f"{alerts[0]['speech']} {speech}".strip()
        hindi = f"{alerts[0]['hindi']} {hindi}".strip()
    outcome.update(status=status, speech=speech, hindi=hindi, **extra)
    if outcome["effective_zone"] is None:
        outcome["effective_zone"] = outcome["zone"]
    ledger.record(
        "decision",
        f"{outcome['tool']}: {status}",
        status=status,
        zone=outcome["zone"],
        effective_zone=outcome["effective_zone"],
        tripwire=outcome["tripwire"],
        policy=outcome.get("policy"),
        speech=speech,
        mocked=outcome.get("mocked", False),
    )
    metrics.emit(status, outcome["tool"], len(alerts))
    return outcome
