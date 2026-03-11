# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Built-in tool: continue_waiting_for_agent_response — resume a blocked talk_to/inquire call."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..contexts import Context

NAME = "continue_waiting_for_agent_response"

DESCRIPTION = (
    "Resume waiting for an agent's response after handling an inquiry "
    "interruption. Call this after you have replied to the incoming inquiry "
    "via reply_to_inquiry."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


async def execute(ctx: Context) -> dict[str, Any]:
    """Execute continue_waiting — re-enter the feed await loop.

    Returns MCP content format.
    """
    from ..dispatcher import ResponseItem, InquiryInterruptItem, TerminationItem

    pending = ctx._runner._sm.pending_wait
    if pending is None:
        return {
            "content": [{"type": "text", "text": "No pending wait to resume."}],
            "is_error": True,
        }

    # Emit a dedicated talk_to.waiting activity.
    await ctx.activity(
        "talk_to.waiting",
        data={
            "request_id": pending.request_id,
            "peer": pending.peer or "",
        },
    )

    # Re-enter the wait state so AgentInstanceRouter routes responses to the feed.
    if pending.wait_type == "talk_to":
        ctx._runner._sm.enter_waiting_for_agent(pending.request_id, pending.peer or "")
    else:
        ctx._runner._sm.enter_waiting_for_inquiry(pending.request_id)

    # _await_feed only reads from the feed; it does not mutate SM state.
    # SM stays in waiting_for_* until we call exit_waiting / receive_unexpected below.
    item = await ctx._await_feed(expected_request_id=pending.request_id)

    if isinstance(item, InquiryInterruptItem):
        return {
            "content": [{
                "type": "text",
                "text": ctx._runner._sm.receive_unexpected(item),
            }],
        }

    if isinstance(item, TerminationItem):
        reason = item.event.get("reason", "connection lost")
        ctx._runner._sm.exit_waiting(pending.request_id)
        return {
            "content": [{"type": "text", "text": f"Error: {reason}"}],
            "is_error": True,
        }

    # ResponseItem — success.
    response = item.event.get("response", "")
    peer = pending.peer or "agent"
    ctx._runner._sm.exit_waiting(pending.request_id)

    # Log the talk_to.response activity (mirrors context.py talk_to success path).
    await ctx.activity(
        "talk_to.response",
        data={
            "request_id": pending.request_id,
            "target_agent": peer,
            "response": response,
        },
    )

    return {
        "content": [{"type": "text", "text": f"Response from {peer}: {response}"}],
    }
