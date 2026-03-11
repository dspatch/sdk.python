# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Claude-specialized context.

Provides a ``ClaudeAgentContext`` that adds Claude Agent SDK helpers directly
as methods: MCP tool creation, response-stream bridging, and system-prompt
augmentation with MCP naming conventions.
"""

from __future__ import annotations

import logging
from typing import Any

from .context import Context

logger = logging.getLogger("dspatch.claude_context")


class ClaudeAgentContext(Context):
    """Context specialized for Claude Agent SDK agents.

    Provides:

    - ``setup(system_prompt, options)`` — configure the SDK client
    - ``async with ctx:`` — create/destroy the Claude SDK client
    - ``run(prompt)`` — send a prompt and bridge the response stream
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sdk_client_ctx: Any = None

    @property
    def _tool_name_prefix(self) -> str:
        return "mcp__dspatch__"

    # ── Setup / run / context manager ─────────────────────────────────────

    async def __aenter__(self):
        await super().__aenter__()

        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        augmented = self._get_augmented_system_prompt()
        mcp_server, tool_names = self._get_tools()

        if self._user_options is not None:
            options = self._user_options
        else:
            options = ClaudeAgentOptions()

        options.system_prompt = augmented
        if not options.mcp_servers:
            options.mcp_servers = {}
        options.mcp_servers["dspatch"] = mcp_server
        if not options.allowed_tools:
            options.allowed_tools = []
        options.allowed_tools.extend(tool_names)
        if not options.cwd:
            options.cwd = self.workspace_dir
        if not options.permission_mode:
            options.permission_mode = "bypassPermissions"

        self._sdk_client_ctx = ClaudeSDKClient(options=options)
        self.client = await self._sdk_client_ctx.__aenter__()
        self.log("Claude Agent SDK client started")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._sdk_client_ctx is not None:
            self.log("Shutting down Claude Agent SDK client...")
            await self._sdk_client_ctx.__aexit__(exc_type, exc_val, exc_tb)
            self._sdk_client_ctx = None
            self.client = None
        return False

    async def run(self, prompt: str) -> str:
        """Send *prompt* to the Claude SDK client and bridge the response.

        Must be called inside ``async with ctx:``.
        """
        if self.client is None:
            raise RuntimeError("No active client. Use 'async with ctx:' first.")
        self.log(f"Processing prompt: {prompt}")

        # Debug: log conversation state before query.
        conv = getattr(self.client, '_conversation', None)
        history = getattr(self.client, '_messages', None) or getattr(self.client, 'messages', None)
        logger.info(
            "ClaudeAgentContext.run() — client id=%s, "
            "has _conversation=%s, has messages=%s, "
            "message count=%s",
            id(self.client),
            conv is not None,
            history is not None,
            len(history) if history else "N/A",
        )
        if history:
            for i, msg in enumerate(history):
                role = msg.get("role", "?") if isinstance(msg, dict) else getattr(msg, "role", "?")
                content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                preview = str(content)[:150]
                logger.info("  history[%d] role=%s: %s", i, role, preview)

        # Also dump all attrs of the client for discovery.
        logger.info(
            "Client attrs: %s",
            [a for a in dir(self.client) if not a.startswith("__")],
        )

        await self.client.query(prompt)
        return await self._process_response_stream()

    # ── MCP tool creation ─────────────────────────────────────────────────

    def _get_tools(
        self,
        *,
        server_name: str = "dspatch",
        server_version: str = "1.0.0",
    ) -> tuple[Any, list[str]]:
        """Create an MCP server with all registered dspatch tools.

        Wraps each :class:`ToolSpec` from ``_dspatch_tool_specs()`` into
        a Claude MCP tool closure that delegates to ``spec.handler``.

        Returns ``(mcp_server, tool_names)``.
        """
        from claude_agent_sdk import create_sdk_mcp_server, tool

        tools = []
        tool_names: list[str] = []

        for spec in self._dspatch_tool_specs():
            handler = spec.handler

            @tool(spec.name, spec.description, spec.schema)
            async def tool_fn(args: dict[str, Any], _h: Any = handler) -> dict[str, Any]:
                return await _h(args)

            tools.append(tool_fn)
            tool_names.append(f"mcp__{server_name}__{spec.name}")

        logger.info(
            "create_dspatch_tools: registering %d tools "
            "(available_agents=%s): %s",
            len(tool_names), self.available_agents, tool_names,
        )

        mcp_server = create_sdk_mcp_server(
            name=server_name,
            version=server_version,
            tools=tools,
        )

        return mcp_server, tool_names

    # ── Response stream bridging ──────────────────────────────────────────

    async def _process_response_stream(self) -> str:
        """Bridge a Claude Agent SDK response stream to the dspatch app.

        Iterates ``self.client.receive_response()`` and:

        - **AssistantMessage** — content blocks forwarded as streaming
          messages via ``ctx.message(is_delta=True)``.
        - **ToolUseBlock** — logged as an activity.
        - **ThinkingBlock** — logged as an activity.
        - **ResultMessage** — token usage recorded via ``ctx.usage()``.

        Returns the final result text.
        """
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            ThinkingBlock,
        )

        model = "claude-sonnet-4-5-20250929"
        if self._user_options is not None:
            model = getattr(self._user_options, "model", model) or model

        result_text = ""
        message_id: str | None = None

        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_text = block.text
                        message_id = await self.message(
                            block.text,
                            is_delta=True,
                            id=message_id,
                        )

                    elif isinstance(block, ToolUseBlock):
                        # Reset message_id before tool use so the next
                        # text segment gets a fresh message_id.
                        message_id = None

                        file_path = _extract_file_path(block.input)
                        summary = (
                            f"{block.name}: {file_path}"
                            if file_path
                            else block.name
                        )

                        metadata: dict = {
                            "tool": block.name,
                            "input": str(block.input),
                            "file_path": file_path,
                            "description": summary,
                        }

                        await self.activity(
                            "tool_call",
                            data=metadata,
                        )

                    elif isinstance(block, ThinkingBlock):
                        # Reset message_id so thinking doesn't merge
                        # with prior text.
                        message_id = None

                        await self.activity(
                            "thinking",
                            content=block.thinking,
                        )

            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0
                usage = message.usage or {}
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

                if message.result:
                    result_text = message.result

                await self.usage(
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                )

        # Send final message if nothing was streamed yet.
        if message_id is None:
            final_text = result_text or "Agent completed without producing output."
            await self.message(final_text)

        return result_text


def _extract_file_path(tool_input: Any) -> str | None:
    """Extract a file path from a Claude tool call's input dict."""
    if isinstance(tool_input, dict):
        return (
            tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("command", "")
            or None
        )
    return None
