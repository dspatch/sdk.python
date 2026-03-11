# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Per-peer talk_to_XXX tools — auto-generated from the peers config."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..contexts import Context


def tool_definitions(peers: list[str]) -> list[dict[str, Any]]:
    """Return tool definitions for all peers.

    Each peer gets a talk_to_<name> tool with `text` and `continue_previous_conversation` params.
    """
    return [_make_definition(peer) for peer in peers]


def tool_names(peers: list[str], *, server_name: str = "dspatch") -> list[str]:
    """Return fully-qualified MCP tool names for all peer tools."""
    return [f"mcp__{server_name}__talk_to_{peer}" for peer in peers]


def _make_definition(peer: str) -> dict[str, Any]:
    return {
        "name": f"talk_to_{peer}",
        "description": (
            f"Talk to {peer}. Sends a message and waits for their response. "
            f"Use this to coordinate work, delegate tasks, or request "
            f"information from {peer}."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": f"The message to send to {peer}.",
                },
                "continue_previous_conversation": {
                    "type": "boolean",
                    "description": (
                        "Set to true to keep the agent's full conversation "
                        "history intact — the agent will remember everything "
                        "from previous exchanges and can build on prior context. "
                        "Set to false to wipe the agent's memory and start a "
                        "completely fresh conversation — the agent will have no "
                        "knowledge of any previous interactions. "
                    )
                },
            },
            "required": ["text", "continue_previous_conversation"],
        },
    }


async def execute(
    ctx: Context,
    peer: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Execute a talk_to_<peer> tool call.

    Returns MCP content format.
    """
    text = args.get("text", "")
    continue_conv = args.get("continue_previous_conversation", False)

    ctx.log(f"Talking to {peer}: {text}")

    try:
        response = await ctx.talk_to(
            peer,
            text,
            continue_conversation=continue_conv,
        )
        # Check if this is an interrupt message.
        if isinstance(response, str) and response.startswith("INTERRUPTED:"):
            return {
                "content": [{"type": "text", "text": response}],
            }
        return {
            "content": [{"type": "text", "text": response}],
        }
    except Exception as exc:
        ctx.log(f"talk_to_{peer} failed: {exc}", level="error")
        return {
            "content": [{"type": "text", "text": f"Failed: {exc}"}],
            "is_error": True,
        }
