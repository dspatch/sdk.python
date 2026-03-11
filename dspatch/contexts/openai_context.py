# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""OpenAI Agents SDK context.

Provides an ``OpenAiAgentContext`` that integrates with the OpenAI Agents SDK
(``openai-agents`` package). Uses ``Runner.run_streamed()`` for real-time
streaming of text deltas, tool calls, and reasoning events.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .context import Context

logger = logging.getLogger("dspatch.openai_context")


class OpenAiAgentContext(Context):
    """Context specialized for OpenAI Agents SDK.

    Provides:

    - ``setup(system_prompt, options)`` — configure model and agent
    - ``async with ctx:`` — build Agent with dspatch tools
    - ``run(prompt)`` — stream events from Runner.run_streamed()
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent: Any = None
        self._last_response_id: str | None = None

    # ── Setup / run / context manager ─────────────────────────────────────

    async def __aenter__(self):
        await super().__aenter__()

        from agents import Agent

        augmented = self._get_augmented_system_prompt()
        tools = self._get_tools()

        model = "gpt-4o"
        if self._user_options is not None:
            model = getattr(self._user_options, "model", model) or model

        self._agent = Agent(
            name="dspatch-agent",
            instructions=augmented,
            tools=tools,
            model=model,
        )
        self.log("OpenAI Agents SDK context entered")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._agent = None
        self._last_response_id = None
        self.client = None
        return False

    async def run(self, prompt: str) -> str:
        """Send *prompt* to the OpenAI Agents SDK and bridge the event stream.

        Must be called inside ``async with ctx:``.
        """
        if self._agent is None:
            raise RuntimeError(
                "No active agent. Use 'async with ctx:' first."
            )
        self.log(f"Processing prompt: {prompt}")

        from agents import Runner
        from agents.run_config import RunConfig
        from openai.types.responses import ResponseTextDeltaEvent

        # Build RunConfig — optionally wrap a custom OpenAI client.
        run_config: RunConfig | None = None
        if self.client is not None:
            from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

            model_name = "gpt-4o"
            if self._user_options is not None:
                model_name = getattr(self._user_options, "model", model_name) or model_name

            custom_model = OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=self.client,
            )
            run_config = RunConfig(model=custom_model)

        result = Runner.run_streamed(
            self._agent,
            input=prompt,
            previous_response_id=self._last_response_id,
            run_config=run_config,
        )

        result_text = ""
        message_id: str | None = None

        async for event in result.stream_events():
            if event.type == "raw_response_event":
                if isinstance(event.data, ResponseTextDeltaEvent):
                    delta = event.data.delta
                    if delta:
                        result_text += delta
                        message_id = await self.message(
                            delta,
                            is_delta=True,
                            id=message_id,
                        )

            elif event.type == "run_item_stream_event":
                if event.name == "tool_called":
                    item = event.item
                    raw_item = getattr(item, "raw_item", None)
                    actual_name = ""
                    arguments = ""
                    if raw_item is not None:
                        actual_name = getattr(raw_item, "name", "") or ""
                        arguments = getattr(raw_item, "arguments", "") or ""

                    # Reset message_id before tool call so the next
                    # text segment gets a fresh one.
                    message_id = None

                    metadata: dict = {
                        "tool": actual_name,
                        "input": arguments,
                        "description": actual_name,
                    }

                    await self.activity("tool_call", data=metadata)

                elif event.name == "reasoning_item_created":
                    item = event.item
                    raw_item = getattr(item, "raw_item", None)
                    text = ""
                    if raw_item is not None:
                        summary = getattr(raw_item, "summary", None)
                        if summary:
                            text = " ".join(
                                getattr(s, "text", str(s)) for s in summary
                            )
                    if text:
                        await self.activity("thinking", content=text)

            elif event.type == "agent_updated_stream_event":
                logger.info("Agent updated: %s", event.new_agent.name)

        # Record usage from the result.
        if hasattr(result, "raw_responses") and result.raw_responses:
            for resp in result.raw_responses:
                usage = getattr(resp, "usage", None)
                if usage:
                    model_name = "gpt-4o"
                    if self._user_options is not None:
                        model_name = getattr(self._user_options, "model", model_name) or model_name
                    await self.usage(
                        model=model_name,
                        input_tokens=getattr(usage, "input_tokens", 0) or 0,
                        output_tokens=getattr(usage, "output_tokens", 0) or 0,
                        cost_usd=0.0,
                    )

        # Store response ID for multi-turn continuity.
        self._last_response_id = result.last_response_id

        # Send final message if nothing was streamed yet.
        if message_id is None:
            final_text = result_text or "Agent completed without producing output."
            await self.message(final_text)

        return result_text

    # ── Tool definitions ──────────────────────────────────────────────────

    def _get_tools(self) -> list:
        """Return OpenAI Agents SDK FunctionTool objects for all dspatch tools.

        Wraps each :class:`ToolSpec` from ``_dspatch_tool_specs()`` into
        a ``FunctionTool`` with an ``on_invoke_tool`` callback.
        """
        from agents import FunctionTool

        tools = []

        for spec in self._dspatch_tool_specs():
            handler = spec.handler

            async def _on_invoke(ctx, args_json: str, _h=handler) -> str:
                args = json.loads(args_json) if args_json else {}
                result = await _h(args)
                return json.dumps(result)

            ft = FunctionTool(
                name=spec.name,
                description=spec.description,
                params_json_schema=spec.schema,
                on_invoke_tool=_on_invoke,
                strict_json_schema=False,
            )
            tools.append(ft)

        tool_names = [t.name for t in tools]
        logger.info(
            "get_tools: registering %d tools "
            "(available_agents=%s): %s",
            len(tool_names), self.available_agents, tool_names,
        )
        return tools
