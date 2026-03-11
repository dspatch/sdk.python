# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""dspatch SDK — Python agent-to-host communication."""

__version__ = "0.1.0"

from .contexts import ClaudeAgentContext, Context, OpenAiAgentContext
from .engine import DspatchEngine
from .instance_router import AgentInstanceRouter
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
from .packages import (
    Package,
    AgentPackage,
    OutputPackage,
    EventPackage,
    ConnectionPackage,
    # Output packets
    MessagePackage,
    ActivityPackage,
    LogPackage,
    UsagePackage,
    FilesPackage,
    PromptReceivedPackage,
    # Event packets
    UserInputPackage,
    TalkToRequestPackage,
    TalkToResponsePackage,
    RequestAlivePackage,
    RequestFailedPackage,
    InquiryRequestPackage,
    InquiryResponsePackage,
    InquiryAlivePackage,
    InquiryFailedPackage,
    DrainPackage,
    TerminatePackage,
    StateQueryPackage,
    StateReportPackage,
    InstanceSpawnedPackage,
    # Connection packets
    AuthPackage,
    AuthAckPackage,
    AuthErrorPackage,
    RegisterPackage,
    HeartbeatPackage,
    SpawnInstancePackage,
    # Fallback
    UnknownPackage,
)

def __getattr__(name: str):
    if name == "AgentHostRouter":
        from .host import AgentHostRouter
        return AgentHostRouter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Models
    "AgentHostRouter",
    "AgentInstanceRouter",
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
    # Package hierarchy
    "Package",
    "AgentPackage",
    "OutputPackage",
    "EventPackage",
    "ConnectionPackage",
    "MessagePackage",
    "ActivityPackage",
    "LogPackage",
    "UsagePackage",
    "FilesPackage",
    "PromptReceivedPackage",
    "UserInputPackage",
    "TalkToRequestPackage",
    "TalkToResponsePackage",
    "RequestAlivePackage",
    "RequestFailedPackage",
    "InquiryRequestPackage",
    "InquiryResponsePackage",
    "InquiryAlivePackage",
    "InquiryFailedPackage",
    "DrainPackage",
    "TerminatePackage",
    "StateQueryPackage",
    "StateReportPackage",
    "InstanceSpawnedPackage",
    "AuthPackage",
    "AuthAckPackage",
    "AuthErrorPackage",
    "RegisterPackage",
    "HeartbeatPackage",
    "SpawnInstancePackage",
    "UnknownPackage",
]
