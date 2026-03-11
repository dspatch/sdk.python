# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Shared data types used across the SDK."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Message:
    """A single conversation message."""

    id: str
    role: str
    content: str


@dataclass
class InquiryResponse:
    """User's response to an agent inquiry."""

    text: str | None = None
    suggestion_index: int | None = None


@dataclass
class ForwardedInquiry:
    """An inquiry forwarded from a sub-agent."""

    inquiry_id: str
    from_agent_id: str
    content_markdown: str
    suggestions: list[dict] | None = None
    priority: str = "normal"


class InquiryDecision:
    """Base class for inquiry forwarding decisions."""

    pass


@dataclass
class RespondDecision(InquiryDecision):
    """Respond to the inquiry with text."""

    text: str


@dataclass
class RespondSuggestionDecision(InquiryDecision):
    """Respond with a selected suggestion index."""

    suggestion_index: int


class BubbleDecision(InquiryDecision):
    """Bubble the inquiry up to the next supervisor."""

    pass


@dataclass
class TalkToResponse:
    """Response from a talk_to request to another agent."""

    response: str | None = None
    error: str | None = None


@dataclass
class PendingWait:
    """Tracks what a blocked tool call is waiting for."""

    wait_type: str  # "talk_to" or "inquiry"
    request_id: str
    peer: str | None = None
