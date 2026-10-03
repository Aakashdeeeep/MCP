# raksha_core: vendored from Raksha OS (pre-existing work)

Everything in this folder was written **before** the Amazon Developer Hackathon, as part of
Raksha OS (IntentOS: Bharat Edition), and is copied here unchanged so the MCP server runs
the exact same safety code.

- Source: https://github.com/Dhanya2810005/Raksha
- Commit: `1733c891fce0c20c3add6b7439ad743a3d1e0716` (2026-09-18, "Base serveless architecture")

| Here | Original path |
|---|---|
| `raksha_common/` | `src/shared/raksha_common/` (tool registry, Cedar policy + engine, agent dispatch, notify, adherence, redact...) |
| `tripwire.py` | `src/bedrock_planner/tripwire.py` |
| `planner.py` | `src/bedrock_planner/planner.py` (only its pure validation helpers are used) |
| `agents/<name>.py` | `src/agents/<name>/app.py` |

The only additions to the shared registry happen at runtime, from new code:
`raksha_mcp/voice_agent.py` registers three Alexa-specific tools under a new
`raksha-voice` agent. Nothing in this folder is edited; `diff -r` against the commit above
shows no changes.
