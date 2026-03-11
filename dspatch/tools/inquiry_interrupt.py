# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tools for handling forwarded inquiries.

When an inquiry is forwarded to an agent (from a subordinate or user),
the agent can respond via ``reply_to_inquiry``. If the agent was blocked
on a ``talk_to`` or ``inquire`` call, the reply includes instructions to
call ``continue_waiting_for_agent_response`` to resume.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..contexts import Context

# ── reply_to_inquiry tool definition ─────────────────────────────────────────

REPLY_NAME = "reply_to_inquiry"

REPLY_DESCRIPTION = (
    "Respond to the forwarded inquiry from a subordinate agent. "
    "Call this once you have a complete answer. The response will "
    "be delivered back to the asking agent and the interrupt turn "
    "will end."
)

REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "response": {
            "type": "string",
            "description": "Your response to the inquiry.",
        },
    },
    "required": ["response"],
}


def format_inquiry_injection(
    from_agent: str,
    content: str,
    suggestions: list[str] | None = None,
) -> str:
    """Build the structured user message injected into the supervisor's conversation."""
    msg = "[INQUIRY FROM SUBORDINATE AGENT]\n\n"
    msg += f'Agent "{from_agent}" is asking for your guidance:\n\n'
    msg += f'"{content}"\n'
    if suggestions:
        msg += "\nSuggestions from the agent:\n"
        for i, s in enumerate(suggestions, 1):
            msg += f"{i}. {s}\n"
    msg += "\nYou have the following tools available:\n"
    msg += "- reply_to_inquiry: Respond to the inquiry with your decision\n"
    msg += "- send_inquiry: Escalate parts you cannot answer to YOUR supervisor\n"
    msg += "\nIf you can answer fully, call reply_to_inquiry with your response.\n"
    msg += "If parts need escalation, call send_inquiry first for those parts,\n"
    msg += "then compile your full answer and call reply_to_inquiry.\n"
    return msg


async def execute_reply(
    ctx: Context,
    args: dict[str, Any],
    inquiry_id: str,
) -> dict[str, Any]:
    """Execute the reply_to_inquiry tool — sends response.

    Returns MCP content format with instructions to continue waiting
    if the agent was previously blocked.
    """
    response = args.get("response", "")

    # Emit a dedicated inquiry.responded activity.
    await ctx.activity(
        "inquiry.responded",
        data={
            "inquiry_id": inquiry_id,
            "response": response,
        },
    )

    ctx.log(f"Replying to inquiry {inquiry_id}: {response}")

    await ctx._runner._send_event({
        "type": "agent.event.inquiry.response",
        "inquiry_id": inquiry_id,
        "response_text": response,
    })

    ctx._pending_inquiry_id = None

    if ctx._runner._sm.pending_wait is not None:
        return {
            "content": [{
                "type": "text",
                "text": (
                    f"Inquiry response sent: {response}\n\n"
                    "You were waiting for an agent response before this interruption. "
                    "Call continue_waiting_for_agent_response to resume waiting."
                ),
            }],
        }

    return {
        "content": [
            {"type": "text", "text": f"Inquiry response sent: {response}"}
        ],
    }
