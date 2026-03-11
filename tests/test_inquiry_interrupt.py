# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for inquiry interrupt flow --- forwarded inquiries and reply_to_inquiry tool."""

from __future__ import annotations

import asyncio

import pytest

from dspatch.agent_worker import AgentWorker
from dspatch.contexts import Context
from dspatch.instance_router import AgentInstanceRouter
from dspatch.state_manager import StateManager
from dspatch.dispatcher import InquiryInterruptItem
from dspatch.models import PendingWait
from dspatch.tools.inquiry_interrupt import (
    REPLY_NAME,
    REPLY_SCHEMA,
    execute_reply,
    format_inquiry_injection,
)


# -- Helpers ----------------------------------------------------------------


class FakeHost:
    """Minimal fake AgentHost for testing."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_event(self, event: dict) -> None:
        self.sent.append(event)


def _make_stack(
    *,
    agent_fn=None,
    instance_id: str = "inst_001",
    host: FakeHost | None = None,
) -> tuple[AgentWorker, AgentInstanceRouter, StateManager, FakeHost]:
    if agent_fn is None:
        async def agent_fn(text, ctx):
            return f"echo: {text}"

    if host is None:
        host = FakeHost()

    sm = StateManager()
    router = AgentInstanceRouter(state_manager=sm)
    worker = AgentWorker(
        agent_fn=agent_fn,
        agent_name="test-agent",
        instance_id=instance_id,
        router=router,
        state_manager=sm,
        host=host,
    )
    return worker, router, sm, host


def _make_ctx(worker: AgentWorker, host: FakeHost, instance_id: str = "inst_001") -> Context:
    return Context(
        host=host,
        runner=worker,
        instance_id=instance_id,
    )


def _make_ctx_with_pending_wait(request_id="r1", peer="agent_b"):
    """Create a Context whose StateManager has a preserved pending_wait.

    Sets up state by calling enter_waiting_for_agent then receive_unexpected,
    which preserves pending_wait and transitions back to generating.
    """
    host = FakeHost()
    worker, router, sm, host = _make_stack(host=host)

    sm.enter_generating()
    sm.enter_waiting_for_agent(request_id, peer)
    interrupt = InquiryInterruptItem(event={"type": "agent.event.inquiry.request", "inquiry_id": "i1"})
    sm.receive_unexpected(interrupt)  # pending_wait preserved, state = generating

    ctx = _make_ctx(worker, host)
    return ctx, worker, host


# -- format_inquiry_injection -----------------------------------------------


class TestFormatInquiryInjection:
    def test_structured_inquiry_message_format(self) -> None:
        msg = format_inquiry_injection(
            from_agent="Coder",
            content="Redis or Postgres?",
            suggestions=["Redis", "Postgres"],
        )
        assert "Coder" in msg
        assert "Redis or Postgres?" in msg
        assert "reply_to_inquiry" in msg
        assert "send_inquiry" in msg
        assert "1. Redis" in msg
        assert "2. Postgres" in msg

    def test_no_suggestions(self) -> None:
        msg = format_inquiry_injection(
            from_agent="Worker",
            content="Should I proceed?",
        )
        assert "Worker" in msg
        assert "Should I proceed?" in msg
        assert "Suggestions" not in msg
        assert "reply_to_inquiry" in msg

    def test_empty_suggestions(self) -> None:
        msg = format_inquiry_injection(
            from_agent="Worker",
            content="What now?",
            suggestions=[],
        )
        assert "Suggestions" not in msg


# -- execute_reply ----------------------------------------------------------


class TestExecuteReply:
    @pytest.mark.asyncio
    async def test_reply_to_inquiry_sends_response(self) -> None:
        """Verify reply_to_inquiry tool sends inquiry_response event."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn_interrupt")
        worker._current_turn_id = "turn_interrupt"
        ctx = _make_ctx(worker, host)

        result = await execute_reply(
            ctx,
            args={"response": "Use Postgres, we need ACID"},
            inquiry_id="inq_abc123",
        )

        # Check the event was sent.
        response_events = [
            e for e in host.sent
            if e.get("type") == "agent.event.inquiry.response"
        ]
        assert len(response_events) == 1
        assert response_events[0]["inquiry_id"] == "inq_abc123"
        assert response_events[0]["response_text"] == "Use Postgres, we need ACID"
        assert "packet_type" not in response_events[0]

        # Check MCP content format.
        assert "content" in result
        assert "Postgres" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_reply_includes_continue_waiting_when_pending(self) -> None:
        """When agent has a pending_wait, reply includes resume instructions."""
        ctx, worker, host = _make_ctx_with_pending_wait()

        result = await execute_reply(
            ctx,
            args={"response": "Use Postgres"},
            inquiry_id="inq_abc123",
        )

        text = result["content"][0]["text"]
        assert "continue_waiting_for_agent_response" in text

    @pytest.mark.asyncio
    async def test_reply_no_continue_when_no_pending(self) -> None:
        """When agent has no pending_wait, reply does not mention continue."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn_interrupt")
        worker._current_turn_id = "turn_interrupt"
        ctx = _make_ctx(worker, host)
        # sm.pending_wait is None (in generating state, no wait entered)

        result = await execute_reply(
            ctx,
            args={"response": "Use Postgres"},
            inquiry_id="inq_abc123",
        )

        text = result["content"][0]["text"]
        assert "continue_waiting" not in text


# -- Tool definition constants -----------------------------------------------


class TestToolDefinition:
    def test_reply_name(self) -> None:
        assert REPLY_NAME == "reply_to_inquiry"

    def test_reply_schema_has_response(self) -> None:
        assert "response" in REPLY_SCHEMA["properties"]
        assert "response" in REPLY_SCHEMA["required"]


# -- inquiry_request handling in event loop ----------------------------------


class TestInquiryRequestInEventLoop:
    @pytest.mark.asyncio
    async def test_inquiry_request_when_idle_handled_as_input(self) -> None:
        """When idle, inquiry_request goes through feed as InquiryInterruptItem."""
        host = FakeHost()

        inquiry_injection_seen = None

        async def supervisor_agent(text, ctx):
            nonlocal inquiry_injection_seen
            if "[INQUIRY FROM SUBORDINATE AGENT]" in (text or ""):
                inquiry_injection_seen = text
                await execute_reply(
                    ctx,
                    args={"response": "Use Postgres"},
                    inquiry_id=ctx._pending_inquiry_id or "",
                )
            return f"done: {text}"

        worker, router, sm, host = _make_stack(
            agent_fn=supervisor_agent,
            host=host,
        )

        # Put an inquiry_request into the router feed when idle.
        # The router classifies inquiry_request as InquiryInterruptItem
        # and delivers it to feed when state == idle.
        router.receive({
            "type": "agent.event.inquiry.request",
            "from_agent": "Coder",
            "content_markdown": "Redis or Postgres?",
            "suggestions": [{"text": "Redis"}, {"text": "Postgres"}],
            "inquiry_id": "inq_fwd_001",
        })

        await asyncio.wait_for(worker._run_one(), timeout=2.0)

        assert inquiry_injection_seen is not None
        assert "Coder" in inquiry_injection_seen
        assert "Redis or Postgres?" in inquiry_injection_seen

        response_events = [
            e for e in host.sent
            if e.get("type") == "agent.event.inquiry.response"
        ]
        assert len(response_events) == 1
        assert response_events[0]["inquiry_id"] == "inq_fwd_001"
