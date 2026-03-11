# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for the receive_incoming_inquiry tool."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from dspatch.dispatcher import InquiryInterruptItem
from dspatch.tools.receive_inquiry import NAME, DESCRIPTION, SCHEMA, execute
from dspatch.state_manager import StateManager
from dspatch.instance_router import AgentInstanceRouter


def _make_ctx(interrupt_event=None, *, has_pending_wait=False):
    """Create a mock context with StateManager for testing."""
    sm = StateManager()
    router = AgentInstanceRouter(state_manager=sm)

    if interrupt_event is not None:
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        interrupt = InquiryInterruptItem(event=interrupt_event)
        sm.receive_unexpected(interrupt)  # stores current_interrupt, transitions to generating
        if not has_pending_wait:
            # Artificially clear pending_wait to isolate the branch where
            # current_interrupt is set but no outer talk_to wait is active.
            # This state cannot arise via the public API; the private attribute
            # is set directly to unit-test that specific code path.
            sm._pending_wait = None

    runner = MagicMock()
    runner._sm = sm
    runner._send_event = AsyncMock()
    runner._send_activity = AsyncMock(return_value="activity_id")

    ctx = MagicMock()
    ctx._runner = runner
    ctx._pending_inquiry_id = None
    ctx.activity = AsyncMock(return_value="activity_id")
    return ctx, sm


class TestToolDefinition:
    def test_name(self):
        assert NAME == "receive_incoming_inquiry"

    def test_schema_has_no_required_params(self):
        assert SCHEMA.get("required", []) == []


class TestExecute:
    @pytest.mark.asyncio
    async def test_returns_inquiry_content(self):
        ctx, sm = _make_ctx(
            interrupt_event={
                "type": "agent.event.inquiry.request",
                "inquiry_id": "inq_001",
                "from_agent": "Coder",
                "content_markdown": "Redis or Postgres?",
                "suggestions": [{"text": "Redis"}, {"text": "Postgres"}],
            },
            has_pending_wait=True,
        )

        result = await execute(ctx)

        assert "content" in result
        text = result["content"][0]["text"]
        assert "Coder" in text
        assert "Redis or Postgres?" in text
        assert "reply_to_inquiry" in text
        assert "continue_waiting_for_agent_response" in text

    @pytest.mark.asyncio
    async def test_sets_pending_inquiry_id(self):
        ctx, sm = _make_ctx(
            interrupt_event={
                "type": "agent.event.inquiry.request",
                "inquiry_id": "inq_002",
                "from_agent": "Worker",
                "content_markdown": "What now?",
            },
            has_pending_wait=False,
        )

        await execute(ctx)
        assert ctx._pending_inquiry_id == "inq_002"

    @pytest.mark.asyncio
    async def test_error_when_no_interrupt(self):
        sm = StateManager()  # idle state, no interrupt
        runner = MagicMock()
        runner._sm = sm
        ctx = MagicMock()
        ctx._runner = runner
        ctx.activity = AsyncMock(return_value="activity_id")

        result = await execute(ctx)
        assert result.get("is_error") is True

    @pytest.mark.asyncio
    async def test_no_continue_waiting_instruction_when_not_blocked(self):
        ctx, sm = _make_ctx(
            interrupt_event={
                "type": "agent.event.inquiry.request",
                "inquiry_id": "inq_003",
                "from_agent": "Worker",
                "content_markdown": "Question?",
            },
            has_pending_wait=False,
        )

        result = await execute(ctx)
        text = result["content"][0]["text"]
        assert "continue_waiting_for_agent_response" not in text
