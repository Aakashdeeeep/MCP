"""A tiny MCP server where an assistant can check a balance freely, but paying a bill needs
the family's approval, and an OTP request locks money down.

    pip install -e packages/mcp-blast-radius
    python packages/mcp-blast-radius/examples/family_bank.py      # Streamable HTTP on :8100/mcp
"""
import re

from mcp.server.mcpserver import MCPServer

from mcp_blast_radius import BlastRadius, Zone

server = MCPServer("family-bank")


def scam_tripwire(text):
    patterns = {"otp_request": r"\botp\b", "gift_cards": r"gift\s*card", "digital_arrest": r"digital\s*arrest"}
    return [label for label, pattern in patterns.items() if re.search(pattern, text, re.IGNORECASE)]


def text_the_family(request):
    print(f"[to family] Approve {request['tool']}({request['arguments']})? id={request['id']}")


gate = BlastRadius(server, tripwire=scam_tripwire, on_approval_needed=text_the_family, spending_cap=5000)
BALANCE = {"rupees": 18250}


@gate.tool(zone=Zone.AUTO)
def check_balance() -> str:
    """How much money is in the account."""
    return f"Your balance is {BALANCE['rupees']} rupees."


@gate.tool(zone=Zone.APPROVE, moves_money=True, amount_arg="rupees")
def pay_bill(payee: str, rupees: float, note: str = "") -> str:
    """Pay a bill. A family member approves every payment."""
    BALANCE["rupees"] -= rupees
    return f"Paid {rupees:g} rupees to {payee}."


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(server.streamable_http_app(), port=8100)
