# Product feedback

*A draft from the build. The team will edit it with their own experience before submitting,
especially for the Alexa+ console, the CLI and device testing, which happen on their account.*

## MCP Python SDK (`mcp` 2.3.0): the server and the simulator's client

- **Used for:** `MCPServer`, Streamable HTTP (stateful locally, stateless on Lambda), tool
  annotations, `_meta`, icons, resources, prompts, form elicitation, and `Client` (in-process and
  over HTTP) for the tests and the simulator.
- **Worked well:** one codebase negotiates both 2025-11-25 and 2026-07-28. `Resolve(...)` plus
  `Elicit` made elicitation version-agnostic, and an in-process `Client(server)` made about 200 tests run
  in about 3 seconds. Protocol-version-header and batch rejection came for free.
- **Needs work:** the rename from `FastMCP` to `MCPServer` breaks every v1 tutorial (the error
  message does link the migration guide, which helped). On a stateless 2025-11-25 connection,
  `ctx.elicit` fails with `NoBackChannelError`. A capability flag such as `ctx.can_elicit` would
  save guesswork. Tool schemas come from function signatures, so generating tools from an
  existing registry meant hand-building `inspect.Signature` objects. An `add_tool(input_schema=…)`
  path would help. `TestClient` failed with 421 until we gave it a localhost base URL, because of
  the DNS-rebinding guard.
- **Again?** Yes.

## Amazon Bedrock: Claude in Amazon Bedrock (Mantle endpoint)

- **Used for:** `check_scam` (Claude Haiku 4.5 judges scams that use no keywords), and the
  simulator's agent loop (Claude chooses MCP tools from `tools/list`). Both use
  `AnthropicBedrockMantle` from the `anthropic` SDK.
- **Worked well:** it is the same Messages API as first-party, so the tool-use loop moved over
  unchanged. The `anthropic.`-prefixed model IDs are simple, and Haiku 4.5 is open to all
  accounts.
- **Needs work:** **structured outputs aren't supported** on this endpoint, so a JSON-schema
  response becomes a forced tool call. We found this from the docs only after writing the code.
  The IAM action (`bedrock-mantle:CreateInference`) is easy to miss: our earlier project's template
  still had a TODO with `bedrock:InvokeModel`.
- **Again?** Yes.

## AWS Lambda + Lambda Web Adapter, SAM, DynamoDB, SNS, Budgets

- **Used for:** running a standard ASGI MCP server unchanged on Lambda behind a Function URL,
  tables in the same shapes as Raksha OS, a TTL ledger for approvals and OAuth, SNS email to the
  family, and a cost guardrail.
- **Worked well:** Web Adapter means no Lambda-specific code: the same `uvicorn` app runs locally
  and in Lambda. DynamoDB conditional writes gave us run-exactly-once approvals cheaply.
- **Needs work:** the Function URL isn't known until the stack exists, so OAuth metadata and
  approval links can't be environment variables without a second deploy. We learn the URL from
  the first request instead.
- **Again?** Yes.

## Alexa+ MCP toolkit

- **Used for:** the `addon.json` package and OAuth 2.1 account linking requirements (RFC 9728
  metadata, PKCE S256, 401 without `WWW-Authenticate`).
- **Worked well:** building on the open MCP standard means one server serves Alexa+, MCP
  Inspector and our own simulator.
- **Needs work:** *(team to fill in from console, CLI and simulator testing)*. From the build
  environment we couldn't reach developer.amazon.com docs, and learned the checklist from public
  projects. A machine-readable conformance checker (`alexa-ai validate --mcp <url>`) would make the
  auth checklist much easier to get right.
