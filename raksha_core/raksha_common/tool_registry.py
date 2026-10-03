"""Single source of truth for every agent, its tools, and each tool's blast-radius zone.

The planner prompt, the planner's validation, and each agent Lambda all read from here.
The LLM picks agent + tool + args. The ZONE (and moves_money) is always set by this registry
in code, never by the LLM. policies/blast_radius.cedar turns these facts into allow/deny.

Zones:
  0 = conversational (reply only)
  1 = autonomous (internal / read-only, no cost, no outside party acting)
  2 = human-gated (money, orders, forms: needs caregiver approval)
  3 = panic override (scam / emergency: alert immediately)

Each agent is one Lambda named "<stack>-agent-<agent id>". Tools are MCP-style:
a name, a description, and a small argument schema.

Two more facts per tool, also enforced in code rather than trusted to the model:
  returns    result fields the tool ALWAYS produces (live or mocked). A later task may only
             reference these, as {{t1.address}}; see raksha_common/dependencies.py.
  read_only  the tool only looks things up. Only read-only tools may be chosen by the
             mid-execution re-plan; see bedrock_planner/replan.py. An argument marked
             side_effect (like share_with_family) is always removed from a re-planned task.
"""

AGENTS = {
    "conversation": {
        "description": "Chit-chat, complaints, loneliness, anything unclear. Warm reply only. Never diagnose.",
        "tools": {
            "reply": {
                "zone": 0,
                "description": "Give a warm spoken reply. Optionally leave a low-priority note for the caregiver.",
                "args": {"caregiver_note": {"type": "string", "required": False}},
            },
            "ask_followup": {
                "zone": 0,
                "clarifies": True,  # asking IS the uncertainty handling, so no confidence floor
                "description": "A need is missing a detail you would otherwise have to guess (which medicine, how much, which reading). Ask the elder ONE short, simple question in Hindi; their next voice memo will be planned with this context.",
                "args": {
                    "question_hi": {"type": "string", "required": True},
                    "about": {"type": "string", "required": True},  # English: what's missing, e.g. "which medicine to order"
                },
            },
        },
    },
    "document-reader": {
        "description": (
            "Papers the elder photographs: bank and pension letters, bills, prescriptions, "
            "government notices, insurance papers. Use these tools ONLY when a <document> is "
            "attached to the memo. Explaining is Zone 0; acting on what the paper says (ordering "
            "the medicine on a prescription, paying a bill) belongs to the normal agent for that job."
        ),
        "tools": {
            "explain": {
                "zone": 0,
                "description": (
                    "Read a photographed document back in simple Hindi: what it is, what it asks for, "
                    "what the elder has to do and by when. Put the explanation in reply_text_hi. "
                    "Never guess at text you cannot read, and never read out account or ID numbers."
                ),
                "args": {
                    # bank_letter | bill | prescription | government_notice | insurance | pension | other
                    "doc_type": {"type": "string", "required": True},
                    "key_points": {"type": "array", "required": False},  # short English notes for the family
                    "deadline": {"type": "string", "required": False},  # a date printed on the paper, if any
                },
            },
            "share_with_family": {
                "zone": 1,
                "description": (
                    "Send the document's summary and photo to the family, for a paper the elder should "
                    "not have to deal with alone."
                ),
                "args": {
                    "doc_type": {"type": "string", "required": True},
                    "reason": {"type": "string", "required": True},
                },
            },
        },
    },
    "health-log": {
        "description": "Record and read the elder's vitals.",
        "tools": {
            "log_vitals": {
                "zone": 1,
                "description": "Log one vitals reading. vital_type is one of blood_sugar, blood_pressure, weight, temperature, pulse.",
                "args": {
                    "vital_type": {"type": "string", "required": True},
                    "value": {"type": "string", "required": True},  # string so "130/85" works for BP
                    "unit": {"type": "string", "required": False},
                },
            },
            "get_history": {
                "zone": 1,
                "read_only": True,
                "description": "Read back recent vitals readings.",
                "args": {
                    "vital_type": {"type": "string", "required": False},
                    "days": {"type": "integer", "required": False},
                },
            },
        },
    },
    "pharmacy-order": {
        "description": "Order medicines. Always needs caregiver approval.",
        "tools": {
            "order_medicine": {
                "zone": 2,
                "moves_money": True,
                "description": "Order a medicine refill.",
                "args": {
                    "name": {"type": "string", "required": True},
                    "dosage": {"type": "string", "required": False},
                    "quantity": {"type": "integer", "required": False},
                },
            },
            "check_stock": {
                "zone": 1,
                "read_only": True,
                "returns": ["medicine", "in_stock"],
                "description": "Check whether a medicine is in stock at the pharmacy.",
                "args": {"name": {"type": "string", "required": True}},
            },
        },
    },
    "scam-shield": {
        "description": "Panic override. Scams: fake bank/RBI/police officer, OTP or PIN requests, KYC threats, 'digital arrest', lottery, urgent money transfer. Emergencies: fall, chest pain, breathing trouble.",
        "tools": {
            "report_scam": {
                "zone": 3,
                "description": "A likely scam was described. Alert the caregiver immediately.",
                "args": {
                    "scam_type": {"type": "string", "required": True},  # e.g. bank_otp, digital_arrest, kyc, lottery
                    "description": {"type": "string", "required": True},
                    "indicators": {"type": "array", "required": False},
                },
            },
            "report_emergency": {
                "zone": 3,
                "description": "A possible medical emergency was described. Alert the caregiver immediately. Do not diagnose.",
                "args": {"description": {"type": "string", "required": True}},
            },
        },
    },
    "family-bridge": {
        "description": "Stay connected with family and hear the news.",
        "tools": {
            "request_call": {
                "zone": 1,
                "description": "Ask a family member to call the elder back.",
                "args": {"recipient": {"type": "string", "required": True}},
            },
            "share_update": {
                "zone": 1,
                "description": "Send a short message from the elder to the family.",
                "args": {"message": {"type": "string", "required": True}},
            },
            "fetch_news": {
                "zone": 1,
                "read_only": True,
                "description": "Read out today's top news headlines.",
                "args": {"topic": {"type": "string", "required": False}},
            },
        },
    },
    "care-coordinator": {
        "description": "Doctor's care plan: medicine adherence and weather-aware activity advice.",
        "tools": {
            "log_dose": {
                "zone": 1,
                "description": "Record that the elder took (or skipped) a medicine dose.",
                "args": {
                    "medicine": {"type": "string", "required": True},
                    "taken": {"type": "boolean", "required": True},
                },
            },
            "get_adherence": {
                "zone": 1,
                "read_only": True,
                "description": "Summarise how many doses were taken vs missed recently.",
                "args": {"days": {"type": "integer", "required": False}},
            },
            "check_weather": {
                "zone": 1,
                "read_only": True,
                "returns": ["condition", "temp_c"],
                "description": "Check the weather before an outdoor activity like a walk.",
                "args": {"activity": {"type": "string", "required": False}},
            },
        },
    },
    "location-finder": {
        "description": "Find nearby places and look up pincodes.",
        "tools": {
            "find_nearest": {
                "zone": 1,
                "read_only": True,
                "returns": ["name", "address", "distance_km"],
                "description": "Find a nearby hospital, pharmacy, restaurant, cafe, library, temple, or park near the elder's registered home, include opening and Google rating details when available, and optionally share the destination with family.",
                "args": {
                    "place_type": {"type": "string", "required": True},  # hospital | pharmacy | restaurant | cafe | library | temple | park
                    "share_with_family": {"type": "boolean", "required": False, "side_effect": True},
                },
            },
            "lookup_pincode": {
                "zone": 1,
                "read_only": True,
                "returns": ["pincode", "area", "district", "state"],
                "description": "Look up the area / district for an Indian pincode.",
                "args": {"pincode": {"type": "string", "required": True}},
            },
        },
    },
    "calendar-assistant": {
        "description": "Help the elder keep a social life: read upcoming plans and schedule outings such as dinner, library visits, temple visits, or time in the park.",
        "tools": {
            "list_events": {
                "zone": 1,
                "read_only": True,
                "description": "Read the caregiver calendar's upcoming events. Do not change anything.",
                "args": {"days": {"type": "integer", "required": False}},
            },
            "create_event": {
                "zone": 2,
                "description": "Add an outing or appointment to the caregiver calendar after approval. Never invite guests automatically. start/end are ISO 8601 with the India offset, e.g. 2026-09-19T10:00:00+05:30, worked out from <now>.",
                "args": {
                    "summary": {"type": "string", "required": True},
                    "start": {"type": "string", "required": True},
                    "end": {"type": "string", "required": False},
                    "location": {"type": "string", "required": False},
                    "description": {"type": "string", "required": False},
                },
            },
            "create_video_call": {
                "zone": 2,
                "returns": ["meet_url"],
                "description": "Create a Google Meet family call after caregiver approval. Do not invent family email addresses; invite only explicitly supplied addresses. start/end are ISO 8601 with the India offset, e.g. 2026-09-19T10:00:00+05:30, worked out from <now>.",
                "args": {
                    "recipient": {"type": "string", "required": True},
                    "start": {"type": "string", "required": True},
                    "end": {"type": "string", "required": False},
                    "summary": {"type": "string", "required": False},
                    "message": {"type": "string", "required": False},
                    "attendee_emails": {"type": "array", "required": False},
                },
            },
        },
    },
    "web-assistant": {
        "description": "Fill online forms such as a teleconsultation appointment booking. Always needs approval.",
        "tools": {
            "fill_form": {
                "zone": 2,
                "description": "Book a teleconsultation appointment by filling the booking form.",
                "args": {
                    "form": {"type": "string", "required": True},  # e.g. teleconsult_booking
                    "speciality": {"type": "string", "required": False},
                    "preferred_date": {"type": "string", "required": False},
                },
            },
        },
    },
    "payment-assistant": {
        "description": "Payments such as a doctor's fee. Creates a payment link for the caregiver; never pays by itself.",
        "tools": {
            "create_payment_link": {
                "zone": 2,
                "moves_money": True,
                "description": "Create a UPI payment link for an amount in rupees.",
                "args": {
                    "amount_inr": {"type": "number", "required": True},
                    "description": {"type": "string", "required": True},
                },
            },
            "verify_transaction": {
                "zone": 1,
                "read_only": True,
                "returns": ["payment_link_id", "status"],
                "description": "Check the status of an earlier payment link.",
                "args": {"payment_link_id": {"type": "string", "required": True}},
            },
        },
    },
}

PYTHON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
}


def get_tool(agent, tool):
    """Return the tool spec, or None if the agent/tool pair doesn't exist."""
    return AGENTS.get(agent, {}).get("tools", {}).get(tool)


def all_tool_names():
    return sorted({tool for spec in AGENTS.values() for tool in spec["tools"]})


def tool_catalog_text():
    """Human-readable catalog injected into the planner system prompt."""
    lines = []
    for agent, spec in AGENTS.items():
        lines.append(f"## agent: {agent}\n{spec['description']}")
        for tool, tspec in spec["tools"].items():
            args = ", ".join(
                f"{name}: {a['type']}{'' if a['required'] else ' (optional)'}" for name, a in tspec["args"].items()
            ) or "no args"
            line = f"- tool `{tool}` [zone {tspec['zone']}]: {tspec['description']} Args: {args}"
            if tspec.get("returns"):
                line += f" Returns: {', '.join(tspec['returns'])}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def read_only_tools():
    """(agent, tool) pairs the mid-execution re-plan is allowed to choose from."""
    return sorted((agent, tool) for agent, spec in AGENTS.items() for tool, t in spec["tools"].items() if t.get("read_only"))


def read_only_catalog_text():
    """The catalog the re-plan sees: read-only tools only, so it cannot even name anything else."""
    lines = []
    for agent, tool in read_only_tools():
        tspec = AGENTS[agent]["tools"][tool]
        args = ", ".join(
            f"{name}: {a['type']}{'' if a['required'] else ' (optional)'}"
            for name, a in tspec["args"].items()
            if not a.get("side_effect")
        ) or "no args"
        lines.append(f"- `{agent}.{tool}`: {tspec['description']} Args: {args}")
    return "\n".join(lines)
