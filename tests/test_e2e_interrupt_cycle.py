# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""End-to-end integration test for the full single-feed interrupt cycle.

Exercises the complete flow using the new architecture
(AgentWorker + AgentInstanceRouter + StateManager):
  1. Agent calls talk_to() which blocks on the feed queue
  2. inquiry_request arrives -> agent gets INTERRUPTED
  3. receive_incoming_inquiry reads the inquiry
  4. reply_to_inquiry sends the response
  5. continue_waiting_for_agent_response resumes the wait
  6. talk_to_response arrives -> agent gets the final response
  7. All outgoing events are verified
"""

from __future__ import annotations

import asyncio

import pytest

from dspatch.agent_worker import AgentWorker
from dspatch.contexts import Context
from dspatch.dispatcher import InquiryInterruptItem, ResponseItem
from dspatch.instance_router import AgentInstanceRouter
from dspatch.state_manager import StateManager
from dspatch.tools import receive_inquiry, continue_waiting
from dspatch.tools.inquiry_interrupt import execute_reply


# -- Helpers ----------------------------------------------------------------


class FakeHost:
    """Minimal fake AgentHost for testing."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_event(self, event: dict) -> None:
        self.sent.append(event)


def _make_stack(
    *,
    agent_fn=None,
    instance_id: str = "inst_e2e",
    host: FakeHost | None = None,
) -> tuple[AgentWorker, AgentInstanceRouter, StateManager, FakeHost]:
    """Create an AgentWorker + AgentInstanceRouter + StateManager stack."""
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


def _make_ctx(worker: AgentWorker, host: FakeHost, instance_id: str = "inst_e2e") -> Context:
    """Create a Context wired to the worker."""
    ctx = Context(
        host=host,
        runner=worker,
        instance_id=instance_id,
    )
    worker._ctx = ctx
    return ctx


def _events_of_type(host: FakeHost, event_type: str) -> list[dict]:
    return [e for e in host.sent if e.get("type") == event_type]


# -- Full E2E interrupt cycle -----------------------------------------------


class TestE2EInterruptCycle:
    """Full single-feed interrupt cycle: talk_to -> interrupt -> reply -> resume -> response."""

    @pytest.mark.asyncio
    async def test_full_interrupt_cycle(self) -> None:
        """Complete cycle: talk_to blocks, inquiry interrupts, reply, resume, get response."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)

        # Set up generating state and push a turn ID (mimics AgentWorker._run_one_item).
        sm.enter_generating()
        router.push_turn("turn_e2e")

        ctx = _make_ctx(worker, host)

        # -- Step 1: Start talk_to in a background task (it will block) ------
        talk_to_task = asyncio.create_task(ctx.talk_to("agent_b", "do something"))

        # Yield control so talk_to sends its request event and enters _await_feed.
        await asyncio.sleep(0.05)

        # -- Verify talk_to_request was sent ----------------------------------
        talk_to_requests = _events_of_type(host, "agent.event.talk_to.request")
        assert len(talk_to_requests) == 1, f"Expected 1 talk_to_request, got {len(talk_to_requests)}"
        request_id = talk_to_requests[0]["request_id"]
        assert talk_to_requests[0]["target_agent"] == "agent_b"
        assert talk_to_requests[0]["text"] == "do something"

        # StateManager should now be in waiting_for_agent.
        assert sm.current_state == "waiting_for_agent"

        # -- Step 2: Push inquiry_request event -> interrupts the blocked agent
        router.feed.put_nowait(InquiryInterruptItem(event={
            "type": "agent.event.inquiry.request",
            "from_agent": "agent_c",
            "content_markdown": "Should I use Redis or Postgres?",
            "suggestions": [{"text": "Redis"}, {"text": "Postgres"}],
            "inquiry_id": "inq_001",
        }))

        # talk_to should return the INTERRUPTED string.
        result = await asyncio.wait_for(talk_to_task, timeout=2.0)
        assert "INTERRUPTED" in result
        assert "receive_incoming_inquiry" in result

        # StateManager should be back to generating after the interrupt.
        assert sm.current_state == "generating"

        # pending_wait should still be set (preserved across interrupt).
        assert sm.pending_wait is not None
        assert sm.pending_wait.request_id == request_id
        assert sm.pending_wait.wait_type == "talk_to"
        assert sm.pending_wait.peer == "agent_b"

        # current_interrupt should hold the inquiry item.
        assert sm.current_interrupt is not None

        # -- Step 3: Call receive_incoming_inquiry ----------------------------
        recv_result = await receive_inquiry.execute(ctx)
        assert "is_error" not in recv_result
        recv_text = recv_result["content"][0]["text"]
        assert "agent_c" in recv_text
        assert "Redis or Postgres?" in recv_text
        assert "reply_to_inquiry" in recv_text
        assert "continue_waiting_for_agent_response" in recv_text

        # Inquiry ID should be stored for reply.
        assert ctx._pending_inquiry_id == "inq_001"

        # -- Step 4: Call reply_to_inquiry ------------------------------------
        reply_result = await execute_reply(
            ctx,
            args={"response": "Use Postgres for ACID compliance"},
            inquiry_id="inq_001",
        )
        reply_text = reply_result["content"][0]["text"]
        assert "Postgres" in reply_text
        assert "continue_waiting_for_agent_response" in reply_text

        # Verify the inquiry_response event was sent.
        response_events = _events_of_type(host, "agent.event.inquiry.response")
        assert len(response_events) == 1
        assert response_events[0]["inquiry_id"] == "inq_001"
        assert response_events[0]["response_text"] == "Use Postgres for ACID compliance"

        # pending_inquiry_id should be cleared after reply.
        assert ctx._pending_inquiry_id is None

        # pending_wait should still be intact (we haven't resumed yet).
        assert sm.pending_wait is not None
        assert sm.pending_wait.request_id == request_id

        # -- Step 5: Schedule talk_to_response, then call continue_waiting ----
        async def deliver_response():
            await asyncio.sleep(0.05)
            router.feed.put_nowait(ResponseItem(event={
                "type": "agent.event.talk_to.response",
                "request_id": request_id,
                "response": "Task completed successfully",
                "conversation_id": "conv_b_001",
            }))

        asyncio.create_task(deliver_response())

        # continue_waiting re-enters _await_feed and blocks until the response.
        continue_result = await asyncio.wait_for(
            continue_waiting.execute(ctx), timeout=2.0,
        )

        # -- Step 6: Verify the final response --------------------------------
        assert "is_error" not in continue_result
        continue_text = continue_result["content"][0]["text"]
        assert "agent_b" in continue_text
        assert "Task completed successfully" in continue_text

        # pending_wait should be cleared after successful response.
        assert sm.pending_wait is None

        # -- Step 7: Verify all expected events were sent ---------------------

        # talk_to_request
        assert len(_events_of_type(host, "agent.event.talk_to.request")) == 1

        # inquiry_response
        assert len(_events_of_type(host, "agent.event.inquiry.response")) == 1

        # All non-infrastructure events should have instance_id.
        # turn_id should only appear on output packages and response event packages.
        infra_types = {"auth", "heartbeat", "register"}
        output_or_response = {"agent.output.", "agent.event.talk_to.response", "agent.event.inquiry.response"}
        for event in host.sent:
            etype = event.get("type", "")
            if etype not in infra_types:
                assert event.get("instance_id") == "inst_e2e", f"Missing instance_id on {event}"
                should_have_turn_id = (
                    etype.startswith("agent.output.")
                    or etype in ("agent.event.talk_to.response", "agent.event.inquiry.response")
                )
                if should_have_turn_id:
                    assert event.get("turn_id") == "turn_e2e", f"Missing turn_id on {event}"
                else:
                    assert "turn_id" not in event, f"Unexpected turn_id on {event}"

    @pytest.mark.asyncio
    async def test_interrupt_with_no_pending_wait_errors(self) -> None:
        """receive_incoming_inquiry returns error when no interrupt is pending."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        ctx = _make_ctx(worker, host)

        result = await receive_inquiry.execute(ctx)
        assert result.get("is_error") is True
        assert "No pending inquiry" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_continue_waiting_with_no_pending_wait_errors(self) -> None:
        """continue_waiting returns error when no pending_wait exists."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        ctx = _make_ctx(worker, host)

        result = await continue_waiting.execute(ctx)
        assert result.get("is_error") is True
        assert "No pending wait" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_double_interrupt_cycle(self) -> None:
        """Two interrupts arrive during a single talk_to wait."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn_e2e")
        ctx = _make_ctx(worker, host)

        # Start talk_to.
        talk_to_task = asyncio.create_task(ctx.talk_to("agent_b", "work"))
        await asyncio.sleep(0.05)

        request_id = _events_of_type(host, "agent.event.talk_to.request")[0]["request_id"]

        # -- First interrupt --
        router.feed.put_nowait(InquiryInterruptItem(event={
            "type": "agent.event.inquiry.request",
            "from_agent": "agent_c",
            "content_markdown": "Question 1?",
            "inquiry_id": "inq_first",
        }))

        result1 = await asyncio.wait_for(talk_to_task, timeout=2.0)
        assert "INTERRUPTED" in result1

        # Handle first interrupt.
        recv1 = await receive_inquiry.execute(ctx)
        assert "Question 1?" in recv1["content"][0]["text"]

        await execute_reply(ctx, args={"response": "Answer 1"}, inquiry_id="inq_first")

        # -- Resume, but get second interrupt --
        async def deliver_second_inquiry():
            await asyncio.sleep(0.05)
            router.feed.put_nowait(InquiryInterruptItem(event={
                "type": "agent.event.inquiry.request",
                "from_agent": "agent_d",
                "content_markdown": "Question 2?",
                "inquiry_id": "inq_second",
            }))

        asyncio.create_task(deliver_second_inquiry())

        continue_result1 = await asyncio.wait_for(
            continue_waiting.execute(ctx), timeout=2.0,
        )
        # Should get another INTERRUPTED.
        assert "INTERRUPTED" in continue_result1["content"][0]["text"]

        # Handle second interrupt.
        recv2 = await receive_inquiry.execute(ctx)
        assert "Question 2?" in recv2["content"][0]["text"]

        await execute_reply(ctx, args={"response": "Answer 2"}, inquiry_id="inq_second")

        # -- Resume again, this time the response arrives --
        async def deliver_final_response():
            await asyncio.sleep(0.05)
            router.feed.put_nowait(ResponseItem(event={
                "type": "agent.event.talk_to.response",
                "request_id": request_id,
                "response": "All done",
            }))

        asyncio.create_task(deliver_final_response())

        continue_result2 = await asyncio.wait_for(
            continue_waiting.execute(ctx), timeout=2.0,
        )
        assert "All done" in continue_result2["content"][0]["text"]
        assert sm.pending_wait is None

        # Two inquiry responses should have been sent.
        inquiry_responses = _events_of_type(host, "agent.event.inquiry.response")
        assert len(inquiry_responses) == 2
        assert inquiry_responses[0]["inquiry_id"] == "inq_first"
        assert inquiry_responses[1]["inquiry_id"] == "inq_second"

    @pytest.mark.asyncio
    async def test_talk_to_response_without_interrupt(self) -> None:
        """talk_to returns normally when the response arrives with no interrupts."""
        host = FakeHost()
        worker, router, sm, host = _make_stack(host=host)
        sm.enter_generating()
        router.push_turn("turn_e2e")
        ctx = _make_ctx(worker, host)

        # Start talk_to.
        talk_to_task = asyncio.create_task(ctx.talk_to("agent_b", "hello"))
        await asyncio.sleep(0.05)

        request_id = _events_of_type(host, "agent.event.talk_to.request")[0]["request_id"]

        # Deliver response directly (no interrupt).
        router.feed.put_nowait(ResponseItem(event={
            "type": "agent.event.talk_to.response",
            "request_id": request_id,
            "response": "hi back",
            "conversation_id": "conv_001",
        }))

        result = await asyncio.wait_for(talk_to_task, timeout=2.0)
        assert result == "hi back"
        assert sm.pending_wait is None

        # No interrupt events should exist.
        assert len(_events_of_type(host, "agent.event.inquiry.response")) == 0
