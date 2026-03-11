# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for AgentInstanceRouter input gate routing."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from dspatch.agent_worker import AgentWorker
from dspatch.instance_router import AgentInstanceRouter
from dspatch.state_manager import StateManager
from dspatch.dispatcher import (
    InputItem,
    InquiryInterruptItem,
    ResponseItem,
)


def _make_stack(**overrides):
    """Create AgentInstanceRouter + StateManager with AgentWorker."""
    host = MagicMock()
    host.send_event = AsyncMock()

    sm = StateManager()
    router = AgentInstanceRouter(state_manager=sm)
    worker = AgentWorker(
        agent_fn=overrides.get("agent_fn", AsyncMock(return_value="ok")),
        agent_name="test-agent",
        instance_id=overrides.get("instance_id", "inst_001"),
        router=router,
        state_manager=sm,
        host=host,
    )
    return worker, router, sm, host


class TestAgentStateTransitions:
    def test_initial_state_is_idle(self):
        _, router, sm, _ = _make_stack()
        assert sm.current_state == "idle"

    def test_set_generating(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        assert sm.current_state == "generating"

    def test_set_idle_from_generating(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        sm.enter_idle()
        assert sm.current_state == "idle"

    def test_set_idle_flushes_buffer(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        router.receive({"type": "agent.event.user_input", "content": "hi"})
        assert len(router._buffer) == 1
        sm.enter_idle()
        assert len(router._buffer) == 0
        assert not router.feed.empty()


class TestRouterReceive:
    """Test AgentInstanceRouter.receive() routing based on StateManager state."""

    def test_user_input_dispatched_when_idle(self):
        _, router, sm, _ = _make_stack()
        router.receive({"type": "agent.event.user_input", "content": "hi"})
        assert not router.feed.empty()
        item = router.feed.get_nowait()
        assert isinstance(item, InputItem)

    def test_user_input_buffered_when_generating(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        router.receive({"type": "agent.event.user_input", "content": "hi"})
        assert router.feed.empty()
        assert len(router._buffer) == 1

    def test_user_input_buffered_when_waiting_for_agent(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        router.receive({"type": "agent.event.user_input", "content": "hi"})
        assert router.feed.empty()
        assert len(router._buffer) == 1

    def test_inquiry_request_dispatched_when_idle(self):
        _, router, sm, _ = _make_stack()
        event = {"type": "agent.event.inquiry.request", "inquiry_id": "inq1",
                 "from_agent": "coder", "content_markdown": "q?"}
        router.receive(event)
        assert not router.feed.empty()
        item = router.feed.get_nowait()
        assert isinstance(item, InquiryInterruptItem)

    def test_inquiry_request_dispatched_when_waiting_for_agent(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        event = {"type": "agent.event.inquiry.request", "inquiry_id": "inq1",
                 "from_agent": "coder", "content_markdown": "q?"}
        router.receive(event)
        assert not router.feed.empty()
        item = router.feed.get_nowait()
        assert isinstance(item, InquiryInterruptItem)

    def test_inquiry_request_buffered_when_generating(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        event = {"type": "agent.event.inquiry.request", "inquiry_id": "inq1",
                 "from_agent": "coder", "content_markdown": "q?"}
        router.receive(event)
        assert len(router._buffer) == 1

    def test_response_item_dispatched_when_waiting(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        router.receive({
            "type": "agent.event.talk_to.response",
            "request_id": "req1",
            "response": "done",
        })
        assert not router.feed.empty()
        item = router.feed.get_nowait()
        assert isinstance(item, ResponseItem)

    def test_talk_to_request_dispatched_when_idle(self):
        _, router, sm, _ = _make_stack()
        router.receive({"type": "agent.event.talk_to.request", "text": "go"})
        assert not router.feed.empty()

    def test_talk_to_request_buffered_when_generating(self):
        _, router, sm, _ = _make_stack()
        sm.enter_generating()
        router.receive({"type": "agent.event.talk_to.request", "text": "go"})
        assert router.feed.empty()
        assert len(router._buffer) == 1


class TestContextStateCallbacks:
    @pytest.mark.asyncio
    async def test_inquire_sets_waiting_then_back_to_generating(self):
        worker, router, sm, host = _make_stack()
        from dspatch.contexts import Context
        ctx = Context(host=host, runner=worker, instance_id="inst_001")
        worker._ctx = ctx
        sm.enter_generating()
        router.push_turn("turn_test")
        worker._current_turn_id = "turn_test"

        # Pre-signal a response so inquire() won't block forever.
        async def signal_soon():
            await asyncio.sleep(0.05)
            while sm.pending_wait is None:
                await asyncio.sleep(0.01)
            rid = sm.pending_wait.request_id
            router.feed.put_nowait(
                ResponseItem(event={
                    "type": "agent.event.inquiry.response",
                    "request_id": rid,
                    "response_text": "answer",
                })
            )

        asyncio.create_task(signal_soon())

        # Track state transitions.
        states = []
        original_set_state = sm._set_state

        def track(s):
            states.append(s)
            original_set_state(s)

        sm._set_state = track

        result = await ctx.inquire("question?", suggestions=["a", "b"])

        assert "waiting_for_inquiry" in states
        assert "generating" in states
