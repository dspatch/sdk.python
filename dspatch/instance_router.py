# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""AgentInstanceRouter — application-level router for a single agent instance.

Owns:
- Inbound routing: classifies events, routes to feed based on StateManager state
- Buffer: holds events that cannot be delivered yet; flushes on state change
- Turn ID stack: push on new input/interrupt, pop when sub-turn ends
- Outbound tagging: injects turn_id on output packages and response event packages
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from .dispatcher import (
    FeedItem, InputItem, ResponseItem, InquiryInterruptItem, TerminationItem,
)
from .state_manager import StateManager

# Event type classification.
_RESPONSE_EVENTS = frozenset({"agent.event.talk_to.response", "agent.event.inquiry.response"})
_INQUIRY_EVENTS = frozenset({"agent.event.inquiry.request"})
_TERMINATION_EVENTS = frozenset({"agent.event.request.failed", "agent.event.inquiry.failed"})
_CONTROL_EVENTS = frozenset({"agent.signal.state_query", "agent.signal.terminate", "agent.signal.drain", "agent.signal.interrupt"})
_KEEPALIVE_EVENTS = frozenset({"agent.event.request.alive", "agent.event.inquiry.alive"})


_OUTPUT_PREFIX = "agent.output."
_RESPONSE_OUTBOUND = frozenset({
    "agent.event.talk_to.response",
    "agent.event.inquiry.response",
})


class AgentInstanceRouter:
    """Routes inbound events to the feed based on agent state.

    Observes StateManager via on_state_changed delegate.
    Manages turn ID stack for nested sub-turns (interrupts).
    Tags outbound output packages and response event packages with turn_id.
    """

    def __init__(self, state_manager: StateManager) -> None:
        self._sm = state_manager
        self.feed: asyncio.Queue[FeedItem] = asyncio.Queue()
        self._buffer: list[FeedItem] = []
        self._turn_stack: list[str] = []

        # Callbacks for control/keepalive events (never queued).
        self.on_control: Callable[[dict], None] | None = None
        self.on_keepalive: Callable[[dict], None] | None = None

        # Subscribe to StateManager state changes.
        self._sm.on_state_changed = self._on_state_changed

    # ── Turn ID stack ────────────────────────────────────────────────────

    @property
    def current_turn_id(self) -> str | None:
        return self._turn_stack[-1] if self._turn_stack else None

    def push_turn(self, turn_id: str | None = None) -> str:
        """Push a new turn ID (auto-generate if not provided). Returns the new ID."""
        tid = turn_id or uuid.uuid4().hex[:12]
        self._turn_stack.append(tid)
        return tid

    def pop_turn(self) -> str | None:
        """Pop the current turn ID and return to the previous one."""
        if self._turn_stack:
            return self._turn_stack.pop()
        return None

    # ── Outbound tagging ─────────────────────────────────────────────────

    def tag_outbound(self, event: dict) -> dict:
        """Return a copy of *event* with ``turn_id`` injected when appropriate.

        ``turn_id`` is only added to output packages (``agent.output.*``) and
        response event packages (``talk_to.response``, ``inquiry.response``).
        All other package types are returned unchanged.
        """
        if not self._turn_stack:
            return event
        etype = event.get("type", "")
        if etype.startswith(_OUTPUT_PREFIX) or etype in _RESPONSE_OUTBOUND:
            return {**event, "turn_id": self._turn_stack[-1]}
        return event

    # ── Inbound routing ──────────────────────────────────────────────────

    def receive(self, event: dict) -> None:
        """Route an incoming event based on current agent state."""
        event_type = event.get("type", "")

        if event_type in _CONTROL_EVENTS:
            if self.on_control:
                self.on_control(event)
            return

        if event_type in _KEEPALIVE_EVENTS:
            if self.on_keepalive:
                self.on_keepalive(event)
            return

        item = self._classify(event_type, event)
        state = self._sm.current_state

        if state == "idle":
            if isinstance(item, (InputItem, InquiryInterruptItem)):
                self.feed.put_nowait(item)
            else:
                self._buffer_insert(item)

        elif state == "generating":
            self._buffer_insert(item)

        elif state in ("waiting_for_agent", "waiting_for_inquiry"):
            if isinstance(item, (ResponseItem, TerminationItem, InquiryInterruptItem)):
                self.feed.put_nowait(item)
            else:
                self._buffer_insert(item)

    # ── State change observer ────────────────────────────────────────────

    def _on_state_changed(self, old_state: str, new_state: str) -> None:
        """Called by StateManager when state changes. Flush deliverable items."""
        self._flush()

    # ── Internal helpers ─────────────────────────────────────────────────

    def _classify(self, event_type: str, event: dict) -> FeedItem:
        if event_type in _RESPONSE_EVENTS:
            return ResponseItem(event=event)
        if event_type in _INQUIRY_EVENTS:
            return InquiryInterruptItem(event=event)
        if event_type in _TERMINATION_EVENTS:
            return TerminationItem(event=event)
        return InputItem(event=event)

    def _buffer_insert(self, item: FeedItem) -> None:
        """Insert into buffer maintaining priority: inquiries before inputs."""
        if isinstance(item, InquiryInterruptItem):
            for i, existing in enumerate(self._buffer):
                if isinstance(existing, InputItem):
                    self._buffer.insert(i, item)
                    return
            self._buffer.append(item)
        else:
            self._buffer.append(item)

    def _flush(self) -> None:
        """Deliver all buffered items that are appropriate for the current state."""
        remaining = []
        for item in self._buffer:
            if self._should_deliver(item):
                self.feed.put_nowait(item)
            else:
                remaining.append(item)
        self._buffer = remaining

    def _should_deliver(self, item: FeedItem) -> bool:
        state = self._sm.current_state
        if state == "idle":
            return isinstance(item, (InputItem, InquiryInterruptItem))
        if state in ("waiting_for_agent", "waiting_for_inquiry"):
            return isinstance(item, (InquiryInterruptItem, ResponseItem, TerminationItem))
        return False
