# Raksha as an Alexa+ add-on

`addon.json` packages the Raksha MCP server as an Alexa+ MCP add-on.

1. Deploy the server (`infra/template.yaml`, see the main README) and copy the `McpEndpoint`
   output, for example `https://abc123.lambda-url.ap-south-1.on.aws/mcp`.
2. Put it in `addon.json` at `integrations[0].config.endpoints.default.uri`.
3. Install the Alexa AI CLI (see the Alexa+ MCP Toolkit quickstart on developer.amazon.com),
   then from this folder run `alexa-ai deploy` to deploy to the development stage.
4. In the Alexa+ web simulator (or on a device), enable the add-on and link the account.
   Raksha's consent page asks for the family passcode (`ApprovalPasscode`), then Alexa+
   receives an OAuth 2.1 token (authorization code + PKCE S256).
5. Try: "Ask Raksha which medicines I still need to take today."

What Alexa+ discovers from the server:

- `/.well-known/oauth-protected-resource` (RFC 9728) and `/.well-known/oauth-authorization-server`
- `/mcp`: Streamable HTTP, protocol 2025-11-25. An unauthenticated request gets a bare 401.
- 21 tools with zone-labelled descriptions and `readOnlyHint` / `destructiveHint` /
  `idempotentHint` / `openWorldHint` annotations, 4 resources and 2 prompts.

The icons in `assets/` are generated, so no third-party artwork is included.
