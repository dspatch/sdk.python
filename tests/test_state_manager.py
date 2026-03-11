# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
# packages/dspatch-sdk/tests/test_state_manager.py
"""Tests for StateManager — single owner of agent state."""

import pytest
from unittest.mock import MagicMock

from dspatch.state_manager import StateManager, InvalidStateTransition
from dspatch.dispatcher import InquiryInterruptItem


class TestInitialState:
    def test_initial_state_is_idle(self):
        sm = StateManager()
        assert sm.current_state == "idle"

    def test_initial_pending_wait_is_none(self):
        sm = StateManager()
        assert sm.pending_wait is None

    def test_initial_current_interrupt_is_none(self):
        sm = StateManager()
        assert sm.current_interrupt is None


class TestValidTransitions:
    def test_idle_to_generating(self):
        sm = StateManager()
        sm.enter_generating()
        assert sm.current_state == "generating"

    def test_generating_to_idle(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_idle()
        assert sm.current_state == "idle"

    def test_generating_to_waiting_for_agent(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        assert sm.current_state == "waiting_for_agent"

    def test_generating_to_waiting_for_inquiry(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_inquiry("inq1")
        assert sm.current_state == "waiting_for_inquiry"

    def test_waiting_for_agent_to_generating_via_exit(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        sm.exit_waiting("req1")
        assert sm.current_state == "generating"

    def test_waiting_for_inquiry_to_generating_via_exit(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_inquiry("inq1")
        sm.exit_waiting("inq1")
        assert sm.current_state == "generating"


class TestGuards:
    def test_idle_cannot_enter_waiting_for_agent(self):
        sm = StateManager()
        with pytest.raises(InvalidStateTransition):
            sm.enter_waiting_for_agent("req1", "agent_b")

    def test_idle_cannot_enter_waiting_for_inquiry(self):
        sm = StateManager()
        with pytest.raises(InvalidStateTransition):
            sm.enter_waiting_for_inquiry("inq1")

    def test_idle_cannot_exit_waiting(self):
        sm = StateManager()
        with pytest.raises(InvalidStateTransition):
            sm.exit_waiting("req1")

    def test_waiting_cannot_enter_generating_directly(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        with pytest.raises(InvalidStateTransition):
            sm.enter_generating()

    def test_exit_waiting_wrong_request_id_raises(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        with pytest.raises(ValueError, match="req_wrong"):
            sm.exit_waiting("req_wrong")


class TestPendingWait:
    def test_enter_waiting_for_agent_sets_pending_wait(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        assert sm.pending_wait is not None
        assert sm.pending_wait.wait_type == "talk_to"
        assert sm.pending_wait.request_id == "req1"
        assert sm.pending_wait.peer == "agent_b"

    def test_enter_waiting_for_inquiry_sets_pending_wait(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_inquiry("inq1")
        assert sm.pending_wait is not None
        assert sm.pending_wait.wait_type == "inquiry"
        assert sm.pending_wait.request_id == "inq1"

    def test_exit_waiting_clears_pending_wait(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        sm.exit_waiting("req1")
        assert sm.pending_wait is None


class TestDelegate:
    def test_on_state_changed_fires_on_transition(self):
        sm = StateManager()
        changes = []
        sm.on_state_changed = lambda old, new: changes.append((old, new))
        sm.enter_generating()
        assert changes == [("idle", "generating")]

    def test_on_state_changed_fires_multiple_times(self):
        sm = StateManager()
        changes = []
        sm.on_state_changed = lambda old, new: changes.append((old, new))
        sm.enter_generating()
        sm.enter_idle()
        assert changes == [("idle", "generating"), ("generating", "idle")]

    def test_no_delegate_no_error(self):
        sm = StateManager()
        sm.on_state_changed = None
        sm.enter_generating()  # should not raise


class TestReceiveUnexpected:
    def test_receive_unexpected_returns_interrupt_message(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        item = InquiryInterruptItem(event={"type": "agent.event.inquiry.request", "inquiry_id": "inq1"})
        msg = sm.receive_unexpected(item)
        assert "INTERRUPTED" in msg
        assert "receive_incoming_inquiry" in msg

    def test_receive_unexpected_sets_current_interrupt(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        item = InquiryInterruptItem(event={"type": "agent.event.inquiry.request", "inquiry_id": "inq1"})
        sm.receive_unexpected(item)
        assert sm.current_interrupt is item

    def test_receive_unexpected_preserves_pending_wait(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        item = InquiryInterruptItem(event={"type": "agent.event.inquiry.request", "inquiry_id": "inq1"})
        sm.receive_unexpected(item)
        assert sm.pending_wait is not None
        assert sm.pending_wait.request_id == "req1"

    def test_receive_unexpected_transitions_to_generating(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        item = InquiryInterruptItem(event={"type": "agent.event.inquiry.request", "inquiry_id": "inq1"})
        sm.receive_unexpected(item)
        assert sm.current_state == "generating"

    def test_receive_unexpected_fires_delegate(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        changes = []
        sm.on_state_changed = lambda old, new: changes.append((old, new))
        item = InquiryInterruptItem(event={"type": "agent.event.inquiry.request"})
        sm.receive_unexpected(item)
        assert ("waiting_for_agent", "generating") in changes

    def test_exit_waiting_after_interrupt_clears_interrupt(self):
        sm = StateManager()
        sm.enter_generating()
        sm.enter_waiting_for_agent("req1", "agent_b")
        item = InquiryInterruptItem(event={"type": "agent.event.inquiry.request"})
        sm.receive_unexpected(item)
        # Re-enter waiting (simulates continue_waiting resuming)
        sm.enter_waiting_for_agent("req1", "agent_b")
        sm.exit_waiting("req1")
        assert sm.current_interrupt is None
