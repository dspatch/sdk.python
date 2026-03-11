# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
# packages/dspatch-sdk/tests/test_instance_router.py
"""Tests for AgentInstanceRouter."""

import asyncio
import pytest
from unittest.mock import MagicMock

from dspatch.instance_router import AgentInstanceRouter
from dspatch.state_manager import StateManager
from dspatch.dispatcher import (
    InputItem, ResponseItem, InquiryInterruptItem, TerminationItem,
)


def _make_router():
    sm = StateManager()
    router = AgentInstanceRouter(state_manager=sm)
    return router, sm


class TestInboundRoutingIdle:
    def test_user_input_goes_to_feed_when_idle(self):
        router, sm = _make_router()
        router.receive({"type": "agent.event.user_input", "content": "hello"})
        assert not router.feed.empty()
        item = router.feed.get_nowait()
        assert isinstance(item, InputItem)

    def test_inquiry_request_goes_to_feed_when_idle(self):
        router, sm = _make_router()
        router.receive({"type": "agent.event.inquiry.request", "inquiry_id": "inq1"})
        assert not router.feed.empty()
        item = router.feed.get_nowait()
        assert isinstance(item, InquiryInterruptItem)


class TestInboundRoutingGenerating:
    def test_user_input_buffered_when_generating(self):
        router, sm = _make_router()
        sm.enter_generating()
        router.receive({"type": "agent.event.user_input", "content": "hello"})
        assert router.feed.empty()
        assert len(router._buffer) == 1

    def test_response_buffered_when_generating(self):
        router, sm = _make_router()
        sm.enter_generating()
        router.receive({"type": "agent.event.talk_to.response", "request_id": "r1"})
        assert router.feed.empty()
        assert len(router._buffer) == 1


class TestInboundRoutingBlocked:
    def test_response_goes_to_feed_when_blocked(self):
        router, sm = _make_router()
        sm.enter_generating()
        sm.enter_waiting_for_agent("r1", "agent_b")
        router.receive({"type": "agent.event.talk_to.response", "request_id": "r1"})
        assert not router.feed.empty()

    def test_inquiry_goes_to_feed_when_blocked(self):
        router, sm = _make_router()
        sm.enter_generating()
        sm.enter_waiting_for_agent("r1", "agent_b")
        router.receive({"type": "agent.event.inquiry.request", "inquiry_id": "inq1"})
        assert not router.feed.empty()

    def test_user_input_buffered_when_blocked(self):
        router, sm = _make_router()
        sm.enter_generating()
        sm.enter_waiting_for_agent("r1", "agent_b")
        router.receive({"type": "agent.event.user_input", "content": "hi"})
        assert router.feed.empty()
        assert len(router._buffer) == 1


class TestBufferFlush:
    def test_buffer_flushed_when_state_returns_to_idle(self):
        router, sm = _make_router()
        sm.enter_generating()
        router.receive({"type": "agent.event.user_input", "content": "hello"})
        assert router.feed.empty()
        sm.enter_idle()
        assert not router.feed.empty()

    def test_inquiry_delivered_before_input_on_flush(self):
        router, sm = _make_router()
        sm.enter_generating()
        router.receive({"type": "agent.event.user_input", "content": "first"})
        router.receive({"type": "agent.event.inquiry.request", "inquiry_id": "inq1"})
        sm.enter_idle()
        first = router.feed.get_nowait()
        assert isinstance(first, InquiryInterruptItem)


class TestTurnIdStack:
    def test_initial_turn_id_is_none(self):
        router, sm = _make_router()
        assert router.current_turn_id is None

    def test_push_turn_sets_turn_id(self):
        router, sm = _make_router()
        router.push_turn("abc")
        assert router.current_turn_id == "abc"

    def test_pop_turn_restores_previous(self):
        router, sm = _make_router()
        router.push_turn("abc")
        router.push_turn("def")
        router.pop_turn()
        assert router.current_turn_id == "abc"

    def test_pop_turn_on_empty_stack_is_noop(self):
        router, sm = _make_router()
        router.pop_turn()  # should not raise
        assert router.current_turn_id is None


class TestOutboundTagging:
    def test_tag_outbound_injects_turn_id(self):
        router, sm = _make_router()
        router.push_turn("abc123")
        tagged = router.tag_outbound({"type": "agent.output.message", "content": "hi"})
        assert tagged["turn_id"] == "abc123"

    def test_tag_outbound_no_turn_id_when_stack_empty(self):
        router, sm = _make_router()
        tagged = router.tag_outbound({"type": "agent.output.message", "content": "hi"})
        assert "turn_id" not in tagged

    def test_tag_outbound_does_not_modify_original(self):
        router, sm = _make_router()
        router.push_turn("abc")
        original = {"type": "agent.output.message"}
        tagged = router.tag_outbound(original)
        assert "turn_id" not in original
        assert "turn_id" in tagged


class TestControlEvents:
    def test_control_events_trigger_on_control_callback(self):
        router, sm = _make_router()
        received = []
        router.on_control = received.append
        router.receive({"type": "agent.signal.state_query", "request_id": "r1"})
        assert len(received) == 1
        assert received[0]["type"] == "agent.signal.state_query"

    def test_keepalive_events_trigger_on_keepalive_callback(self):
        router, sm = _make_router()
        received = []
        router.on_keepalive = received.append
        router.receive({"type": "agent.event.request.alive", "request_id": "r1"})
        assert len(received) == 1

    def test_terminate_event_triggers_on_control(self):
        router, sm = _make_router()
        received = []
        router.on_control = received.append
        router.receive({"type": "agent.signal.terminate"})
        assert len(received) == 1
        assert router.feed.empty()

    def test_drain_event_triggers_on_control(self):
        router, sm = _make_router()
        received = []
        router.on_control = received.append
        router.receive({"type": "agent.signal.drain"})
        assert len(received) == 1
        assert router.feed.empty()


class TestIdleResponseBuffering:
    def test_response_buffered_when_idle(self):
        router, sm = _make_router()
        router.receive({"type": "agent.event.talk_to.response", "request_id": "r1"})
        assert router.feed.empty()
        assert len(router._buffer) == 1
        assert isinstance(router._buffer[0], ResponseItem)

    def test_termination_buffered_when_idle(self):
        router, sm = _make_router()
        router.receive({"type": "agent.event.request.failed", "request_id": "r1"})
        assert router.feed.empty()
        assert len(router._buffer) == 1
        assert isinstance(router._buffer[0], TerminationItem)

    def test_response_not_flushed_when_state_returns_to_idle(self):
        router, sm = _make_router()
        sm.enter_generating()
        router.receive({"type": "agent.event.talk_to.response", "request_id": "r1"})
        assert len(router._buffer) == 1
        sm.enter_idle()
        # ResponseItem must remain in buffer, not flushed to feed
        assert router.feed.empty()
        assert len(router._buffer) == 1
        assert isinstance(router._buffer[0], ResponseItem)


class TestInquiryAliveAndFailed:
    def test_inquiry_alive_is_keepalive(self):
        router, sm = _make_router()
        received = []
        router.on_keepalive = received.append
        router.receive({"type": "agent.event.inquiry.alive", "inquiry_id": "q1"})
        assert len(received) == 1
        assert received[0]["type"] == "agent.event.inquiry.alive"
        assert received[0]["inquiry_id"] == "q1"
        assert router.feed.empty()

    def test_inquiry_failed_delivers_when_waiting_for_inquiry(self):
        router, sm = _make_router()
        sm.enter_generating()
        sm.enter_waiting_for_inquiry("q1")
        router.receive({"type": "agent.event.inquiry.failed", "inquiry_id": "q1", "reason": "expired"})
        assert not router.feed.empty()
        item = router.feed.get_nowait()
        assert isinstance(item, TerminationItem)
        assert item.event["reason"] == "expired"


class TestTurnIdStackAutoGenerate:
    def test_push_turn_auto_generates_id(self):
        router, sm = _make_router()
        router.push_turn()
        assert router.current_turn_id is not None
        assert isinstance(router.current_turn_id, str)
        assert len(router.current_turn_id) > 0
