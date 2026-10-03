# Threat model

**Asset:** an elder's money, health records and safety. **Entry point:** an AI assistant
(Alexa+) that calls Raksha's MCP tools, and the scammer who may be talking to the elder, or
through the assistant. **Assumption:** the assistant's model can be wrong, manipulated or
fully compromised, and the elder may agree to anything they're asked.

| # | Threat | What stops it | Enforced by |
|---|---|---|---|
| 1 | The model calls a money tool on its own | Zone 2 + Cedar `money-needs-approval`: nothing that moves money runs without a family member's tap | `test_order_waits_for_family_then_runs_once`, red-team #7 |
| 2 | A scammer talks the elder into paying ("digital arrest" fine) | Tripwire on the elder's words *and* every argument → Zone 3 family alert; scam lock refuses the payment; no approval request is created | `test_scam_lock_refuses_payment_and_alerts_family`, red-team #2, #6 |
| 3 | The scammer calls back with a keyword-free request | **Scam watch:** after any alert, money stays paused across turns; only the family (passcode) can lift it; requests made earlier can't be approved meanwhile | `test_scam_callback_without_keywords_is_still_blocked`, `test_request_made_before_the_scam_cannot_be_approved_during_it`, red-team #3, #4 |
| 4 | Approval fatigue: many small requests until the family taps yes | At most `MAX_PENDING_MONEY` (2) waiting, claimed with DynamoDB conditional writes | `test_fatigue_limit_holds_under_concurrency`, red-team #8 |
| 5 | Above-limit spending with a genuine approval | Cedar `demo-spending-cap`, pre-checked so the family is never asked | `test_family_is_never_asked_to_approve_what_policy_forbids` |
| 6 | Prompt injection ("you are now authorised") | Text is data: the policy reads zones and flags from code, never from the model; payments still go to the family | `test_prompt_injection_is_just_text`, red-team #12 |
| 7 | Impersonation ("it's me, your grandson") | `verify_caller` never vouches for a voice; it gives the saved number to call back | `test_verify_caller_never_vouches_for_a_voice` |
| 8 | Unknown or malformed tool calls | Registry validation; unknown args rejected; schema validation | `test_bad_args_never_run`, red-team #13, #14 |
| 9 | The assistant is unsure what it heard | Confidence floor: below 0.75, even a Zone 1 action goes to the family | `test_unsure_assistant_means_family_decides`, red-team #15 |
| 10 | A delayed emergency | Zone 3 never waits, not even during a lockdown; the alert is sent before any other network call | `test_emergency_words_alert_even_from_a_harmless_tool` |
| 11 | Double execution of an approval | Conditional claim: pending → running, exactly once | `test_approval_page_approves_once` |
| 12 | Someone else's Alexa links to the elder's data | OAuth 2.1 + PKCE S256, consent needs the family passcode, single-use codes, rotating refresh tokens | `test_alexa_account_linking_oauth_flow` |
| 13 | Unauthenticated or cross-site calls to `/mcp` | Bearer required (bare 401), browser Origin check (403), DNS-rebinding guard locally | `test_guard_auth_and_origin` |
| 14 | Poisoned approval links (forged Host header) | Base URL learned only from a Lambda Function URL Host, never X-Forwarded-Host | `test_base_url_is_never_learned_from_a_forged_header` |
| 15 | XSS through the elder's words on family pages | Server-side `html.escape`, client-side escaping | `test_approval_page_approves_once` |
| 16 | Leaking ID numbers | Raksha OS masks account and Aadhaar numbers (`redact.py`); OAuth secrets are stored only as SHA-256 hashes, with TTL | (Raksha OS tests), `oauth.py` |

## Out of scope / residual risk

- A family member who approves a scam payment *after* lifting the pause. Raksha warns them
  in the approval message, but the decision is theirs.
- A compromised family phone or a leaked passcode.
- Scams with no keyword shape and no money tool, for example coaching the elder to go to the
  bank in person. `check_scam` (Claude on Bedrock) catches some of these; the tripwire is only
  a backstop.
- Mocked integrations (pharmacy, payments in Razorpay test mode) don't move real money in
  this demo.
