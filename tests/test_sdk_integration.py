# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
# packages/dspatch-sdk/tests/test_sdk_integration.py
"""Integration tests for the full Python SDK stack.

Tests use real classes (StateManager, AgentInstanceRouter, AgentWorker, Context)
with a FakeHost to capture outgoing events.
"""

from __future__ import annotations

import asyncio

import pytest

from dspatch.agent_worker import AgentWorker
from dspatch.contexts import Context
from dspatch.dispatcher import (
    InquiryInterruptItem,
    InputItem,
    ResponseItem,
)
from dspatch.instance_router import AgentInstanceRouter
from dspatch.models import InquiryResponse
from dspatch.state_manager import StateManager
from dspatch.tools import continue_waiting, receive_inquiry
from dspatch.tools.inquiry_interrupt import execute_reply


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeHost:
    """Minimal stand-in for AgentHost that records sent events."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_event(self, event: dict) -> None:
        self.sent.append(event)


def _make_stack(
    *,
    agent_fn=None,
    instance_id: str = "inst_test",
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


def _make_ctx(
    worker: AgentWorker,
    host: FakeHost,
    instance_id: str = "inst_test",
) -> Context:
    ctx = Context(host=host, runner=worker, instance_id=instance_id)
    # Pre-wire ctx onto the worker so blocking tool calls (talk_to, inquire)
    # have a Context without running through _run_one's full setup path.
    # Safe because _run_one_item only sets _ctx if it is None (no overwrite).
    worker._ctx = ctx
    return ctx


def _events_of_type(host: FakeHost, event_type: str) -> list[dict]:
    return [e for e in host.sent if e.get("type") == event_type]


# ---------------------------------------------------------------------------
# Suite 1: Full AgentWorker + AgentInstanceRouter + StateManager lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:

    @pytest.mark.asyncio
    async def test_user_input_end_to_end(self) -> None:
        """Feed a user_input event; agent processes it and state returns to idle."""
        received: list[str] = []

        async def agent_fn(text, ctx):
            received.append(text)
            return f"reply: {text}"

        worker, router, sm, host = _make_stack(agent_fn=agent_fn)
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "hello world"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)

        assert len(received) == 1
        assert "hello world" in received[0]
        assert "{{SENDER: user}}" in received[0]
        assert sm.current_state == "idle"
        messages = _events_of_type(host, "agent.output.message")
        assert len(messages) == 1
        assert "hello world" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_multiple_inputs_processed_sequentially(self) -> None:
        """Two user_input events are processed in sequence; agent called twice."""
        call_count = 0

        async def agent_fn(text, ctx):
            nonlocal call_count
            call_count += 1
            return f"turn {call_count}"

        worker, router, sm, host = _make_stack(agent_fn=agent_fn)
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "first"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)

        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "second"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)

        assert call_count == 2
        assert sm.current_state == "idle"
        messages = _events_of_type(host, "agent.output.message")
        assert len(messages) == 2
        assert messages[0]["content"] == "turn 1"
        assert messages[1]["content"] == "turn 2"

    @pytest.mark.asyncio
    async def test_input_buffered_during_generating(self) -> None:
        """A second user_input that arrives during generating is buffered, then processed."""
        # We simulate buffering by sending the second event to the router while the
        # state is generating (i.e., before _run_one completes).
        call_count = 0
        second_processed = asyncio.Event()

        async def agent_fn(text, ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # While generating (state=generating), inject the second input.
                # Router is in generating state so it will buffer it.
                router.receive({"type": "agent.event.user_input", "content": "second"})
            return f"turn {call_count}"

        worker, router, sm, host = _make_stack(agent_fn=agent_fn)

        # Feed and process first item.
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "first"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)

        # After first item completes, router flush should have put second into feed.
        assert sm.current_state == "idle"
        assert router.feed.qsize() == 1, "buffered second input should now be in feed"

        await asyncio.wait_for(worker._run_one(), timeout=2)
        assert call_count == 2
        assert sm.current_state == "idle"


# ---------------------------------------------------------------------------
# Suite 2: talk_to interrupt cycle
# ---------------------------------------------------------------------------


class TestTalkToInterrupt:

    @pytest.mark.asyncio
    async def test_talk_to_blocks_and_receives_response(self) -> None:
        """Agent calls talk_to, enters waiting_for_agent, response arrives, returns text."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn1")
        ctx = _make_ctx(worker, host)

        talk_to_task = asyncio.create_task(ctx.talk_to("agent_b", "do work"))
        await asyncio.sleep(0.05)

        assert sm.current_state == "waiting_for_agent"
        requests = _events_of_type(host, "agent.event.talk_to.request")
        assert len(requests) == 1
        request_id = requests[0]["request_id"]

        router.feed.put_nowait(ResponseItem(event={
            "type": "agent.event.talk_to.response",
            "request_id": request_id,
            "response": "work done",
            "conversation_id": "conv_001",
        }))

        result = await asyncio.wait_for(talk_to_task, timeout=2)
        assert result == "work done"
        assert sm.current_state == "generating"
        assert sm.pending_wait is None

    @pytest.mark.asyncio
    async def test_talk_to_interrupted_by_inquiry(self) -> None:
        """Agent calls talk_to, gets interrupted by inquiry_request, handles it, gets final response."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn1")
        ctx = _make_ctx(worker, host)

        # Step 1: Start talk_to in background.
        talk_to_task = asyncio.create_task(ctx.talk_to("agent_b", "do work"))
        await asyncio.sleep(0.05)

        assert sm.current_state == "waiting_for_agent"
        request_id = _events_of_type(host, "agent.event.talk_to.request")[0]["request_id"]

        # Step 2: Interrupt with an inquiry.
        router.feed.put_nowait(InquiryInterruptItem(event={
            "type": "agent.event.inquiry.request",
            "from_agent": "agent_c",
            "content_markdown": "What do you prefer?",
            "suggestions": [{"text": "Option A"}, {"text": "Option B"}],
            "inquiry_id": "inq_001",
        }))

        interrupt_result = await asyncio.wait_for(talk_to_task, timeout=2)
        assert "INTERRUPTED" in interrupt_result
        assert sm.current_state == "generating"
        assert sm.pending_wait is not None
        assert sm.pending_wait.request_id == request_id

        # Step 3: receive_incoming_inquiry.
        recv = await receive_inquiry.execute(ctx)
        assert "is_error" not in recv
        assert "agent_c" in recv["content"][0]["text"]
        assert ctx._pending_inquiry_id == "inq_001"

        # Step 4: reply_to_inquiry.
        reply = await execute_reply(ctx, args={"response": "Option A"}, inquiry_id="inq_001")
        assert "is_error" not in reply
        assert ctx._pending_inquiry_id is None

        # Step 5: Deliver talk_to_response and call continue_waiting.
        async def deliver():
            await asyncio.sleep(0.05)
            router.feed.put_nowait(ResponseItem(event={
                "type": "agent.event.talk_to.response",
                "request_id": request_id,
                "response": "final answer",
                "conversation_id": "conv_001",
            }))

        asyncio.create_task(deliver())

        cont = await asyncio.wait_for(continue_waiting.execute(ctx), timeout=2)
        assert "is_error" not in cont
        assert "agent_b" in cont["content"][0]["text"]
        assert "final answer" in cont["content"][0]["text"]
        assert sm.pending_wait is None


# ---------------------------------------------------------------------------
# Suite 3: inquire cycle
# ---------------------------------------------------------------------------


class TestInquireCycle:

    @pytest.mark.asyncio
    async def test_inquire_blocks_and_receives_response(self) -> None:
        """Agent calls inquire(), inquiry_response arrives, agent receives the text."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn_inq")
        ctx = _make_ctx(worker, host)

        inquire_task = asyncio.create_task(
            ctx.inquire("Choose an option:", suggestions=["A", "B"])
        )
        await asyncio.sleep(0.05)

        assert sm.current_state == "waiting_for_inquiry"
        inq_requests = _events_of_type(host, "agent.event.inquiry.request")
        assert len(inq_requests) == 1
        inquiry_id = inq_requests[0]["inquiry_id"]

        # Deliver inquiry_response.
        router.feed.put_nowait(ResponseItem(event={
            "type": "agent.event.inquiry.response",
            "request_id": inquiry_id,
            "inquiry_id": inquiry_id,
            "response_text": "A",
            "response_suggestion_index": 0,
        }))

        result = await asyncio.wait_for(inquire_task, timeout=2)
        assert isinstance(result, InquiryResponse)
        assert result.text == "A"
        assert sm.current_state == "generating"
        assert sm.pending_wait is None

    @pytest.mark.asyncio
    async def test_inquire_interrupted_by_higher_priority_inquiry(self) -> None:
        """Agent calls inquire(), gets interrupted by another inquiry_request, handles it,
        then continue_waiting resumes the original inquiry wait."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn_inq")
        ctx = _make_ctx(worker, host)

        # Start inquire.
        inquire_task = asyncio.create_task(
            ctx.inquire("Original question:", suggestions=["X", "Y"])
        )
        await asyncio.sleep(0.05)

        assert sm.current_state == "waiting_for_inquiry"
        original_inquiry_id = _events_of_type(host, "agent.event.inquiry.request")[0]["inquiry_id"]

        # Push an interrupting inquiry.
        router.feed.put_nowait(InquiryInterruptItem(event={
            "type": "agent.event.inquiry.request",
            "from_agent": "agent_d",
            "content_markdown": "Urgent: what is 2+2?",
            "inquiry_id": "inq_urgent",
        }))

        interrupt_result = await asyncio.wait_for(inquire_task, timeout=2)
        assert "INTERRUPTED" in interrupt_result
        assert sm.current_state == "generating"
        assert sm.pending_wait is not None
        assert sm.pending_wait.request_id == original_inquiry_id

        # Handle the interrupting inquiry.
        recv = await receive_inquiry.execute(ctx)
        assert "agent_d" in recv["content"][0]["text"]
        assert ctx._pending_inquiry_id == "inq_urgent"

        reply = await execute_reply(ctx, args={"response": "4"}, inquiry_id="inq_urgent")
        assert "is_error" not in reply

        # Deliver the original inquiry_response and resume.
        async def deliver_original():
            await asyncio.sleep(0.05)
            router.feed.put_nowait(ResponseItem(event={
                "type": "agent.event.inquiry.response",
                "request_id": original_inquiry_id,
                "inquiry_id": original_inquiry_id,
                "response": "X",
                "response_text": "X",
                "response_suggestion_index": 0,
            }))

        asyncio.create_task(deliver_original())

        cont = await asyncio.wait_for(continue_waiting.execute(ctx), timeout=2)
        assert "is_error" not in cont
        assert "X" in cont["content"][0]["text"]
        assert sm.pending_wait is None


# ---------------------------------------------------------------------------
# Suite 4: Output packet fields
# ---------------------------------------------------------------------------


class TestOutputPacketFields:

    @pytest.mark.asyncio
    async def test_output_packets_use_dot_notation_types(self) -> None:
        """All output events use agent.output.* dot-notation type strings."""

        async def agent_fn(text, ctx):
            ctx.log("a log message")
            await ctx.activity("tool_call", data={"description": "doing something"})
            await ctx.usage("test-model", 10, 20, 0.001)
            await ctx.files([{"path": "/tmp/x.txt", "op": "write"}])
            await ctx.message("hello from agent")
            return None

        worker, router, sm, host = _make_stack(agent_fn=agent_fn)
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "go"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)
        # Yield to let fire-and-forget log/activity tasks complete.
        await asyncio.sleep(0.05)

        output_event_types = {
            "agent.output.message", "agent.output.activity",
            "agent.output.log", "agent.output.usage", "agent.output.files",
            "agent.output.prompt_received",
        }
        found_types = {e["type"] for e in host.sent if e.get("type", "").startswith("agent.output.")}
        assert found_types == output_event_types, (
            f"Expected output types {output_event_types}, got {found_types}"
        )
        # No packet_type key should be present.
        for event in host.sent:
            assert "packet_type" not in event, (
                f"Event {event['type']!r} still has packet_type key"
            )

    @pytest.mark.asyncio
    async def test_event_packets_use_dot_notation_types(self) -> None:
        """talk_to_request and inquiry_request events use agent.event.* dot-notation types."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn_ev")
        ctx = _make_ctx(worker, host)

        # Trigger talk_to_request.
        talk_task = asyncio.create_task(ctx.talk_to("agent_b", "ping"))
        await asyncio.sleep(0.05)

        # Cancel the task and clean up state so we can also test inquire.
        talk_task.cancel()
        try:
            await talk_task
        except (asyncio.CancelledError, Exception):
            pass

        # Check talk_to_request uses new type and has no packet_type.
        talk_events = _events_of_type(host, "agent.event.talk_to.request")
        assert len(talk_events) >= 1
        for e in talk_events:
            assert "packet_type" not in e

        # Reset state for inquire test.
        # Re-create stack to get fresh state.
        host2 = FakeHost()
        worker2, router2, sm2, host2 = _make_stack(host=host2)
        sm2.enter_generating()
        router2.push_turn("turn_ev2")
        ctx2 = _make_ctx(worker2, host2)

        inq_task = asyncio.create_task(ctx2.inquire("Question?", suggestions=["Yes", "No"]))
        await asyncio.sleep(0.05)

        inq_task.cancel()
        try:
            await inq_task
        except (asyncio.CancelledError, Exception):
            pass

        inq_events = _events_of_type(host2, "agent.event.inquiry.request")
        assert len(inq_events) >= 1
        for e in inq_events:
            assert "packet_type" not in e

    @pytest.mark.asyncio
    async def test_all_packets_have_instance_id_and_turn_id(self) -> None:
        """Packets sent synchronously during a turn have instance_id and turn_id.

        Fire-and-forget events (log, activity) are excluded from the turn_id
        check because they may be scheduled after the turn stack is popped.
        All non-infra packets must carry instance_id.
        """
        infra_types = {"auth", "heartbeat", "register"}
        # Fire-and-forget methods (ctx.log, ctx.activity) schedule tasks that
        # may execute after pop_turn(), so they won't always carry a turn_id.
        fire_and_forget_types = {"agent.output.log", "agent.output.activity"}

        async def agent_fn(text, ctx):
            # Only use awaited methods so we can assert turn_id is always present.
            await ctx.usage("m", 1, 1)
            await ctx.files([{"path": "/x", "op": "read"}])
            return "done"

        worker, router, sm, host = _make_stack(agent_fn=agent_fn, instance_id="inst_abc")
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "go"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)

        for event in host.sent:
            etype = event.get("type")
            if etype in infra_types:
                continue
            assert event.get("instance_id") == "inst_abc", (
                f"Missing/wrong instance_id on event type={etype!r}: {event}"
            )
            if etype not in fire_and_forget_types:
                assert event.get("turn_id") is not None, (
                    f"Missing turn_id on event type={etype!r}: {event}"
                )
