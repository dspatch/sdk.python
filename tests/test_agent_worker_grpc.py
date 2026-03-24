# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for simplified AgentWorker (gRPC)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dspatch.agent_worker import AgentWorker


@pytest.fixture
def mock_channel():
    ch = MagicMock()
    ch.agent_key = "lead"
    ch.instance_id = "lead-0"
    ch.stub = MagicMock()
    return ch


@pytest.fixture
def mock_context_class():
    """Return a mock context class whose instances have an async prompt()."""
    def factory(*args, **kwargs):
        ctx = MagicMock()
        ctx.prompt = AsyncMock()
        return ctx
    return factory


@pytest.mark.asyncio
async def test_worker_calls_agent_on_user_input(mock_channel, mock_context_class):
    """Worker should call agent function when receiving user_input event."""
    from dspatch.generated.dspatch_router_pb2 import (
        RouterEvent, UserInputEvent, EventStreamRequest, Ack,
    )

    # Mock the EventStream to yield one event then stop
    event = RouterEvent(
        instance_id="lead-0",
        turn_id="turn-1",
        user_input=UserInputEvent(text="hello", history=[]),
    )

    async def mock_event_stream(req):
        yield event

    mock_channel.stub.EventStream = mock_event_stream
    mock_channel.stub.CompleteTurn = AsyncMock(return_value=Ack(ok=True))

    agent_called = asyncio.Event()

    async def my_agent(text, ctx):
        agent_called.set()

    worker = AgentWorker(
        agent_fn=my_agent,
        channel=mock_channel,
        context_class=mock_context_class,
    )

    # Run worker with a timeout
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(agent_called.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("Agent function was not called")
    finally:
        worker.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_worker_calls_complete_turn_after_agent(mock_channel, mock_context_class):
    """Worker should call CompleteTurn after agent function returns."""
    from dspatch.generated.dspatch_router_pb2 import (
        RouterEvent, UserInputEvent, Ack,
    )

    event = RouterEvent(
        instance_id="lead-0",
        turn_id="turn-1",
        user_input=UserInputEvent(text="hello", history=[]),
    )

    async def mock_event_stream(req):
        yield event

    mock_channel.stub.EventStream = mock_event_stream
    mock_channel.stub.CompleteTurn = AsyncMock(return_value=Ack(ok=True))

    async def my_agent(text, ctx):
        return "response"

    worker = AgentWorker(
        agent_fn=my_agent,
        channel=mock_channel,
        context_class=mock_context_class,
    )

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    worker.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    mock_channel.stub.CompleteTurn.assert_called_once()
    call_args = mock_channel.stub.CompleteTurn.call_args
    req = call_args[0][0]
    assert req.instance_id == "lead-0"
    assert req.turn_id == "turn-1"
    assert req.result == "response"


@pytest.mark.asyncio
async def test_worker_handles_drain_signal(mock_channel, mock_context_class):
    """Worker should stop when receiving drain signal."""
    from dspatch.generated.dspatch_router_pb2 import (
        RouterEvent, DrainSignal,
    )

    event = RouterEvent(
        instance_id="lead-0",
        turn_id="",
        drain=DrainSignal(),
    )

    async def mock_event_stream(req):
        yield event

    mock_channel.stub.EventStream = mock_event_stream

    worker = AgentWorker(
        agent_fn=AsyncMock(),
        channel=mock_channel,
        context_class=mock_context_class,
    )

    # run() should complete when drain is received
    await asyncio.wait_for(worker.run(), timeout=2.0)
    assert not worker._running


@pytest.mark.asyncio
async def test_worker_handles_terminate_signal(mock_channel, mock_context_class):
    """Worker should stop when receiving terminate signal."""
    from dspatch.generated.dspatch_router_pb2 import (
        RouterEvent, TerminateSignal,
    )

    event = RouterEvent(
        instance_id="lead-0",
        turn_id="",
        terminate=TerminateSignal(),
    )

    async def mock_event_stream(req):
        yield event

    mock_channel.stub.EventStream = mock_event_stream

    worker = AgentWorker(
        agent_fn=AsyncMock(),
        channel=mock_channel,
        context_class=mock_context_class,
    )

    await asyncio.wait_for(worker.run(), timeout=2.0)
    assert not worker._running


@pytest.mark.asyncio
async def test_worker_handles_talk_to_request(mock_channel, mock_context_class):
    """Worker should handle talk_to_request events."""
    from dspatch.generated.dspatch_router_pb2 import (
        RouterEvent, TalkToRequestEvent, Ack,
    )

    event = RouterEvent(
        instance_id="lead-0",
        turn_id="turn-2",
        talk_to_request=TalkToRequestEvent(
            request_id="req-1",
            caller_agent="manager",
            text="do something",
        ),
    )

    async def mock_event_stream(req):
        yield event

    mock_channel.stub.EventStream = mock_event_stream
    mock_channel.stub.CompleteTurn = AsyncMock(return_value=Ack(ok=True))

    agent_called = asyncio.Event()

    async def my_agent(text, ctx):
        agent_called.set()
        return "done"

    worker = AgentWorker(
        agent_fn=my_agent,
        channel=mock_channel,
        context_class=mock_context_class,
    )

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(agent_called.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("Agent function was not called for talk_to_request")
    finally:
        worker.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mock_channel.stub.CompleteTurn.assert_called_once()


@pytest.mark.asyncio
async def test_worker_handles_inquiry_request(mock_channel, mock_context_class):
    """Worker should handle inquiry_request events."""
    from dspatch.generated.dspatch_router_pb2 import (
        RouterEvent, InquiryRequestEvent, Ack,
    )

    event = RouterEvent(
        instance_id="lead-0",
        turn_id="turn-3",
        inquiry_request=InquiryRequestEvent(
            inquiry_id="inq-1",
            from_agent="supervisor",
            content_markdown="What should we do?",
        ),
    )

    async def mock_event_stream(req):
        yield event

    mock_channel.stub.EventStream = mock_event_stream
    mock_channel.stub.CompleteTurn = AsyncMock(return_value=Ack(ok=True))

    agent_called = asyncio.Event()

    async def my_agent(text, ctx):
        agent_called.set()

    worker = AgentWorker(
        agent_fn=my_agent,
        channel=mock_channel,
        context_class=mock_context_class,
    )

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(agent_called.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("Agent function was not called for inquiry_request")
    finally:
        worker.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_worker_generator_agent(mock_channel, mock_context_class):
    """Worker should support async generator agent functions."""
    from dspatch.generated.dspatch_router_pb2 import (
        RouterEvent, UserInputEvent, Ack,
    )

    event = RouterEvent(
        instance_id="lead-0",
        turn_id="turn-1",
        user_input=UserInputEvent(text="hello", history=[]),
    )

    async def mock_event_stream(req):
        yield event

    mock_channel.stub.EventStream = mock_event_stream
    mock_channel.stub.CompleteTurn = AsyncMock(return_value=Ack(ok=True))

    agent_called = asyncio.Event()

    async def my_gen_agent(text, ctx):
        agent_called.set()
        yield "gen-response"

    worker = AgentWorker(
        agent_fn=my_gen_agent,
        channel=mock_channel,
        context_class=mock_context_class,
    )

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(agent_called.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("Generator agent function was not called")
    finally:
        worker.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_worker_interrupt_closes_generator(mock_channel, mock_context_class):
    """Worker should close generator on interrupt signal."""
    from dspatch.generated.dspatch_router_pb2 import (
        RouterEvent, InterruptSignal,
    )

    event = RouterEvent(
        instance_id="lead-0",
        turn_id="",
        interrupt=InterruptSignal(),
    )

    async def mock_event_stream(req):
        yield event

    mock_channel.stub.EventStream = mock_event_stream

    gen_closed = False

    async def my_gen_agent(text, ctx):
        nonlocal gen_closed
        try:
            yield "response"
        except GeneratorExit:
            gen_closed = True

    worker = AgentWorker(
        agent_fn=my_gen_agent,
        channel=mock_channel,
        context_class=mock_context_class,
    )

    # Pre-initialize a generator so _close_gen has something to close
    worker._gen = my_gen_agent("test", MagicMock())
    await worker._gen.__anext__()  # advance past yield

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    worker.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Generator should have been closed
    assert worker._gen is None
