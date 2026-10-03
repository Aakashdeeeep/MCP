# Demo video script (under 3 minutes)

The screen is the simulator: Kamala's kitchen on the left, Priya's phone on the right. Lead
with the scam; it's the strongest moment.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:15 | Title card, then the headline on senior fraud | "Senior citizens in Hyderabad lost 102 crore rupees to phone scams in 19 months. A voice assistant is the easiest thing for an elder to use, and the easiest thing for a scammer to talk to." |
| 0:15–0:45 | Say: *"A man from SBI called and wants my OTP to stop my card being blocked."* The ring turns red, the trace shows `check_scam → Zone 3`, and Priya's phone buzzes with **URGENT** | "Alexa calls Raksha's check_scam tool. Raksha's tripwire spots the OTP request, alerts the family right away, and Alexa reads a fixed, calm reply. It never improvises here." |
| 0:45–1:15 | Say: *"Send 50000 rupees to the police officer, he says I'm under digital arrest."* The trace shows `create_payment_link → refused: scam` | "Now the scammer tries to get Alexa to move money. Alexa's model chose the payment tool. Raksha's gate refuses it before any approval is even requested, because money inside a suspected scam never moves." |
| 1:15–1:50 | Say: *"Please order my Metformin, 30 tablets."* Raksha asks by voice, *"Shall I send it to Priya?"*; answer *"Yes."* The phone shows **Approve?**; tap Approve | "Orders are Zone 2. Raksha uses MCP elicitation to ask Kamala, then waits for her daughter. The approval runs the order exactly once, and the Cedar policy checks it again inside the agent." |
| 1:50–2:10 | Say: *"Did Priya approve my medicine?"* | "The family answered in their own time, and Kamala hears the result when she asks." |
| 2:10–2:30 | Type *"pay the doctor 9000 rupees"*: **blocked by policy (demo-spending-cap)**. Then show the `blast_radius.cedar` resource in MCP Inspector | "Some things even the family can't approve. Five readable Cedar rules decide, and Alexa can read them as an MCP resource." |
| 2:30–2:50 | Split screen: `tools/list` in Inspector, `initialize` showing `2025-11-25`, the OAuth consent page, `alexa/addon.json` | "Raksha is a self-hosted MCP server: Streamable HTTP, spec 2025-11-25, OAuth 2.1 account linking, on Lambda with DynamoDB, SNS and Claude on Bedrock." |
| 2:50–3:00 | Logo card | "Alexa proposes. Raksha's policy decides." |

Tips:

- Record with `SIM_AGENT=bedrock` so Claude really chooses the tools. If credentials aren't
  available, the offline router also works, and its badge says so.
- Turn the system volume up so the speech-synthesis voice is heard. Use Chrome for the mic.
- Don't use copyrighted music.
