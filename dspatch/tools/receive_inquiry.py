# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Built-in tool: receive_incoming_inquiry — read the inquiry that interrupted a blocking call."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..contexts import Context

NAME = "receive_incoming_inquiry"

DESCRIPTION = (
    "Receive an incoming inquiry that interrupted your current operation. "
    "Call this immediately after being notified of an interruption. "
    "Returns the inquiry content so you can respond with reply_to_inquiry."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


async def execute(ctx: Context) -> dict[str, Any]:
    """Execute receive_incoming_inquiry — read buffered interrupt.

    Returns MCP content format.
    """
    interrupt = ctx._runner._sm.current_interrupt
    if interrupt is None:
        return {
            "content": [{"type": "text", "text": "No pending inquiry to receive."}],
            "is_error": True,
        }

    event = interrupt.event

    from_agent = event.get("from_agent", "unknown")
    content = event.get("content_markdown", "")
    suggestions = event.get("suggestions", [])
    inquiry_id = event.get("inquiry_id", "")

    # Store the inquiry_id so reply_to_inquiry knows which inquiry to respond to.
    ctx._pending_inquiry_id = inquiry_id

    # Emit a dedicated inquiry.receive activity.
    await ctx.activity(
        "inquiry.receive",
        data={
            "inquiry_id": inquiry_id,
            "from_agent": from_agent,
            "content_markdown": content,
        },
    )

    msg = f'Incoming inquiry from "{from_agent}":\n\n'
    msg += f"{content}\n"
    if suggestions:
        msg += "\nSuggestions:\n"
        for i, s in enumerate(suggestions, 1):
            text = s.get("text", str(s)) if isinstance(s, dict) else str(s)
            msg += f"{i}. {text}\n"
    msg += "\nRespond using the reply_to_inquiry tool with your answer.\n"
    if ctx._runner._sm.pending_wait is not None:
        msg += "After replying, call continue_waiting_for_agent_response to resume waiting.\n"

    return {
        "content": [{"type": "text", "text": msg}],
    }
