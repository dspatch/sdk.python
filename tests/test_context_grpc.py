# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for Context gRPC methods."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from dspatch.contexts.context import Context
from dspatch.generated import dspatch_router_pb2


@pytest.fixture
def mock_ctx():
    channel = MagicMock()
    channel.agent_key = "lead"
    channel.instance_id = "lead-0"
    channel.stub = MagicMock()
    channel.stub.SendOutput = AsyncMock(
        return_value=dspatch_router_pb2.Ack(ok=True)
    )

    ctx = Context(
        channel=channel,
        instance_id="lead-0",
        turn_id="turn-1",
        messages=[],
    )
    return ctx


@pytest.mark.asyncio
async def test_message_sends_output(mock_ctx):
    await mock_ctx.message("Hello")
    mock_ctx._channel.stub.SendOutput.assert_called_once()
    call_arg = mock_ctx._channel.stub.SendOutput.call_args[0][0]
    assert call_arg.HasField("message")
    assert call_arg.message.content == "Hello"


@pytest.mark.asyncio
async def test_log_sends_output(mock_ctx):
    mock_ctx.log("test message", "info")
    await asyncio.sleep(0)  # Allow fire-and-forget coroutine to execute
    mock_ctx._channel.stub.SendOutput.assert_called_once()


@pytest.mark.asyncio
async def test_talk_to_returns_response(mock_ctx):
    mock_ctx._channel.stub.TalkTo = AsyncMock(
        return_value=dspatch_router_pb2.TalkToRpcResponse(
            success=dspatch_router_pb2.TalkToSuccess(
                request_id="req-1",
                response="Done!",
                conversation_id="conv-1",
            )
        )
    )
    result = await mock_ctx.talk_to("coder", "Build this")
    assert result == "Done!"


@pytest.mark.asyncio
async def test_talk_to_cycle_raises(mock_ctx):
    mock_ctx._channel.stub.TalkTo = AsyncMock(
        return_value=dspatch_router_pb2.TalkToRpcResponse(
            error=dspatch_router_pb2.TalkToError(
                request_id="",
                reason="cycle_detected",
            )
        )
    )
    with pytest.raises(RuntimeError, match="cycle_detected"):
        await mock_ctx.talk_to("coder", "Build this")


@pytest.mark.asyncio
async def test_talk_to_stores_conversation_id(mock_ctx):
    mock_ctx._channel.stub.TalkTo = AsyncMock(
        return_value=dspatch_router_pb2.TalkToRpcResponse(
            success=dspatch_router_pb2.TalkToSuccess(
                request_id="req-1",
                response="OK",
                conversation_id="conv-42",
            )
        )
    )
    await mock_ctx.talk_to("coder", "Hello")
    assert mock_ctx._peer_conversations["coder"] == "conv-42"


@pytest.mark.asyncio
async def test_inquire_returns_response_text(mock_ctx):
    mock_ctx._channel.stub.Inquire = AsyncMock(
        return_value=dspatch_router_pb2.InquireRpcResponse(
            success=dspatch_router_pb2.InquireSuccess(
                inquiry_id="inq-1",
                response_text="Yes, proceed",
            )
        )
    )
    result = await mock_ctx.inquire("Should I proceed?", suggestions=["Yes", "No"])
    assert result == "Yes, proceed"


@pytest.mark.asyncio
async def test_inquire_error_raises(mock_ctx):
    mock_ctx._channel.stub.Inquire = AsyncMock(
        return_value=dspatch_router_pb2.InquireRpcResponse(
            error=dspatch_router_pb2.InquireError(
                inquiry_id="inq-1",
                reason="timeout",
            )
        )
    )
    with pytest.raises(RuntimeError, match="timeout"):
        await mock_ctx.inquire("Question?", suggestions=["A", "B"])


@pytest.mark.asyncio
async def test_inquire_validates_suggestions(mock_ctx):
    with pytest.raises(ValueError, match="at least 2 items"):
        await mock_ctx.inquire("Question?", suggestions=["only one"])


@pytest.mark.asyncio
async def test_activity_sends_output(mock_ctx):
    aid = await mock_ctx.activity("tool_call", content="running")
    assert isinstance(aid, str)
    mock_ctx._channel.stub.SendOutput.assert_called_once()
    call_arg = mock_ctx._channel.stub.SendOutput.call_args[0][0]
    assert call_arg.HasField("activity")
    assert call_arg.activity.event_type == "tool_call"


@pytest.mark.asyncio
async def test_usage_sends_output(mock_ctx):
    await mock_ctx.usage("gpt-4", 100, 50, cost_usd=0.01)
    mock_ctx._channel.stub.SendOutput.assert_called_once()
    call_arg = mock_ctx._channel.stub.SendOutput.call_args[0][0]
    assert call_arg.HasField("usage")
    assert call_arg.usage.model == "gpt-4"
    assert call_arg.usage.input_tokens == 100


@pytest.mark.asyncio
async def test_files_sends_output(mock_ctx):
    await mock_ctx.files([{"path": "main.py", "action": "created"}])
    mock_ctx._channel.stub.SendOutput.assert_called_once()
    call_arg = mock_ctx._channel.stub.SendOutput.call_args[0][0]
    assert call_arg.HasField("files")
    assert len(call_arg.files.files) == 1
    assert call_arg.files.files[0].path == "main.py"


@pytest.mark.asyncio
async def test_prompt_sends_output(mock_ctx):
    await mock_ctx.prompt("Hello agent", sender_name="user")
    mock_ctx._channel.stub.SendOutput.assert_called_once()
    call_arg = mock_ctx._channel.stub.SendOutput.call_args[0][0]
    assert call_arg.HasField("prompt_received")
    assert call_arg.prompt_received.content == "Hello agent"


@pytest.mark.asyncio
async def test_turn_id_property(mock_ctx):
    assert mock_ctx.turn_id == "turn-1"
