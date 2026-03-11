# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for inquiry bubbling support in the SDK."""

from __future__ import annotations

import pytest

from dspatch.models import (
    BubbleDecision,
    ForwardedInquiry,
    RespondDecision,
    RespondSuggestionDecision,
)


class TestForwardedInquiryModel:
    """Tests for the ForwardedInquiry dataclass."""

    def test_create_with_defaults(self):
        fwd = ForwardedInquiry(
            inquiry_id="inq-1",
            from_agent_id="coder",
            content_markdown="Help needed",
        )
        assert fwd.inquiry_id == "inq-1"
        assert fwd.from_agent_id == "coder"
        assert fwd.content_markdown == "Help needed"
        assert fwd.suggestions is None
        assert fwd.priority == "normal"

    def test_create_with_all_fields(self):
        fwd = ForwardedInquiry(
            inquiry_id="inq-2",
            from_agent_id="coder-0",
            content_markdown="Choose an option",
            suggestions=[{"text": "A"}, {"text": "B"}],
            priority="high",
        )
        assert fwd.priority == "high"
        assert len(fwd.suggestions) == 2


class TestInquiryDecisions:
    """Tests for the decision types."""

    def test_respond_decision(self):
        d = RespondDecision(text="I'll handle it")
        assert d.text == "I'll handle it"

    def test_respond_suggestion_decision(self):
        d = RespondSuggestionDecision(suggestion_index=1)
        assert d.suggestion_index == 1

    def test_bubble_decision(self):
        d = BubbleDecision()
        assert isinstance(d, BubbleDecision)


