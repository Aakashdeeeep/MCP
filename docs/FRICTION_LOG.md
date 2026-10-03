# Friction log

These entries were recorded while building. The team adds entries from their own Alexa+ console
and device testing before submitting.

### 1. Structured outputs on Claude in Amazon Bedrock
- **Task:** get a strict JSON scam verdict from Claude Haiku 4.5 on Bedrock.
- **Steps:** wrote `messages.create(..., output_config={"format": {"type": "json_schema", ...}})`
  with `AnthropicBedrockMantle`, the same code that works first-party.
- **Expected:** the same feature set as first-party, since it's the same Messages API.
- **Actual:** the Bedrock Messages-API page lists structured outputs as *not supported*.
- **Severity:** medium (it silently forces a redesign).
- **Workaround:** a single forced tool (`tool_choice: {"type": "tool"}`) whose `input_schema` is
  the verdict schema, with every field validated in code.
- **Suggestion:** support `output_config.format`, or have the SDK raise a clear client-side error
  when it's used against the Mantle base URL.

### 2. IAM action for the Mantle endpoint
- **Task:** grant the Lambda permission to call Claude.
- **Steps:** copied `bedrock:InvokeModel` from our earlier template, which carried a
  "TODO: confirm actions".
- **Expected:** the Bedrock actions people already know.
- **Actual:** the endpoint needs `bedrock-mantle:CreateInference`.
- **Severity:** medium (a deploy succeeds, then calls fail at runtime).
- **Workaround:** read the auth section of the Claude-in-Bedrock docs.
- **Suggestion:** a managed policy (`AmazonBedrockMantleInvokeAccess`), and an error message that
  names the missing action.

### 3. Elicitation on stateless Streamable HTTP (2025-11-25)
- **Task:** ask the elder to confirm before sending a request to the family, on Lambda.
- **Steps:** `ctx.elicit(...)` inside a tool, with `stateless_http=True`.
- **Expected:** elicitation works, or the client gets a clean "unsupported".
- **Actual:** `NoBackChannelError`: a stateless 2025-11-25 request has no channel for
  server-initiated requests. On 2026-07-28, `InputRequiredResult` works statelessly.
- **Severity:** medium.
- **Workaround:** use `Resolve`/`Elicit` and only ask when the connection can carry it. The
  family's approval stays the real gate either way.
- **Suggestion:** document which MCP features Alexa+ supports on which transport mode, and expose
  `ctx.can_elicit` in the SDK.

### 4. The Function URL is unknown at deploy time
- **Task:** OAuth metadata (`issuer`, `resource`) and approval links need the public URL.
- **Expected:** a CloudFormation reference.
- **Actual:** a circular dependency between the function and its own URL.
- **Severity:** low.
- **Workaround:** learn the base URL from the first request's Host header, or set
  `PUBLIC_BASE_URL` on a second deploy.
- **Suggestion:** expose the Function URL to the function as an environment variable automatically.

### 5. Alexa+ developer docs unreachable from a locked-down build environment
- **Task:** read the MCP toolkit quickstart and account-linking checklist.
- **Actual:** developer.amazon.com was blocked by the build sandbox's network policy. We learned
  the checklist from open-source projects that cite it.
- **Severity:** low (environmental), but it shows the value of a public, versioned spec.
- **Suggestion:** mirror the MCP add-on checklist in a public GitHub repository, with a
  conformance test suite.
