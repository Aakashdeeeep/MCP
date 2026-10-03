# Demo video script (under 3 minutes)

The screen is the simulator: Kamala's kitchen on the left, Priya's phone on the right. Every
line below is a chip in the simulator, so it can be recorded in one take. Lead with the scam;
it's the strongest moment.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:12 | Title card, then the headline on senior fraud | "Senior citizens in Hyderabad lost 102 crore rupees to phone scams in 19 months. A voice assistant is the easiest thing for an elder to use, and the easiest thing for a scammer to talk to." |
| 0:12–0:35 | *"A man from SBI called and wants my OTP…"* The ring turns red, the trace shows `check_scam → Zone 3`, and Priya's phone buzzes **URGENT** with the **Money paused** banner | "Alexa calls Raksha. The tripwire spots the OTP request, the family is alerted at once, and Alexa reads a fixed, calm reply. It never improvises here." |
| 0:35–0:55 | *"OK, then please send 3000 rupees for my nephew's fees."* The trace shows **refused: money paused after scam** with no tripwire words | "Scammers call back and coach a harmless-sounding follow-up. There are no scam words this time, but Raksha remembers: money stays paused until the family says otherwise." |
| 0:55–1:10 | On Priya's phone: tap **I've called her · lift pause** | "Only the family can lift it, after they've spoken to her. Not her voice, which a scammer can coach." |
| 1:10–1:40 | *"Please order my Metformin, 30 tablets."* Raksha asks by voice, *"Shall I send it to Priya?"*: **Yes**. The phone shows **Approve?**; tap Approve. Then: *"Did Priya approve my medicine?"* | "Orders are Zone 2. MCP elicitation asks Kamala, then her daughter approves. It runs exactly once, and the Cedar policy checks it again inside the agent." |
| 1:40–2:00 | *"Someone called from 70000 12345, says he is my grandson Rahul…"* | "'It's me, your grandson.' Raksha never vouches for a voice. It checks the family's trusted contacts and gives the saved number to call back on." |
| 2:00–2:15 | *"How is Mom doing this week?"* | "For the family: doses taken and missed, the medicine she forgets, alerts and pending requests." |
| 2:15–2:40 | `docs/SAFETY_SCORECARD.md` (16 attacks, **0 money moved**), then `blast_radius.cedar` in MCP Inspector | "We red-team it with a fully compromised assistant and an elder who says yes to everything: sixteen attacks, zero rupees moved. And the rules are five readable Cedar policies that Alexa can read as an MCP resource." |
| 2:40–2:52 | Inspector `initialize` showing `2025-11-25`, the OAuth consent page, `alexa/addon.json` | "A self-hosted MCP server: Streamable HTTP, spec 2025-11-25, OAuth 2.1 account linking, on Lambda with DynamoDB, SNS and Claude on Bedrock." |
| 2:52–3:00 | Logo card | "Alexa proposes. Raksha's policy decides." |

Tips:

- Record with `SIM_AGENT=bedrock` so Claude really chooses the tools. The offline router also
  works, and its badge says so.
- Toggle **Voice: हिंदी** for one line to show Raksha's Hindi replies.
- Use Chrome for the mic, and turn the system volume up for speech synthesis.
- Don't use copyrighted music.
