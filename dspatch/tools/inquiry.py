# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Built-in inquiry tool — ask the user a question with suggested options."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..contexts import Context

NAME = "send_inquiry"

DESCRIPTION = (
    "Send an inquiry to the user for decision-making. Use this tool "
    "when you need human approval or clarification on significant "
    "decisions. The tool will block until the user responds (up to "
    "72 hours). Suggest what the user might wanto to instruct you to do. "
    "The first suggestion is treated as your recommended approach."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "markdown": {
            "type": "string",
            "description": (
                "A comprehensive markdown document explaining the "
                "situation, what you are trying to do, what you are "
                "unsure about, and why you need input. Include all "
                "context needed to make a decision."
            ),
        },
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 4,
            "description": (
                "2-4 instructions that the user can choose from to "
                "tell you what to do next. Each suggestion is a "
                "directive addressed to you (the agent). The FIRST "
                "suggestion must be your best recommended action. "
                "All others must be genuinely valid alternatives — "
                "not filler or throwaway options. "
                "Example: 'Refactor the auth module into separate files "
                "for OAuth and JWT' — not 'I will refactor the module'."
            ),
        },
        "files": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "List of absolute file paths relevant to this "
                "inquiry. Their contents will be sent to the user "
                "for review."
            ),
            "default": [],
        },
    },
    "required": ["markdown", "suggestions"],
}


async def execute(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Execute the inquiry tool — calls ctx.inquire() and returns the response.

    Returns MCP content format:
        {"content": [{"type": "text", "text": "..."}]}
    On error:
        {"content": [{"type": "text", "text": "..."}], "is_error": True}
    """
    markdown: str = args["markdown"]
    suggestions: list[str] = args["suggestions"]
    files: list[str] = args.get("files", [])

    ctx.log(
        f"Sending inquiry (suggestions={len(suggestions)}, files={len(files)})"
    )

    try:
        response = await ctx.inquire(
            content_markdown=markdown,
            suggestions=suggestions,
            file_paths=files or None,
        )

        # Check for interrupt.
        if isinstance(response, str):
            return {
                "content": [{"type": "text", "text": response}],
            }

        # Build a meaningful response string. When the user selects a
        # suggestion (no custom text), response.text is None — map the
        # suggestion_index back to the original suggestion text.
        if response.text:
            response_text = response.text
        elif response.suggestion_index is not None:
            idx = response.suggestion_index
            if 0 <= idx < len(suggestions):
                response_text = suggestions[idx]
            else:
                response_text = f"(selected suggestion #{idx})"
        else:
            response_text = "(no response text)"

        ctx.log(f"User responded to inquiry: {response_text}")

        return {
            "content": [
                {"type": "text", "text": f"User response: {response_text}"}
            ],
        }

    except Exception as exc:
        error_name = type(exc).__name__
        ctx.log(f"Inquiry failed: {error_name}: {exc}", level="error")
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Failed to send inquiry: {exc}",
                }
            ],
            "is_error": True,
        }
