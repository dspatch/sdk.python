# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""AgentWorker — consumes from AgentInstanceRouter feed, runs agent function."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import traceback
from collections.abc import AsyncGenerator, Callable

from .dispatcher import InputItem, InquiryInterruptItem
from .instance_router import AgentInstanceRouter
from .state_manager import StateManager

logger = logging.getLogger("dspatch.worker")


def _with_sender_header(content: str, sender: str) -> str:
    """Prepend a sender header to prompt content."""
    return f"{{{{SENDER: {sender}}}}}\n{content}"


class AgentWorker:
    """Consumes items from the AgentInstanceRouter feed and runs the agent.

    Does not own state — uses StateManager to enter/exit states.
    Handles:
    - user_input → run agent, send result
    - talk_to_request → run agent, send talk_to_response
    - inquiry_request (when idle) → inject as input, run agent
    """

    def __init__(
        self,
        *,
        agent_fn: Callable,
        agent_name: str,
        instance_id: str,
        router: AgentInstanceRouter,
        state_manager: StateManager,
        host: object,
        context_class=None,
    ) -> None:
        from .contexts import Context
        self._agent_fn = agent_fn
        self._agent_name = agent_name
        self._instance_id = instance_id
        self._router = router
        self._sm = state_manager
        self._host = host
        self._context_class = context_class or Context
        self._is_generator = inspect.isasyncgenfunction(agent_fn)
        self._gen: AsyncGenerator | None = None
        self._running = True
        self._ctx = None
        self._current_turn_id: str | None = None
        self._interrupted = False

    # ── Main loop ────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main worker loop — pops from feed, runs agent, repeats."""
        self._ctx = self._context_class(
            host=self._host,
            runner=self,  # AgentWorker acts as the runner interface for Context
            instance_id=self._instance_id,
        )
        logger.info("AgentWorker %s ready", self._instance_id)
        try:
            while self._running:
                try:
                    item = await self._router.feed.get()
                except asyncio.CancelledError:
                    raise
                await self._run_one_item(item)
        finally:
            await self._close_gen()

    async def _run_one(self) -> None:
        """Process exactly one item from the feed (for testing)."""
        if self._ctx is None:
            from .contexts import Context
            self._ctx = self._context_class(
                host=self._host, runner=self, instance_id=self._instance_id,
            )
        item = await self._router.feed.get()
        await self._run_one_item(item)

    async def _run_one_item(self, item) -> None:
        """Dispatch a single feed item."""
        if item is None:
            return  # Sentinel for testing

        try:
            self._sm.enter_generating()
            turn_id = self._router.push_turn()
            self._current_turn_id = turn_id

            if isinstance(item, InquiryInterruptItem):
                await self._handle_idle_inquiry(item)
            elif isinstance(item, InputItem):
                await self._handle_input(item)

            self._router.pop_turn()
            self._sm.enter_idle()

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("AgentWorker error:\n%s", traceback.format_exc())
            try:
                self._router.pop_turn()
                self._sm.enter_idle()
            except Exception:
                pass

    async def _handle_input(self, item: InputItem) -> None:
        event = item.event
        event_type = event.get("type", "")

        if event_type == "agent.event.user_input":
            content = event.get("content", "")
            if not content:
                return
            await self._ctx.prompt(content)
            self._ctx._message_sent = False
            result = await self._run_agent(_with_sender_header(content, "user"), self._ctx)
            if result and not self._ctx._message_sent:
                await self._send_message(result)

        elif event_type == "agent.event.talk_to.request":
            text = event.get("text", "")
            request_id = event.get("request_id", "")
            caller = event.get("caller_agent", "") or "unknown"

            # Emit a dedicated talk_to.receive activity.
            # TODO: Comment this in again, after refactoring how prompt_recevied is visualized
            # await self._ctx.activity(
            #     "talk_to.receive",
            #     data={
            #         "request_id": request_id,
            #         "caller_agent": caller,
            #         "text": text,
            #     },
            # )

            await self._ctx.prompt(text, sender_name=caller)
            self._ctx._message_sent = False
            result = await self._run_agent(_with_sender_header(text, caller), self._ctx)
            await self._send_talk_to_response(request_id=request_id, response=result or "")

        else:
            logger.warning("AgentWorker: unhandled input event type %r", event_type)

    async def _handle_idle_inquiry(self, item: InquiryInterruptItem) -> None:
        """Handle an inquiry that arrived while idle (new input)."""
        from .tools.inquiry_interrupt import format_inquiry_injection
        event = item.event
        inquiry_id = event.get("inquiry_id", "")
        from_agent = event.get("from_agent", "unknown")
        injection = format_inquiry_injection(
            from_agent=from_agent,
            content=event.get("content_markdown", ""),
            suggestions=[
                s.get("text", "") if isinstance(s, dict) else str(s)
                for s in event.get("suggestions", [])
            ] or None,
        )
        self._ctx._pending_inquiry_id = inquiry_id
        await self._ctx.prompt(injection, sender_name=from_agent)
        self._ctx._message_sent = False
        result = await self._run_agent(_with_sender_header(injection, from_agent), self._ctx)
        if result and not self._ctx._message_sent:
            await self._send_message(result)
        self._ctx._pending_inquiry_id = None

    # ── Agent execution ──────────────────────────────────────────────────

    async def _run_agent(self, text, ctx):
        if self._is_generator:
            return await self._run_generator(text, ctx)
        return await self._run_oneshot(text, ctx)

    async def _run_oneshot(self, text, ctx):
        try:
            result = self._agent_fn(text, ctx)
            if asyncio.iscoroutine(result):
                result = await result
            return result if isinstance(result, str) else None
        except Exception:
            logger.error("Agent error:\n%s", traceback.format_exc())
            ctx.log(traceback.format_exc(), level="error")
            return f"Error: {traceback.format_exc()[:300]}"

    async def _run_generator(self, text, ctx):
        try:
            if self._gen is None:
                self._gen = self._agent_fn(text, ctx)
                result = await self._gen.asend(None)
            else:
                result = await self._gen.asend(text)
            return result if isinstance(result, str) else None
        except StopAsyncIteration:
            self._gen = None
            return None
        except Exception:
            logger.error("Agent error:\n%s", traceback.format_exc())
            ctx.log(traceback.format_exc(), level="error")
            self._gen = None
            return f"Error: {traceback.format_exc()[:300]}"

    async def _close_gen(self):
        gen, self._gen = self._gen, None
        if gen is not None:
            try:
                await gen.aclose()
            except Exception:
                pass

    # ── Send helpers (Context uses these via runner interface) ───────────

    async def _send_event(self, event: dict) -> None:
        tagged = self._router.tag_outbound({
            **event,
            "instance_id": self._instance_id,
            "ts": int(time.time() * 1000),
        })
        await self._host.send_event(tagged)

    async def _send_message(self, content: str, **kwargs) -> str:
        from .contexts.context import _uuid7_hex
        msg_id = kwargs.pop("message_id", None) or _uuid7_hex()
        await self._send_event({
            "type": "agent.output.message",
            "id": msg_id,
            "role": kwargs.pop("role", "assistant"),
            "content": content,
            "is_delta": kwargs.pop("is_delta", False),
            **kwargs,
        })
        return msg_id

    async def _send_activity(
        self,
        event_type: str,
        *,
        content: str | None = None,
        is_delta: bool = False,
        activity_id: str | None = None,
        data: dict | None = None,
    ) -> str:
        from .contexts.context import _uuid7_hex
        aid = activity_id or _uuid7_hex()
        event: dict = {
            "type": "agent.output.activity",
            "id": aid,
            "event_type": event_type,
            "is_delta": is_delta,
        }
        if content is not None:
            event["content"] = content
        if data is not None:
            event["data"] = data
        await self._send_event(event)
        return aid

    async def _send_prompt_received(self, content: str, *, sender_name=None) -> None:
        await self._send_event({
            "type": "agent.output.prompt_received",
            "content": content,
            "sender_name": sender_name,
        })

    async def _send_talk_to_response(self, request_id: str, response: str) -> None:
        await self._send_event({
            "type": "agent.event.talk_to.response",
            "request_id": request_id,
            "response": response,
            "conversation_id": self._instance_id,
        })
