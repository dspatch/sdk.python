# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for OpenAiAgentContext setup / run / context manager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dspatch.contexts import OpenAiAgentContext
from dspatch.generated import dspatch_router_pb2


def _make_channel():
    """Create a mock GrpcChannel."""
    channel = MagicMock()
    channel.agent_key = "test"
    channel.instance_id = "test-0"
    channel.stub = MagicMock()
    channel.stub.SendOutput = AsyncMock(
        return_value=dspatch_router_pb2.Ack(ok=True)
    )
    return channel


class TestOpenAiAgentContextSetup:
    def test_setup_stores_system_prompt(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup(system_prompt="You are helpful.")
        assert ctx._user_system_prompt == "You are helpful."

    def test_setup_stores_options(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        mock_options = MagicMock()
        ctx.setup(system_prompt="Hello", options=mock_options)
        assert ctx._user_options is mock_options


class TestOpenAiAgentContextManager:
    @pytest.mark.asyncio
    async def test_enter_creates_agent(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup(system_prompt="Test")

        async with ctx:
            assert ctx._agent is not None
            assert ctx._agent.name == "dspatch-agent"

    @pytest.mark.asyncio
    async def test_enter_agent_has_tools(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup(system_prompt="Test")

        async with ctx:
            assert len(ctx._agent.tools) > 0

    @pytest.mark.asyncio
    async def test_enter_agent_has_instructions(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup(system_prompt="Test prompt here")

        async with ctx:
            assert "Test prompt here" in ctx._agent.instructions

    @pytest.mark.asyncio
    async def test_enter_without_setup_raises(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        with pytest.raises(RuntimeError, match="setup.*before"):
            async with ctx:
                pass

    @pytest.mark.asyncio
    async def test_exit_clears_agent(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup(system_prompt="Test")

        async with ctx:
            assert ctx._agent is not None
        assert ctx._agent is None

    @pytest.mark.asyncio
    async def test_run_without_agent_raises(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup(system_prompt="Test")
        with pytest.raises(RuntimeError, match="No active agent"):
            await ctx.run("hello")

    @pytest.mark.asyncio
    async def test_model_from_options(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        opts = MagicMock()
        opts.model = "gpt-4o-mini"
        ctx.setup(system_prompt="Test", options=opts)

        async with ctx:
            assert ctx._agent.model == "gpt-4o-mini"


class TestOpenAiAgentContextPrivateMethods:
    def test_augment_system_prompt_is_private(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        assert hasattr(ctx, "_augment_system_prompt")
        assert not hasattr(ctx, "augment_system_prompt")

    def test_handle_tool_call_is_private(self):
        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        assert hasattr(ctx, "_handle_tool_call")
        assert not hasattr(ctx, "handle_tool_call")

    def test_get_tools_returns_function_tools(self):
        from agents import FunctionTool

        ctx = OpenAiAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup(system_prompt="Test")
        tools = ctx._get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0
        assert all(isinstance(t, FunctionTool) for t in tools)
