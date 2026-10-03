"""The family's pages (approval + live feed) and the bearer-token guard for /mcp.

Plain server-rendered HTML with one shared stylesheet, no build step. All dynamic text is
escaped: summaries and utterances come from a voice assistant, so they're untrusted.
"""
import hmac
import html
import json

from raksha_mcp import config

STYLE = """
:root{--bg:#f6f3ee;--card:#fff;--ink:#1f1c18;--muted:#6b645b;--line:#e5ded3;--brand:#c2571a;
--ok:#1f7a4d;--warn:#a15c00;--bad:#b42318;--z0:#6b645b;--z1:#1f7a4d;--z2:#a15c00;--z3:#b42318;
--chip:#f1ece4;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#161412;--card:#1f1c19;--ink:#f3eee7;--muted:#a69d91;
--line:#34302b;--brand:#f08a4b;--ok:#4fbf86;--warn:#f0a840;--bad:#f2685c;--z0:#a69d91;--z1:#4fbf86;
--z2:#f0a840;--z3:#f2685c;--chip:#2a2622}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);line-height:1.45}
main{max-width:46rem;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.4rem;margin:0 0 4px}h2{font-size:1.1rem;margin:0 0 8px}
.sub{color:var(--muted);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:0 0 12px}
.row{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.chip{display:inline-block;font-size:.75rem;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--chip);color:var(--muted)}
.z0{color:var(--z0)}.z1{color:var(--z1)}.z2{color:var(--z2)}.z3{color:var(--z3)}
.time{color:var(--muted);font-size:.8rem;margin-left:auto}
.speech{margin:6px 0 0}.detail{color:var(--muted);font-size:.85rem;margin:6px 0 0;white-space:pre-wrap;word-break:break-word}
.urgent{border-color:var(--bad);border-width:2px}
.btn{font:inherit;font-weight:600;font-size:1.05rem;padding:.65rem 1.3rem;border-radius:10px;border:0;cursor:pointer}
.approve{background:var(--ok);color:#fff}.reject{background:var(--chip);color:var(--ink);border:1px solid var(--line)}
input{font:inherit;padding:.5rem .7rem;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
.err{color:var(--bad);font-weight:600}.brand{color:var(--brand)}
table{border-collapse:collapse;width:100%}td{padding:4px 0;vertical-align:top}td:first-child{color:var(--muted);width:9rem}
"""


def shell(title, body):
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body><main>{body}</main></body></html>"
    )


def approval_page(approval, error=None):
    if approval is None:
        return shell("Raksha", "<h1>Request not found</h1><p class=sub>The link may be wrong or too old.</p>")
    e = html.escape
    args_rows = "".join(f"<tr><td>{e(str(k))}</td><td>{e(str(v))}</td></tr>" for k, v in approval["args"].items())
    status = approval["status"]
    body = [
        f"<h1><span class=brand>Raksha</span> · approval</h1>",
        f"<p class=sub>{e(config.ELDER_NAME)} asked Alexa for something that needs your okay.</p>",
        "<div class=card>",
        f"<h2>{e(approval['summary_en'][:1].upper() + approval['summary_en'][1:])}</h2>",
        f"<table><tr><td>Exactly what runs</td><td><code>{e(approval['agent'])}.{e(approval['tool'])}</code></td></tr>{args_rows}",
        f"<tr><td>What they said</td><td>“{e(approval.get('utterance') or '-')}”</td></tr></table>",
    ]
    if approval.get("forced_by_confidence"):
        body.append("<p class=detail>Alexa wasn't sure it understood, so please double-check before approving.</p>")
    body.append("</div>")
    if error:
        body.append(f"<p class=err>{e(error)}</p>")
    if status == "pending":
        passcode = (
            "<p><label>Family passcode <input name=passcode type=password required autocomplete=off></label></p>"
            if config.APPROVAL_PASSCODE
            else ""
        )
        body.append(
            f"<form method=post>{passcode}<div class=row>"
            "<button class='btn approve' name=decision value=approve>Approve</button>"
            "<button class='btn reject' name=decision value=reject>Reject</button></div></form>"
            f"<p class=detail>Expires {e(approval['expires_at'][:16].replace('T', ' '))} UTC if nobody answers.</p>"
        )
    elif status == "done":
        outcome = approval.get("outcome") or {}
        body.append(
            "<div class=card><span class='chip z1'>Approved and done</span>"
            f"<p class=speech>{e(outcome.get('speech', ''))}</p>"
            + ("<p class=detail>Demo: this agent returns a mocked result.</p>" if outcome.get("mocked") else "")
            + "</div>"
        )
    else:
        body.append(f"<div class=card><span class=chip>{e(status.capitalize())}</span></div>")
    return shell("Raksha approval", "".join(body))


def family_page():
    key_note = "?key=" if config.APPROVAL_PASSCODE else ""
    return shell(
        "Raksha family feed",
        f"""
<h1><span class=brand>Raksha</span> · family feed</h1>
<p class=sub>Every request Alexa makes for {html.escape(config.ELDER_NAME)}, and what Raksha's policy decided. Updates live.</p>
<div id=feed><p class=sub>Waiting for the first request…</p></div>
<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
const ZONE = {{0:'Zone 0 · talk',1:'Zone 1 · autonomous',2:'Zone 2 · family approves',3:'Zone 3 · panic override'}};
const KIND = {{decision:'Decision',alert:'URGENT alert',family_message:'Message to family',approval_request:'Approval needed',
  approval_done:'Approved · done',approval_rejected:'Rejected',approval_expired:'Expired',approval_failed:'Approved · failed'}};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function card(e) {{
  const z = e.effective_zone ?? e.zone;
  const urgent = e.kind === 'alert';
  const reasons = e.policy && e.policy.reasons ? e.policy.reasons.join(', ') : '';
  const engine = e.policy && e.policy.engine ? e.policy.engine : 'cedar';
  return `<div class="card ${{urgent ? 'urgent' : ''}}"><div class=row>
    <span class="chip ${{urgent ? 'z3' : ''}}">${{esc(KIND[e.kind] || e.kind)}}</span>
    ${{z != null ? `<span class="chip z${{z}}">${{esc(ZONE[z])}}</span>` : ''}}
    ${{e.mocked ? '<span class=chip>mocked agent</span>' : ''}}
    <span class=time>${{esc(new Date(e.at).toLocaleTimeString())}}</span></div>
    <p class=speech><strong>${{esc(e.title)}}</strong></p>
    ${{e.speech ? `<p class=detail>Alexa said: “${{esc(e.speech)}}”</p>` : ''}}
    ${{e.tripwire && e.tripwire.length ? `<p class=detail>Tripwire: ${{esc(e.tripwire.join(', '))}}</p>` : ''}}
    ${{reasons ? `<p class=detail>Policy (${{esc(engine)}}): ${{esc(reasons)}}</p>` : ''}}
    ${{e.body ? `<p class=detail>${{esc(e.body)}}</p>` : ''}}
    ${{e.link ? `<p><a href="${{esc(e.link)}}">Open approval →</a></p>` : ''}}
  </div>`;
}}
async function refresh() {{
  try {{
    const r = await fetch('/api/feed' + (KEY ? '?key=' + encodeURIComponent(KEY) : ''));
    if (!r.ok) return;
    const items = await r.json();
    if (items.length) document.getElementById('feed').innerHTML = items.map(card).join('');
  }} catch (err) {{}}
}}
refresh(); setInterval(refresh, 2000);
</script>{key_note and ''}""",
    )


class BearerAuth:
    """ASGI middleware: requests under `protected_prefix` need `Authorization: Bearer <token>`.

    Constant-time comparison. With no token configured the guard is off (local demo only;
    the SAM template requires one)."""

    def __init__(self, app, token, protected_prefix="/mcp"):
        self.app, self.token, self.prefix = app, token, protected_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token and scope["path"].startswith(self.prefix):
            headers = dict(scope.get("headers") or [])
            supplied = headers.get(b"authorization", b"").decode()
            if not hmac.compare_digest(supplied, f"Bearer {self.token}"):
                body = json.dumps({"error": "unauthorized"}).encode()
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


class LearnBaseUrl:
    """ASGI middleware: on Lambda the Function URL isn't known until the stack exists, so the
    approval links use the host the first request arrived on. PUBLIC_BASE_URL overrides it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not config.PUBLIC_BASE_URL_FIXED:
            headers = dict(scope.get("headers") or [])
            host = headers.get(b"x-forwarded-host", headers.get(b"host", b"")).decode()
            if host and not host.startswith(("127.0.0.1", "localhost")):
                proto = headers.get(b"x-forwarded-proto", b"https").decode()
                config.PUBLIC_BASE_URL = f"{proto}://{host}"
                config.PUBLIC_BASE_URL_FIXED = True
        await self.app(scope, receive, send)
