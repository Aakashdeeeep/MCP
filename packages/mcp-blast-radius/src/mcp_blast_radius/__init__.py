"""mcp-blast-radius: put a policy between an AI assistant and real-world actions.

    from mcp.server.mcpserver import MCPServer
    from mcp_blast_radius import BlastRadius, Zone

    server = MCPServer("bank")
    gate = BlastRadius(server, on_approval_needed=text_my_daughter)

    @gate.tool(zone=Zone.AUTO)
    def check_balance() -> str: ...

    @gate.tool(zone=Zone.APPROVE, moves_money=True, amount_arg="rupees")
    def pay_bill(payee: str, rupees: float) -> str: ...

The model can *ask* for anything. What runs is decided by:
  - the tool's zone, fixed in code (never by the model);
  - a Cedar policy (deny by default; money needs approval; a spending cap; a lockdown);
  - a tripwire over the arguments, which can lock money down after a suspected attack;
  - a cap on how many money requests may wait for a human at once (approval fatigue).

Zone 2 calls return `pending_approval` with a request id. A human's approve(id) runs the
stored call exactly once, and the policy is checked again at that moment.
"""
import functools
import inspect
import secrets
import time
from enum import IntEnum

from mcp_types import CallToolResult, TextContent, ToolAnnotations

from mcp_blast_radius.policy import DEFAULT_SPENDING_CAP, Policy, default_policy
from mcp_blast_radius.store import MemoryStore, Store

__all__ = ["BlastRadius", "Zone", "MemoryStore", "Store", "Policy", "default_policy", "ApprovalError"]
__version__ = "0.1.0"


class Zone(IntEnum):
    TALK = 0  # conversation only
    AUTO = 1  # read-only or internal: runs on its own
    APPROVE = 2  # money, orders, outside writes: a human approves each call
    PANIC = 3  # emergencies: runs immediately, never waits


class ApprovalError(Exception):
    pass


class BlastRadius:
    def __init__(
        self,
        server,
        *,
        policy: str | None = None,
        spending_cap: float = DEFAULT_SPENDING_CAP,
        store: Store | None = None,
        tripwire=None,
        on_approval_needed=None,
        on_alert=None,
        lockdown_minutes: int = 120,
        max_pending_money: int = 2,
        approval_ttl_seconds: int = 3600,
    ):
        """
        tripwire(text) -> list[str]: labels of attack signals found in a call's arguments.
            Any hit raises an alert and locks money down for `lockdown_minutes`.
        on_approval_needed(request): tell a human (SMS, email, push). request has id,
            tool, arguments and expires_at.
        on_alert(tool, signals): called when the tripwire fires.
        """
        self.server = server
        self.policy = Policy(policy or default_policy(spending_cap))
        self.store = store or MemoryStore()
        self.tripwire = tripwire
        self.on_approval_needed = on_approval_needed
        self.on_alert = on_alert
        self.lockdown_minutes = lockdown_minutes
        self.max_pending_money = max_pending_money
        self.approval_ttl_seconds = approval_ttl_seconds
        self._tools = {}

    # --- registration ------------------------------------------------------------------

    def tool(self, *, zone: Zone, moves_money: bool = False, amount_arg: str | None = None, **tool_kwargs):
        """Register `fn` as an MCP tool on the server, behind the gate."""

        def decorator(fn):
            name = tool_kwargs.pop("name", None) or fn.__name__
            spec = {"fn": fn, "zone": Zone(zone), "moves_money": moves_money, "amount_arg": amount_arg}
            self._tools[name] = spec

            @functools.wraps(fn)
            async def gated(**arguments):
                return self._as_result(await self.call(name, arguments))

            gated.__signature__ = inspect.signature(fn).replace(return_annotation=CallToolResult)
            gated.__annotations__ = {**getattr(fn, "__annotations__", {}), "return": CallToolResult}
            annotations = tool_kwargs.pop("annotations", None) or ToolAnnotations(
                read_only_hint=zone <= Zone.AUTO and not moves_money,
                destructive_hint=zone == Zone.APPROVE,
            )
            description = (tool_kwargs.pop("description", None) or inspect.getdoc(fn) or name).strip()
            self.server.add_tool(
                gated,
                name=name,
                description=f"{description}\n[blast radius: zone {int(zone)}{', moves money' if moves_money else ''}]",
                annotations=annotations,
                meta={"blast_radius/zone": int(zone), "blast_radius/moves_money": moves_money},
                structured_output=False,
                **tool_kwargs,
            )
            return fn

        return decorator

    # --- the decision ------------------------------------------------------------------

    async def call(self, name, arguments):
        """Decide and (maybe) run one call. Returns an outcome dict."""
        spec = self._tools[name]
        amount = self._amount(spec, arguments)

        signals = self.tripwire(" ".join(_strings(arguments))) if self.tripwire else []
        if signals:
            self.lockdown(reason=f"{name}: {', '.join(signals)}")
            if self.on_alert:
                await _maybe_await(self.on_alert(name, signals))
            if spec["moves_money"] or spec["zone"] == Zone.APPROVE:
                return {"status": "blocked_attack", "tool": name, "signals": signals}

        lockdown = bool(self.store.lockdown())
        allowed, reasons = self._decide(name, spec, approved=False, amount=amount, lockdown=lockdown)
        if allowed:
            return {"status": "done", "tool": name, "result": await _maybe_await(spec["fn"](**arguments)), "policy": reasons}
        if spec["zone"] != Zone.APPROVE:
            return {"status": "blocked_policy", "tool": name, "policy": reasons}

        # Zone 2: never ask a human to approve what the policy would refuse anyway
        would_allow, reasons = self._decide(name, spec, approved=True, amount=amount, lockdown=lockdown)
        if not would_allow:
            return {"status": "blocked_policy", "tool": name, "policy": reasons}
        if spec["moves_money"] and len([r for r in self.store.pending() if r["moves_money"]]) >= self.max_pending_money:
            return {"status": "blocked_too_many_pending", "tool": name}

        request = {
            "id": secrets.token_urlsafe(9),
            "tool": name,
            "arguments": arguments,
            "moves_money": spec["moves_money"],
            "status": "pending",
            "created_at": time.time(),
            "expires_at": time.time() + self.approval_ttl_seconds,
        }
        self.store.put(request)
        if self.on_approval_needed:
            await _maybe_await(self.on_approval_needed(dict(request)))
        return {"status": "pending_approval", "tool": name, "request_id": request["id"], "policy": reasons}

    async def approve(self, request_id):
        """A human said yes: run the stored call once, with the policy checked again now."""
        request = self.store.get(request_id)
        if request is None:
            raise ApprovalError("unknown request")
        if request["status"] == "pending" and request["expires_at"] <= time.time():
            self.store.claim(request_id, "pending", "expired")
            raise ApprovalError("request expired")
        spec = self._tools[request["tool"]]
        allowed, reasons = self._decide(
            request["tool"], spec, approved=True, amount=self._amount(spec, request["arguments"]),
            lockdown=bool(self.store.lockdown()),
        )
        if not allowed:
            raise ApprovalError(f"policy refuses it now: {', '.join(reasons) or 'no permit matched'}")
        if not self.store.claim(request_id, "pending", "approved"):
            raise ApprovalError("already answered")
        result = await _maybe_await(spec["fn"](**request["arguments"]))
        return {"status": "done", "tool": request["tool"], "result": result, "policy": reasons}

    def reject(self, request_id):
        if not self.store.claim(request_id, "pending", "rejected"):
            raise ApprovalError("already answered or unknown")

    def lockdown(self, minutes=None, reason=""):
        self.store.set_lockdown(time.time() + 60 * (minutes or self.lockdown_minutes), reason)

    def lift_lockdown(self):
        self.store.set_lockdown(None)

    # --- helpers -----------------------------------------------------------------------

    def _decide(self, name, spec, *, approved, amount, lockdown):
        return self.policy.decide(
            name, zone=spec["zone"], moves_money=spec["moves_money"], approved=approved, amount=amount, lockdown=lockdown
        )

    @staticmethod
    def _amount(spec, arguments):
        value = arguments.get(spec["amount_arg"]) if spec["amount_arg"] else 0
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        return int(-(-value // 1))  # ceil, so 5000.01 counts as 5001 against the cap

    @staticmethod
    def _as_result(outcome):
        text = {
            "done": str(outcome.get("result", "")),
            "pending_approval": "Sent to a human for approval. Nothing has happened yet.",
            "blocked_policy": "Not allowed by policy.",
            "blocked_attack": "Refused: this looks like a scam or attack. A human has been alerted.",
            "blocked_too_many_pending": "Refused: requests are already waiting for approval.",
        }[outcome["status"]]
        structured = {k: v for k, v in outcome.items() if k != "result"}
        if outcome["status"] == "done":
            structured["result"] = outcome["result"] if isinstance(outcome["result"], (str, int, float, bool, dict, list)) else str(outcome["result"])
        return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=structured)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value
