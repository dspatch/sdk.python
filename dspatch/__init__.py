# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""dspatch SDK — Python agent-to-host communication."""

__version__ = "0.1.2"

from .contexts import ClaudeAgentContext, Context, OpenAiAgentContext
from .engine import DspatchEngine
from .errors import AgentError, DspatchApiError, InquiryTimeout
from .models import (
    BubbleDecision,
    ForwardedInquiry,
    InquiryDecision,
    InquiryResponse,
    Message,
    RespondDecision,
    RespondSuggestionDecision,
    TalkToResponse,
)

__all__ = [
    "AgentError",
    "BubbleDecision",
    "ClaudeAgentContext",
    "Context",
    "DspatchApiError",
    "DspatchEngine",
    "ForwardedInquiry",
    "InquiryDecision",
    "InquiryResponse",
    "InquiryTimeout",
    "Message",
    "OpenAiAgentContext",
    "RespondDecision",
    "RespondSuggestionDecision",
    "TalkToResponse",
]
