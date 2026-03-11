# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""StateManager — single owner of agent instance state.

Tools call enter_*/exit_waiting to drive state.
AgentInstanceRouter observes via on_state_changed delegate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dispatcher import FeedItem

from .models import PendingWait


class InvalidStateTransition(Exception):
    """Raised when an illegal state transition is attempted."""


# Valid transitions via public enter_* methods.
# exit_waiting and receive_unexpected bypass these guards (they use _set_state directly).
_VALID = {
    "idle":               {"generating"},
    "generating":         {"idle", "waiting_for_agent", "waiting_for_inquiry"},
    "waiting_for_agent":  set(),
    "waiting_for_inquiry": set(),
}


class StateManager:
    """Single source of truth for agent instance state.

    Only tools and the agent worker call enter_*/exit_waiting.
    AgentInstanceRouter observes via on_state_changed.
    """

    def __init__(self) -> None:
        self._state: str = "idle"
        self._pending_wait: PendingWait | None = None
        self._current_interrupt: FeedItem | None = None
        self.on_state_changed: Callable[[str, str], None] | None = None

    # ── Observable properties ────────────────────────────────────────────

    @property
    def current_state(self) -> str:
        return self._state

    @property
    def pending_wait(self) -> PendingWait | None:
        return self._pending_wait

    @property
    def current_interrupt(self) -> FeedItem | None:
        return self._current_interrupt

    # ── State entry methods (called by tools / AgentWorker) ──────────────

    def enter_generating(self) -> None:
        self._transition("generating")

    def enter_idle(self) -> None:
        self._transition("idle")

    def enter_waiting_for_agent(self, request_id: str, peer: str) -> None:
        self._transition("waiting_for_agent")
        self._pending_wait = PendingWait(
            wait_type="talk_to", request_id=request_id, peer=peer,
        )

    def enter_waiting_for_inquiry(self, inquiry_id: str) -> None:
        self._transition("waiting_for_inquiry")
        self._pending_wait = PendingWait(
            wait_type="inquiry", request_id=inquiry_id,
        )

    # ── Wait resolution methods ──────────────────────────────────────────

    def exit_waiting(self, consumed_request_id: str) -> None:
        """Called when a tool receives what it was waiting for.

        Validates the request_id, clears pending state, transitions to generating.
        Raises ValueError if the request_id doesn't match the pending wait.
        Raises InvalidStateTransition if not currently in a wait state.
        """
        if self._state not in ("waiting_for_agent", "waiting_for_inquiry"):
            raise InvalidStateTransition(
                f"exit_waiting called in state {self._state!r}"
            )
        pending = self._pending_wait
        if pending is None or pending.request_id != consumed_request_id:
            raise ValueError(
                f"No pending wait for {consumed_request_id!r} "
                f"(pending: {pending.request_id if pending else None!r})"
            )
        self._pending_wait = None
        self._current_interrupt = None
        self._set_state("generating")

    def receive_unexpected(self, item: FeedItem) -> str:
        """Called when a tool receives an unexpected item during a wait.

        Preserves pending_wait (so continue_waiting can resume later).
        Sets current_interrupt. Transitions to generating for the sub-turn.
        Returns the interrupt message string the tool should return.
        """
        if self._state not in ("waiting_for_agent", "waiting_for_inquiry"):
            raise InvalidStateTransition(
                f"receive_unexpected called in state {self._state!r}"
            )
        self._current_interrupt = item
        # pending_wait is intentionally NOT cleared — preserved for continue_waiting.
        self._set_state("generating")
        return (
            "INTERRUPTED: An incoming inquiry requires your attention. "
            "Call receive_incoming_inquiry immediately to handle it."
        )

    # ── Internal ─────────────────────────────────────────────────────────

    def _transition(self, new_state: str) -> None:
        """Guard-checked transition — used by public enter_* methods."""
        allowed = _VALID.get(self._state, set())
        if new_state not in allowed:
            raise InvalidStateTransition(
                f"Cannot transition {self._state!r} → {new_state!r}. "
                f"Allowed: {sorted(allowed)}"
            )
        self._set_state(new_state)

    def _set_state(self, new_state: str) -> None:
        """Unconditional state change — fires delegate. Used internally by exit_waiting/receive_unexpected."""
        old = self._state
        self._state = new_state
        if self.on_state_changed is not None:
            self.on_state_changed(old, new_state)
