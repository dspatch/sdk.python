# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Feed item types for the single-feed architecture.

These types are used by AgentInstanceRouter, AgentWorker, Context, and tools
to classify and route inbound events through the feed queue.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeedItem:
    """Base class for items delivered through the feed."""
    event: dict


class ResponseItem(FeedItem):
    """A response to a blocking call (talk_to_response, inquiry_response)."""


class InquiryInterruptItem(FeedItem):
    """An incoming inquiry that can interrupt a blocked agent."""


class InputItem(FeedItem):
    """A new input for the agent (user_input, talk_to_request)."""


class TerminationItem(FeedItem):
    """A chain termination signal."""
