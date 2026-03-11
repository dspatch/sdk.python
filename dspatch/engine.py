# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""DspatchEngine — top-level API for agent developers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from .contexts import Context


class DspatchEngine:
    """Entry point for building a dspatch agent.

    Usage::

        from dspatch import DspatchEngine, ClaudeAgentContext

        dspatch = DspatchEngine()

        @dspatch.agent(ClaudeAgentContext)
        async def handle(prompt: str, ctx: ClaudeAgentContext):
            ctx.setup(system_prompt="You are helpful.")
            async with ctx:
                while True:
                    await ctx.run(prompt)
                    prompt = yield
                    if prompt is None:
                        break

        dspatch.run()
    """

    def __init__(self) -> None:
        self._agent_fn: Callable | None = None
        self._context_class: type[Context] = Context
        self._resume_fn: Callable | None = None

    def agent(self, context_class: type[Context]) -> Callable[[Callable], Callable]:
        """Decorator — register the agent handler function.

        Args:
            context_class: The context type to inject into the handler
                (e.g. ``ClaudeAgentContext``, ``OpenAiAgentContext``).

        Example::

            @dspatch.agent(ClaudeAgentContext)
            async def my_agent(prompt: str, ctx: ClaudeAgentContext):
                ...
        """
        self._context_class = context_class

        def decorator(fn: Callable) -> Callable:
            self._agent_fn = fn
            return fn

        return decorator

    def on_resume(self, fn: Callable) -> Callable:
        """Decorator — register an optional resume handler."""
        self._resume_fn = fn
        return fn

    def run(self) -> None:
        """Start the agent host loop (blocking)."""
        if self._agent_fn is None:
            raise RuntimeError(
                "No agent function registered. "
                "Use the @dspatch.agent(ContextClass) decorator."
            )

        import logging
        import os
        import sys

        # Configure logging early so all dspatch.* loggers produce output.
        logging.basicConfig(
            level=logging.INFO,
            format="%(name)s %(levelname)s %(message)s",
            stream=sys.stderr,
        )
        # Allow DEBUG records from the dspatch namespace so they can be
        # captured by the _DspatchLogHandler and forwarded over the wire.
        logging.getLogger("dspatch").setLevel(logging.DEBUG)

        agent_key = os.environ.get("DSPATCH_AGENT_KEY", "?")
        print(f"[dspatch-sdk] DspatchEngine.run() starting for {agent_key}",
              flush=True)

        from .client import WsClient
        from .host import AgentHostRouter

        client = WsClient()
        try:
            asyncio.run(
                AgentHostRouter(
                    self._agent_fn, client,
                    context_class=self._context_class,
                ).start()
            )
        except (KeyboardInterrupt, SystemExit):
            # Expected during container shutdown (SIGTERM/SIGINT from Docker).
            pass
