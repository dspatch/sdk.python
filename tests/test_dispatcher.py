# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for dispatcher feed item types."""

from dspatch.dispatcher import (
    FeedItem,
    ResponseItem,
    InquiryInterruptItem,
    InputItem,
    TerminationItem,
)
from dspatch.models import PendingWait


class TestFeedItemTypes:
    def test_response_item(self):
        item = ResponseItem(event={"type": "agent.event.talk_to.response", "request_id": "r1"})
        assert isinstance(item, FeedItem)
        assert item.event["request_id"] == "r1"

    def test_inquiry_interrupt_item(self):
        item = InquiryInterruptItem(event={"type": "agent.event.inquiry.request", "inquiry_id": "i1"})
        assert isinstance(item, FeedItem)

    def test_input_item(self):
        item = InputItem(event={"type": "agent.event.user_input", "content": "hi"})
        assert isinstance(item, FeedItem)

    def test_termination_item(self):
        item = TerminationItem(event={"type": "agent.event.request.failed", "request_id": "r1"})
        assert isinstance(item, FeedItem)


class TestPendingWait:
    def test_pending_wait_talk_to(self):
        pw = PendingWait(wait_type="talk_to", request_id="r1", peer="agent_b")
        assert pw.wait_type == "talk_to"
        assert pw.request_id == "r1"
        assert pw.peer == "agent_b"

    def test_pending_wait_inquiry(self):
        pw = PendingWait(wait_type="inquiry", request_id="inq1")
        assert pw.wait_type == "inquiry"
        assert pw.peer is None
