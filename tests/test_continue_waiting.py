# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for the continue_waiting_for_agent_response tool."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from dspatch.contexts import Context
from dspatch.dispatcher import (
    ResponseItem,
    InquiryInterruptItem,
    TerminationItem,
)
from dspatch.models import PendingWait
from dspatch.state_manager import StateManager
from dspatch.instance_router import AgentInstanceRouter
from dspatch.tools.continue_waiting import NAME, DESCRIPTION, SCHEMA, execute


def _make_context_waiting(request_id="r1", peer="agent_b"):
    """Create a Context in waiting_for_agent state for testing continue_waiting."""
    sm = StateManager()
    router = AgentInstanceRouter(state_manager=sm)
    # Set up the state: generating → waiting (interrupted) → generating
    # Simulate that we were waiting and got interrupted, so pending_wait is preserved
    sm.enter_generating()
    sm.enter_waiting_for_agent(request_id, peer)
    interrupt = InquiryInterruptItem(event={"type": "agent.event.inquiry.request", "inquiry_id": "i1"})
    sm.receive_unexpected(interrupt)  # pending_wait preserved, state = generating

    runner = MagicMock()
    runner._send_event = AsyncMock()
    runner._send_activity = AsyncMock(return_value="activity_id")
    runner._router = router
    runner._sm = sm

    ctx = Context(host=MagicMock(), runner=runner, instance_id="inst_001")
    return ctx, runner, sm, router


class TestToolDefinition:
    def test_name(self):
        assert NAME == "continue_waiting_for_agent_response"

    def test_schema_has_no_required_params(self):
        assert SCHEMA.get("required", []) == []


class TestExecute:
    @pytest.mark.asyncio
    async def test_returns_response_when_received(self):
        ctx, runner, sm, router = _make_context_waiting()

        async def put_response():
            await asyncio.sleep(0.01)
            router.feed.put_nowait(
                ResponseItem(event={
                    "type": "agent.event.talk_to.response",
                    "request_id": "r1",
                    "response": "here are results",
                })
            )

        asyncio.create_task(put_response())
        result = await execute(ctx)

        text = result["content"][0]["text"]
        assert "here are results" in text
        assert "agent_b" in text
        assert sm.pending_wait is None

    @pytest.mark.asyncio
    async def test_returns_interrupt_when_inquiry_arrives(self):
        ctx, runner, sm, router = _make_context_waiting()

        async def put_interrupt():
            await asyncio.sleep(0.01)
            router.feed.put_nowait(
                InquiryInterruptItem(event={
                    "type": "agent.event.inquiry.request",
                    "inquiry_id": "i1",
                })
            )

        asyncio.create_task(put_interrupt())
        result = await execute(ctx)

        text = result["content"][0]["text"]
        assert "INTERRUPTED" in text
        assert "receive_incoming_inquiry" in text
        # pending_wait should be preserved
        assert sm.pending_wait is not None

    @pytest.mark.asyncio
    async def test_returns_error_on_termination(self):
        ctx, runner, sm, router = _make_context_waiting()

        async def put_termination():
            await asyncio.sleep(0.01)
            router.feed.put_nowait(
                TerminationItem(event={
                    "type": "agent.event.request.failed",
                    "request_id": "r1",
                    "reason": "agent crashed",
                })
            )

        asyncio.create_task(put_termination())
        result = await execute(ctx)

        assert result.get("is_error") is True
        assert "agent crashed" in result["content"][0]["text"]
        assert sm.pending_wait is None

    @pytest.mark.asyncio
    async def test_error_when_no_pending_wait(self):
        sm = StateManager()
        router = AgentInstanceRouter(state_manager=sm)
        runner = MagicMock()
        runner._send_event = AsyncMock()
        runner._router = router
        runner._sm = sm

        ctx = Context(host=MagicMock(), runner=runner, instance_id="inst_001")
        # sm.pending_wait is None (idle state)

        result = await execute(ctx)
        assert result.get("is_error") is True
        assert "No pending wait" in result["content"][0]["text"]
