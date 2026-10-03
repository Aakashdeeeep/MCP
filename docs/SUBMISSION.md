# Devpost submission (draft)

**Name:** Raksha for Alexa+
**Tagline:** Alexa proposes. Raksha's policy decides. Safe voice help for elders, over MCP.
**Track:** Alexa+ (self-hosted MCP server, spec 2025-11-25, Streamable HTTP)
**Mini challenges:** AWS Builder, Open Source

## What it does
Raksha lets Alexa+ look after an older family member. Alexa can say which medicine is still due
today, log doses and blood-pressure readings, message the family, check the weather before a
walk, and find the nearest pharmacy. When the elder describes a suspicious call ("a man from SBI
wants my OTP"), Raksha alerts the family immediately and Alexa reads a calm, fixed reply. Orders,
payments and calendar changes are confirmed with the elder through MCP elicitation and then
approved by the family on their phone. A Cedar policy refuses anything unsafe, even with the
family's approval, and refuses any payment during a suspected scam.

## Why it stands out
- **Defends across turns, not sentences.** After a scam alert, money stays paused even for
  the scammer's keyword-free call-back, and only the family can lift it. An approval-fatigue
  limit stops floods of small requests, and `verify_caller` never vouches for a voice.
- **Measured, not claimed.** `python -m evals.redteam` runs 16 attacks through the real MCP
  server with a fully compromised assistant and an elder who says yes to everything:
  **0 money actions executed**. It runs in CI.
- **Readable rules.** The policy is Cedar, served to Alexa as an MCP resource, and every
  decision names the rule that fired.

## How it works
Every `tools/call` from Alexa passes a gate before any code acts. The gate checks the tool
registry, runs a scam and emergency tripwire over the elder's exact words and every argument,
applies a scam lock and a confidence floor, routes by blast-radius zone, and pre-checks Cedar.
Agents re-check Cedar themselves. Zone 3 alerts never wait. Zone 2 requests wait in DynamoDB
until the family taps Approve, and run exactly once.

The server uses the official MCP Python SDK. It is stateless Streamable HTTP on AWS Lambda,
behind a Function URL, with OAuth 2.1 + PKCE account linking, DynamoDB, SNS, and Claude on
Amazon Bedrock for scam judgement. An Alexa+ simulator, a separate MCP client with a voice UI,
shows the same flow when a device isn't available.

## Built during the hackathon vs. before
See `docs/WHATS_NEW.md`. In short: Raksha OS's safety core (registry, Cedar policy, tripwire,
agents) existed before and is copied unchanged. The MCP server, gate, elicitation, async
approvals, OAuth, voice tools, simulator, AWS deploy and tests are new.

## AWS Builder
- **Amazon Bedrock** (Claude Haiku 4.5): `check_scam` classifier in `raksha_mcp/voice_agent.py`.
- **Amazon Bedrock** (Claude): the simulator's agent loop in `simulator/app.py`.
- **AWS Lambda** + Lambda Web Adapter + Function URL: hosts the MCP server (`infra/template.yaml`,
  `Dockerfile`).
- **DynamoDB:** Raksha tables, plus a ledger for approvals, the feed and OAuth tokens (TTL).
- **SNS:** family alerts. **AWS Budgets:** cost guardrail.
- **CloudWatch:** every gate decision as an Embedded Metric Format metric, a dashboard
  (calls, blocked, sent for approval, family alerts by status), and a scam-spike alarm.

## Open Source
- Repo: https://github.com/Aakashdeeeep/MCP (MIT)
- GitHub usernames: Aakashdeeeep, Dhanya2810005
- Additional open-source project: **`mcp-blast-radius`** (`packages/mcp-blast-radius/`, MIT).
  It is a pip-installable library that puts zones, a Cedar policy, tripwire lockdowns, an
  approval-fatigue limit and exactly-once approvals in front of any MCP server's tools, behind
  one decorator, with an example server and tests. *(Publish it as its own repository before
  submitting, e.g. `github.com/Aakashdeeeep/mcp-blast-radius`, and use that as the
  contribution URL.)*
- Contribution URL: *(add the PR or fork link if you also contribute upstream, e.g. an example
  to the MCP Python SDK)*

## Links
- Demo video: *(YouTube link)*. A captioned cut is at `docs/demo/raksha-demo.mp4`.
- Feedback: `docs/FEEDBACK.md` · Friction log: `docs/FRICTION_LOG.md`
