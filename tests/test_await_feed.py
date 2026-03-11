# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for Context._await_feed() — the shared blocking loop."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from dspatch.contexts import Context
from dspatch.dispatcher import (
    ResponseItem,
    InquiryInterruptItem,
    TerminationItem,
)
from dspatch.models import InquiryResponse
from dspatch.state_manager import StateManager
from dspatch.instance_router import AgentInstanceRouter


def _make_context():
    """Create a Context with a mock runner backed by real StateManager+AgentInstanceRouter."""
    host = MagicMock()
    host.send_event = AsyncMock()

    sm = StateManager()
    router = AgentInstanceRouter(state_manager=sm)
    sm.enter_generating()  # valid starting state for waiting transitions

    runner = MagicMock()
    runner._send_event = AsyncMock()
    runner._send_activity = AsyncMock(return_value="activity_id")
    runner._router = router
    runner._sm = sm

    ctx = Context(host=host, runner=runner, instance_id="inst_001")
    return ctx, runner, sm, router


class TestAwaitFeedResponse:
    @pytest.mark.asyncio
    async def test_returns_response_item(self):
        ctx, runner, sm, router = _make_context()
        sm.enter_waiting_for_agent("r1", "agent_b")

        async def put_response():
            await asyncio.sleep(0.01)
            router.feed.put_nowait(
                ResponseItem(event={"type": "agent.event.talk_to.response", "request_id": "r1", "response": "hello"})
            )

        asyncio.create_task(put_response())
        item = await ctx._await_feed(expected_request_id="r1")
        assert isinstance(item, ResponseItem)
        assert item.event["response"] == "hello"

    @pytest.mark.asyncio
    async def test_state_is_waiting_before_response_arrives(self):
        ctx, runner, sm, router = _make_context()
        sm.enter_waiting_for_agent("r1", "agent_b")

        states_during_wait = []

        async def put_response():
            await asyncio.sleep(0.01)
            states_during_wait.append(sm.current_state)
            router.feed.put_nowait(
                ResponseItem(event={"type": "agent.event.talk_to.response", "request_id": "r1"})
            )

        asyncio.create_task(put_response())
        await ctx._await_feed(expected_request_id="r1")
        assert "waiting_for_agent" in states_during_wait


class TestAwaitFeedInterrupt:
    @pytest.mark.asyncio
    async def test_returns_inquiry_interrupt(self):
        ctx, runner, sm, router = _make_context()
        sm.enter_waiting_for_agent("r1", "agent_b")

        async def put_interrupt():
            await asyncio.sleep(0.01)
            router.feed.put_nowait(
                InquiryInterruptItem(event={"type": "agent.event.inquiry.request", "inquiry_id": "i1"})
            )

        asyncio.create_task(put_interrupt())
        item = await ctx._await_feed(expected_request_id="r1")
        assert isinstance(item, InquiryInterruptItem)


class TestAwaitFeedTermination:
    @pytest.mark.asyncio
    async def test_returns_termination_item(self):
        ctx, runner, sm, router = _make_context()
        sm.enter_waiting_for_agent("r1", "agent_b")

        async def put_termination():
            await asyncio.sleep(0.01)
            router.feed.put_nowait(
                TerminationItem(event={"type": "agent.event.request.failed", "request_id": "r1"})
            )

        asyncio.create_task(put_termination())
        item = await ctx._await_feed(expected_request_id="r1")
        assert isinstance(item, TerminationItem)


class TestAwaitFeedMismatchedResponse:
    @pytest.mark.asyncio
    async def test_skips_wrong_request_id(self):
        ctx, runner, sm, router = _make_context()
        sm.enter_waiting_for_agent("r1", "agent_b")

        async def put_items():
            await asyncio.sleep(0.01)
            router.feed.put_nowait(
                ResponseItem(event={"type": "agent.event.talk_to.response", "request_id": "wrong"})
            )
            await asyncio.sleep(0.01)
            router.feed.put_nowait(
                ResponseItem(event={"type": "agent.event.talk_to.response", "request_id": "r1", "response": "correct"})
            )

        asyncio.create_task(put_items())
        item = await ctx._await_feed(expected_request_id="r1")
        assert item.event["response"] == "correct"


class TestTalkToWithFeed:
    @pytest.mark.asyncio
    async def test_talk_to_returns_response(self):
        ctx, runner, sm, router = _make_context()

        async def put_response():
            await asyncio.sleep(0.02)
            while sm.pending_wait is None:
                await asyncio.sleep(0.01)
            rid = sm.pending_wait.request_id
            router.feed.put_nowait(
                ResponseItem(event={
                    "type": "agent.event.talk_to.response",
                    "request_id": rid,
                    "response": "hello back",
                })
            )

        asyncio.create_task(put_response())
        result = await ctx.talk_to("agent_b", "hello")
        assert result == "hello back"
        assert sm.pending_wait is None

    @pytest.mark.asyncio
    async def test_talk_to_returns_interrupt_string(self):
        ctx, runner, sm, router = _make_context()

        async def put_interrupt():
            await asyncio.sleep(0.02)
            while sm.pending_wait is None:
                await asyncio.sleep(0.01)
            router.feed.put_nowait(
                InquiryInterruptItem(event={
                    "type": "agent.event.inquiry.request",
                    "inquiry_id": "i1",
                })
            )

        asyncio.create_task(put_interrupt())
        result = await ctx.talk_to("agent_b", "hello")
        assert "INTERRUPTED" in result
        assert sm.pending_wait is not None
        assert sm.pending_wait.peer == "agent_b"


class TestInquireWithFeed:
    @pytest.mark.asyncio
    async def test_inquire_returns_response(self):
        ctx, runner, sm, router = _make_context()

        async def put_response():
            await asyncio.sleep(0.02)
            while sm.pending_wait is None:
                await asyncio.sleep(0.01)
            rid = sm.pending_wait.request_id
            router.feed.put_nowait(
                ResponseItem(event={
                    "type": "agent.event.inquiry.response",
                    "request_id": rid,
                    "response_text": "yes do it",
                })
            )

        asyncio.create_task(put_response())
        result = await ctx.inquire("Should I proceed?", suggestions=["yes", "no"])
        assert isinstance(result, InquiryResponse)
        assert result.text == "yes do it"

    @pytest.mark.asyncio
    async def test_inquire_returns_interrupt_string(self):
        ctx, runner, sm, router = _make_context()

        async def put_interrupt():
            await asyncio.sleep(0.02)
            while sm.pending_wait is None:
                await asyncio.sleep(0.01)
            router.feed.put_nowait(
                InquiryInterruptItem(event={
                    "type": "agent.event.inquiry.request",
                    "inquiry_id": "i1",
                })
            )

        asyncio.create_task(put_interrupt())
        result = await ctx.inquire("Should I proceed?", suggestions=["yes", "no"])
        assert isinstance(result, str)
        assert "INTERRUPTED" in result


