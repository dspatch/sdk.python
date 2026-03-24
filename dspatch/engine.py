# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""DspatchEngine — entry point for building dspatch agents.

v2: Uses gRPC channel to local dspatch-router instead of WebSocket to engine.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Callable
from typing import Any

from .contexts.context import Context
from .grpc_channel import GrpcChannel

logger = logging.getLogger("dspatch.engine")


class DspatchEngine:
    """Top-level API for building a dspatch agent."""

    def __init__(self) -> None:
        self._agent_fn: Callable | None = None
        self._context_class: type[Context] = Context
        self._resume_fn: Callable | None = None

    def agent(
        self, context_class: type[Context] | None = None
    ) -> Callable:
        """Decorator to register the agent handler function."""
        def decorator(fn: Callable) -> Callable:
            self._agent_fn = fn
            if context_class is not None:
                self._context_class = context_class
            return fn
        return decorator

    def on_resume(self, fn: Callable) -> Callable:
        """Decorator to register an optional resume handler."""
        self._resume_fn = fn
        return fn

    def run(self) -> None:
        """Blocking entry point. Connects to router, registers, starts worker."""
        self._configure_logging()

        if self._agent_fn is None:
            raise RuntimeError("No agent function registered. Use @engine.agent()")

        asyncio.run(self._async_run())

    async def _async_run(self) -> None:
        from .agent_worker import AgentWorker
        from .generated import dspatch_router_pb2

        channel = GrpcChannel()
        await channel.connect()

        try:
            # Register with router
            resp = await channel.stub.Register(
                dspatch_router_pb2.RegisterRequest(
                    name=channel.agent_key,
                    role="host",
                    capabilities=[],
                )
            )
            if not resp.ok:
                logger.error("Registration failed")
                return

            logger.info(
                "Registered as %s (instance %s), router v%s",
                channel.agent_key,
                channel.instance_id,
                resp.router_version,
            )

            # Start worker
            worker = AgentWorker(
                agent_fn=self._agent_fn,
                channel=channel,
                context_class=self._context_class,
            )
            await worker.run()

        finally:
            await channel.disconnect()

    def _configure_logging(self) -> None:
        """Set up dspatch.* logging."""
        root = logging.getLogger("dspatch")
        if not root.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(
                logging.Formatter("[%(name)s] %(levelname)s: %(message)s")
            )
            root.addHandler(handler)
            root.setLevel(logging.DEBUG if os.environ.get("DSPATCH_DEBUG") else logging.INFO)
