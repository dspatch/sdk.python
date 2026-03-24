# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for ClaudeAgentContext setup / run / context manager."""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dspatch.contexts import ClaudeAgentContext
from dspatch.generated import dspatch_router_pb2


def _install_mock_claude_sdk():
    """Install a fake ``claude_agent_sdk`` module into sys.modules."""
    mod = types.ModuleType("claude_agent_sdk")
    mod.ClaudeSDKClient = MagicMock
    mod.ClaudeAgentOptions = MagicMock
    mod.create_sdk_mcp_server = MagicMock(return_value=MagicMock())
    mod.tool = lambda name, desc, schema: (lambda fn: fn)
    sys.modules["claude_agent_sdk"] = mod
    return mod


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


class TestClaudeAgentContextSetup:
    def test_setup_stores_system_prompt(self):
        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup(system_prompt="You are helpful.")
        assert ctx._user_system_prompt == "You are helpful."

    def test_setup_stores_options(self):
        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        mock_options = MagicMock()
        ctx.setup(system_prompt="Hello", options=mock_options)
        assert ctx._user_options is mock_options

    def test_setup_without_system_prompt_uses_empty_string(self):
        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        ctx.setup()  # system_prompt defaults to ''
        assert ctx._user_system_prompt == ''


class TestClaudeAgentContextManager:
    @pytest.mark.asyncio
    async def test_enter_creates_client(self):
        mock_sdk = _install_mock_claude_sdk()

        mock_client = AsyncMock()
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sdk.ClaudeSDKClient = MagicMock(return_value=mock_client_ctx)

        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        mock_options = MagicMock()
        mock_options.system_prompt = None
        ctx.setup(system_prompt="Test", options=mock_options)

        async with ctx:
            assert ctx.client is mock_client

    @pytest.mark.asyncio
    async def test_exit_cleans_up_client(self):
        mock_sdk = _install_mock_claude_sdk()

        mock_client = AsyncMock()
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sdk.ClaudeSDKClient = MagicMock(return_value=mock_client_ctx)

        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        mock_options = MagicMock()
        mock_options.system_prompt = None
        ctx.setup(system_prompt="Test", options=mock_options)

        async with ctx:
            pass

        mock_client_ctx.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_enter_without_setup_raises(self):
        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        with pytest.raises(RuntimeError, match="setup.*before"):
            async with ctx:
                pass


class TestClaudeAgentContextPrivateMethods:
    def test_augment_system_prompt_is_private(self):
        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        assert hasattr(ctx, "_augment_system_prompt")
        assert not hasattr(ctx, "augment_system_prompt")

    def test_get_tools_is_private(self):
        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        assert hasattr(ctx, "_get_tools")
        assert not hasattr(ctx, "get_tools")

    def test_process_response_stream_is_private(self):
        ctx = ClaudeAgentContext(channel=_make_channel(), instance_id="test-0", turn_id="turn_1", messages=[])
        assert hasattr(ctx, "_process_response_stream")
        assert not hasattr(ctx, "process_response_stream")
