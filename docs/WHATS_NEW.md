# What we built during the hackathon window

Raksha OS existed before this hackathon. This page separates that earlier work from what was
built for the Alexa+ track, so judges can see exactly what is new.

## Before (pre-existing)

**Raksha OS (IntentOS: Bharat Edition)**, built for AWS First Commit, Bharat Builds Tour.

- Repository: https://github.com/Dhanya2810005/Raksha
- Baseline commit: `1733c891fce0c20c3add6b7439ad743a3d1e0716` (2026-09-18)

It is a serverless pipeline for Hindi voice memos. An elder records a memo, it goes through
Transcribe, then **our own planner** (Claude on Bedrock) compiles it into a JSON plan, and a fixed
Step Functions state machine runs the plan through agent Lambdas. It includes:

- the tool registry with blast-radius zones 0–3
- the Cedar policy and its Python fallback
- the keyword tripwire, the confidence floor and planner validation
- the agents (care coordinator, health log, pharmacy, payments, scam shield, family bridge, location, calendar)
- caregiver approval through `.waitForTaskToken`

That code is copied **unchanged** into `raksha_core/`. Running `diff -r` against the baseline
shows no differences; `raksha_core/README.md` maps every file to its original path.

## New: built during the hackathon

Raksha OS trusted its own planner and validated it in a state machine. For Alexa+ the planner is
someone else's model, reaching us over MCP, so everything below is new.

| Area | Files | What it does |
|---|---|---|
| MCP server | `raksha_mcp/server.py` | MCP 2.3 SDK `MCPServer`. Streamable HTTP at `/mcp`, protocol 2025-11-25 (and 2026-07-28), stateless mode for Lambda. 21 tools generated from the registry, with annotations and zone metadata, 4 resources and 2 prompts. |
| The gate | `raksha_mcp/gate.py` | Re-applies Raksha's rules to an untrusted planner on every call: registry, tripwire on the elder's words *and* every argument, the new **scam lock**, confidence floor, zone routing, and a **Cedar pre-check**, so the family is never asked to approve something the policy forbids. |
| Elicitation | `raksha_mcp/server.py` (`_confirm_resolver`) | Asks the elder before a Zone 2 request goes to the family. Version-aware: it uses a back-channel request on 2025-11-25 and `InputRequiredResult` on 2026-07-28. It never asks about a request the gate will refuse. |
| Async approvals | `raksha_mcp/approvals.py`, `ledger.py` | Replaces Step Functions task tokens, which can't outlive an MCP call: requests wait in DynamoDB, the family approves on a web page, and conditional writes make each approval run exactly once. The elder asks `check_request_status` later. |
| Voice-first tools | `raksha_mcp/voice_agent.py` | `todays_medicines`, `check_scam` (tripwire, then Claude Haiku 4.5 on Bedrock for scams that use no keywords), `verify_caller` (trusted contacts, call-back number), `family_summary` and `check_request_status`. They are registered in Raksha's registry, so the same Cedar policy covers them. |
| Cross-turn defences | `raksha_mcp/gate.py`, `ledger.py`, `approvals.py` | **Scam watch:** after a scam alert, money stays paused across turns until it expires or the family lifts it, and earlier requests can't be approved meanwhile. **Approval-fatigue limit** on pending money requests. |
| English tripwire | `raksha_mcp/tripwire_en.py` | English scam and emergency shapes on top of Raksha's Hinglish/Devanagari patterns, with false-positive tests. |
| Red-team eval | `evals/redteam.py`, `docs/SAFETY_SCORECARD.md` | 16 attacks with a compromised assistant and an elder who agrees to everything. 0 money moved, and it runs in CI. |
| English voice | `raksha_mcp/voice.py` | Fixed English sentences for Alexa, with Raksha's Hindi line kept alongside. |
| Account linking | `raksha_mcp/oauth.py`, `web.py` | OAuth 2.1 with PKCE S256, RFC 9728 and RFC 8414 metadata, a consent page guarded by the family passcode, single-use codes and rotating refresh tokens. Bare 401s and an Origin check. |
| Family pages | `raksha_mcp/web.py` | Approval page and a live family feed showing every gate decision and Cedar reason. |
| Alexa+ simulator | `simulator/` | A separate MCP client with a voice UI (Web Speech), Claude on Bedrock choosing tools from `tools/list`, spoken elicitation, and the family's phone with Approve/Reject. |
| AWS | `infra/template.yaml`, `Dockerfile`, `scripts/seed_demo.py` | Lambda container with Web Adapter and a Function URL, DynamoDB with TTL, SNS, the Bedrock Mantle IAM action, and a Budget. |
| Alexa+ package | `alexa/` | `addon.json`, generated icons, privacy and terms. |
| Tests | `tests/` | 198 tests, including red-team cases where Alexa or a scammer speaking through Alexa tries to move money. |
