# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""AgentWorker — consumes gRPC EventStream, runs agent function, signals CompleteTurn.

v2: No state machine, no turn ID management, no buffer. The router handles all of that.
Main loop: receive event -> create context -> run agent -> CompleteTurn.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from .generated import dspatch_router_pb2
from .models import Message

if TYPE_CHECKING:
    from .contexts.context import Context
    from .grpc_channel import GrpcChannel

logger = logging.getLogger("dspatch.worker")


class AgentWorker:
    """Consumes events from the router's gRPC EventStream and runs the agent function."""

    def __init__(
        self,
        agent_fn: Callable,
        channel: GrpcChannel,
        context_class: type[Context],
    ) -> None:
        self._agent_fn = agent_fn
        self._channel = channel
        self._context_class = context_class
        self._running = True
        self._is_generator = inspect.isasyncgenfunction(agent_fn)
        self._gen = None

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        """Main worker loop: receive events from router, run agent, complete turn."""
        req = dspatch_router_pb2.EventStreamRequest(
            name=self._channel.agent_key,
            instance_id=self._channel.instance_id,
        )

        logger.info("Starting event stream for %s", self._channel.instance_id)

        async for event in self._channel.stub.EventStream(req):
            if not self._running:
                break

            try:
                await self._handle_event(event)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error handling event for %s", self._channel.instance_id)

    async def _handle_event(self, event: dspatch_router_pb2.RouterEvent) -> None:
        """Dispatch a single RouterEvent."""
        which = event.WhichOneof("event")

        if which == "user_input":
            await self._handle_user_input(event)
        elif which == "talk_to_request":
            await self._handle_talk_to_request(event)
        elif which == "inquiry_request":
            await self._handle_inquiry_request(event)
        elif which == "drain":
            logger.info("Drain signal received, stopping")
            self.stop()
        elif which == "terminate":
            logger.info("Terminate signal received, stopping")
            self.stop()
        elif which == "interrupt":
            logger.info("Interrupt signal received")
            await self._close_gen()

    async def _handle_user_input(self, event: dspatch_router_pb2.RouterEvent) -> None:
        """Handle user_input: create context, run agent, complete turn."""
        ui = event.user_input
        text = ui.text

        # Parse history
        messages = [
            Message(id=m.id, role=m.role, content=m.content)
            for m in ui.history
        ]

        # Create context
        ctx = self._context_class(
            channel=self._channel,
            instance_id=event.instance_id,
            turn_id=event.turn_id,
            messages=messages,
        )

        # Send prompt_received
        await ctx.prompt(text)

        # Run agent
        result = await self._run_agent(text, ctx)

        # Complete turn
        await self._channel.stub.CompleteTurn(
            dspatch_router_pb2.CompleteTurnRequest(
                instance_id=event.instance_id,
                turn_id=event.turn_id,
                result=result,
            )
        )

    async def _handle_talk_to_request(self, event: dspatch_router_pb2.RouterEvent) -> None:
        """Handle talk_to_request: run agent, complete turn with response."""
        req = event.talk_to_request

        ctx = self._context_class(
            channel=self._channel,
            instance_id=event.instance_id,
            turn_id=event.turn_id,
            messages=[],
        )

        await ctx.prompt(req.text, sender_name=req.caller_agent)
        result = await self._run_agent(req.text, ctx)

        await self._channel.stub.CompleteTurn(
            dspatch_router_pb2.CompleteTurnRequest(
                instance_id=event.instance_id,
                turn_id=event.turn_id,
                result=result or "",
            )
        )

    async def _handle_inquiry_request(self, event: dspatch_router_pb2.RouterEvent) -> None:
        """Handle inquiry_request when idle (as a new input)."""
        inq = event.inquiry_request
        text = f"[Inquiry from {inq.from_agent}]: {inq.content_markdown}"

        ctx = self._context_class(
            channel=self._channel,
            instance_id=event.instance_id,
            turn_id=event.turn_id,
            messages=[],
        )

        await self._run_agent(text, ctx)

        await self._channel.stub.CompleteTurn(
            dspatch_router_pb2.CompleteTurnRequest(
                instance_id=event.instance_id,
                turn_id=event.turn_id,
            )
        )

    async def _run_agent(self, text: str, ctx) -> str | None:
        """Run the agent function (oneshot or generator)."""
        if self._is_generator:
            return await self._run_generator(text, ctx)
        return await self._run_oneshot(text, ctx)

    async def _run_oneshot(self, text: str, ctx) -> str | None:
        result = await self._agent_fn(text, ctx)
        return str(result) if result is not None else None

    async def _run_generator(self, text: str, ctx) -> str | None:
        if self._gen is None:
            self._gen = self._agent_fn(text, ctx)
            result = await self._gen.__anext__()
        else:
            result = await self._gen.asend(text)
        return str(result) if result is not None else None

    async def _close_gen(self) -> None:
        if self._gen is not None:
            await self._gen.aclose()
            self._gen = None
