# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Typed packet hierarchy for the dspatch wire protocol.

Every message transmitted between the Python agent SDK and the Dart server
is a ``Package`` subclass. The hierarchy encodes routing semantics directly
in the type system:

    Package
    ├── AgentPackage              — carries instance_id (the instance "address")
    │   ├── OutputPackage         — observable side-effects  (packet_type="output", + turn_id, ts)
    │   │   ├── MessagePackage
    │   │   ├── ActivityPackage
    │   │   ├── LogPackage
    │   │   ├── UsagePackage
    │   │   ├── FilesPackage
    │   │   └── PromptReceivedPackage
    │   ├── EventPackage          — conversational signalling (packet_type="event", + turn_id)
    │   │   ├── UserInputPackage
    │   │   ├── TalkToRequestPackage
    │   │   ├── TalkToResponsePackage
    │   │   ├── RequestAlivePackage
    │   │   ├── RequestFailedPackage
    │   │   ├── InquiryRequestPackage
    │   │   ├── InquiryResponsePackage
    │   │   ├── InquiryAlivePackage
    │   │   └── InquiryFailedPackage
    │   └── SignalPackage         — lifecycle control signals (packet_type="event", no turn_id)
    │       ├── DrainPackage
    │       ├── TerminatePackage
    │       ├── StateQueryPackage
    │       ├── StateReportPackage
    │       └── InstanceSpawnedPackage
    └── ConnectionPackage         — physical connection layer (no instance_id)
        ├── AuthPackage
        ├── AuthAckPackage
        ├── AuthErrorPackage
        ├── RegisterPackage
        ├── HeartbeatPackage
        └── SpawnInstancePackage

``WsClient`` serialises outbound packages via ``Package.to_dict()`` and
deserialises inbound JSON via ``Package.from_dict()``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields as dc_fields
from typing import Any, ClassVar, Literal

# ── Strong types ──────────────────────────────────────────────────────────────

LogLevel = Literal["debug", "info", "warn", "error"]

AgentState = Literal["idle", "generating", "waiting_for_agent", "waiting_for_inquiry"]

MessageRole = Literal["assistant", "user", "tool"]

InquiryPriority = Literal["normal", "high", "urgent"]

# ── Registry ──────────────────────────────────────────────────────────────────
# Populated automatically by __init_subclass__ for every leaf class that
# declares a TYPE class variable.
_REGISTRY: dict[str, type[Package]] = {}


# ── Base ──────────────────────────────────────────────────────────────────────

@dataclass
class Package:
    """Base class for all dspatch wire packets.

    Subclasses declare ``TYPE: ClassVar[str] = "wire_type"`` and are
    registered automatically. ``PACKET_TYPE`` is retained on intermediate
    classes for internal SDK routing but is **not** emitted on the wire.
    The package category is fully determined by the ``type`` prefix.
    """

    TYPE: ClassVar[str]
    PACKET_TYPE: ClassVar[str | None] = None

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a wire-format dict.

        Always emits ``type``. Skips ``None`` fields so optional wire fields
        are omitted cleanly. Non-None falsy values (``False``, ``0``, ``[]``,
        ``{}``) are always included.

        Note: ``PACKET_TYPE`` is retained as a class variable for internal SDK
        use but is no longer emitted on the wire — the hierarchical ``type``
        string (e.g. ``"agent.output.message"``) encodes the same information.
        """
        d: dict[str, Any] = {"type": self.TYPE}
        for f in dc_fields(self):
            val = getattr(self, f.name)
            if val is not None:
                d[f.name] = val
        return d

    def to_json(self) -> str:
        """Serialise to a JSON string."""
        return json.dumps(self.to_dict())

    # ── Deserialisation ──────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Package:
        """Deserialise a wire-format dict into a typed Package.

        Unknown ``type`` values produce an ``UnknownPackage`` rather than
        raising, so future protocol extensions don't crash older SDK versions.
        """
        type_str = data.get("type", "")
        klass = _REGISTRY.get(type_str)
        if klass is None:
            return UnknownPackage(unknown_type=type_str, raw=data)
        return klass._from_dict(data)

    @classmethod
    def from_json(cls, raw: str) -> Package:
        """Deserialise a JSON string into a typed Package."""
        return cls.from_dict(json.loads(raw))

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Package:
        """Subclass hook — construct an instance from a wire dict."""
        raise NotImplementedError(f"{cls.__name__}._from_dict not implemented")

    # ── Auto-registration ────────────────────────────────────────────────

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only register concrete leaf classes that define TYPE in their own
        # __dict__ (not inherited). Intermediate abstract bases are skipped.
        if "TYPE" in cls.__dict__:
            _REGISTRY[cls.__dict__["TYPE"]] = cls


# ── AgentPackage ──────────────────────────────────────────────────────────────

@dataclass
class AgentPackage(Package):
    """A packet addressed to or from a specific agent instance.

    ``instance_id`` is the instance's unique address — all routers in the
    system use it to deliver the packet to exactly the right instance.

    Note: ``turn_id`` is NOT on ``AgentPackage`` — it only exists on
    ``OutputPackage`` and ``EventPackage`` where it is semantically meaningful.
    Lifecycle signals (``SignalPackage``) carry only ``instance_id``.
    """

    instance_id: str = ""


@dataclass
class OutputPackage(AgentPackage):
    """Observable side-effect emitted by an agent instance.

    Carries ``packet_type="output"`` on the wire. Output packets are
    persisted to the database by ``CommunicationService`` and surfaced in
    the UI. ``turn_id`` scopes the output to a specific conversation turn.
    ``ts`` (epoch milliseconds) is generated by the SDK so that event
    ordering reflects generation time rather than receipt time.
    """

    PACKET_TYPE: ClassVar[str] = "output"

    turn_id: str | None = None
    ts: int | None = None  # Unix epoch milliseconds, SDK-generated.


@dataclass
class EventPackage(AgentPackage):
    """Conversational signalling event for an agent instance.

    Carries ``packet_type="event"`` on the wire. These packets drive the
    conversation state machine: routing decisions and blocking calls.
    Most event packages carry no ``turn_id``. Response packages
    (``TalkToResponsePackage``, ``InquiryResponsePackage``) include
    ``turn_id`` so the Host Router can associate the response with the
    conversation turn that produced it.
    """

    PACKET_TYPE: ClassVar[str] = "event"


@dataclass
class SignalPackage(AgentPackage):
    """Lifecycle control signal for an agent instance.

    Carries ``packet_type="event"`` on the wire but carries no ``turn_id``
    — these signals are not part of any conversation turn.
    Examples: drain, terminate, state_query, state_report.
    """

    PACKET_TYPE: ClassVar[str] = "event"


# ── Output packets ────────────────────────────────────────────────────────────

@dataclass
class MessagePackage(OutputPackage):
    """Agent sends a chat message to the session.

    When ``is_delta=True`` the ``content`` is *appended* to any existing
    message with the same ``id`` in the database.  When ``is_delta=False``
    (default) the content *replaces* the stored value (or creates a new row).
    """

    TYPE: ClassVar[str] = "agent.output.message"

    id: str | None = None          # Message ID — auto-generated UUID7 by SDK when absent.
    role: MessageRole = "assistant"
    content: str = ""
    is_delta: bool = False
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    sender_name: str | None = None  # Display name of the sending agent.

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> MessagePackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            turn_id=data.get("turn_id"),
            ts=data.get("ts"),
            id=data.get("id"),
            role=data.get("role", "assistant"),
            content=data.get("content", ""),
            is_delta=data.get("is_delta", False),
            model=data.get("model"),
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            sender_name=data.get("sender_name"),
        )


@dataclass
class ActivityPackage(OutputPackage):
    """Agent reports a tool call or other named activity.

    ``event_type`` identifies the activity (e.g. ``"tool_call"``,
    ``"thinking"``).

    When ``is_delta=True``, non-None fields are *appended* to the existing
    activity row with the same ``id``.  When ``is_delta=False`` (default),
    non-None fields *replace* the stored values (or create a new row).

    ``data`` and ``content`` are updated independently — if either is
    ``None`` the corresponding DB column is left untouched.
    """

    TYPE: ClassVar[str] = "agent.output.activity"

    id: str | None = None           # Activity ID — auto-generated UUID7 by SDK when absent.
    event_type: str = ""
    data: dict[str, Any] | None = None
    content: str | None = None
    is_delta: bool = False

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> ActivityPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            turn_id=data.get("turn_id"),
            ts=data.get("ts"),
            id=data.get("id"),
            event_type=data.get("event_type", ""),
            data=data.get("data"),
            content=data.get("content"),
            is_delta=data.get("is_delta", False),
        )


@dataclass
class LogPackage(OutputPackage):
    """Agent sends a structured log entry."""

    TYPE: ClassVar[str] = "agent.output.log"

    level: LogLevel = "info"
    message: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> LogPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            turn_id=data.get("turn_id"),
            ts=data.get("ts"),
            level=data.get("level", "info"),  # type: ignore[arg-type]
            message=data.get("message", ""),
        )


@dataclass
class UsagePackage(OutputPackage):
    """Agent reports token usage for an LLM call."""

    TYPE: ClassVar[str] = "agent.output.usage"

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: float | None = None

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> UsagePackage:
        raw_cost = data.get("cost_usd")
        return cls(
            instance_id=data.get("instance_id", ""),
            turn_id=data.get("turn_id"),
            ts=data.get("ts"),
            model=data.get("model", ""),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens"),
            cache_write_tokens=data.get("cache_write_tokens"),
            cost_usd=float(raw_cost) if raw_cost is not None else None,
        )


@dataclass
class FilesPackage(OutputPackage):
    """Agent reports file operations performed during a turn."""

    TYPE: ClassVar[str] = "agent.output.files"

    files: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> FilesPackage:
        raw = data.get("files", [])
        return cls(
            instance_id=data.get("instance_id", ""),
            turn_id=data.get("turn_id"),
            ts=data.get("ts"),
            files=[f for f in raw if isinstance(f, dict)],
        )


@dataclass
class PromptReceivedPackage(OutputPackage):
    """Agent acknowledges receipt of a prompt.

    Emitted before the agent starts generating a response, so the UI
    can show a processing indicator immediately. ``sender_name`` is set
    when the prompt originated from another agent (``talk_to`` chain).
    """

    TYPE: ClassVar[str] = "agent.output.prompt_received"

    content: str = ""
    sender_name: str | None = None

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> PromptReceivedPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            turn_id=data.get("turn_id"),
            ts=data.get("ts"),
            content=data.get("content", ""),
            sender_name=data.get("sender_name"),
        )


# ── Event packets ─────────────────────────────────────────────────────────────

@dataclass
class UserInputPackage(EventPackage):
    """User sends a message to a specific agent instance.

    Always carries an ``instance_id`` — the UI routes the message to the
    exact instance the user has open.
    """

    TYPE: ClassVar[str] = "agent.event.user_input"

    content: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> UserInputPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            content=data.get("content", ""),
        )


@dataclass
class TalkToRequestPackage(EventPackage):
    """Agent-to-agent call request.

    Caller sets ``target_agent``, ``text``, ``request_id``, and
    ``continue_conversation``. The engine resolves the right instance —
    routing to the existing chain instance, draining it and spawning a
    new one, or spawning fresh as appropriate. The Host Router relays the
    same package with only ``instance_id`` upgraded.
    """

    TYPE: ClassVar[str] = "agent.event.talk_to.request"

    request_id: str = ""
    text: str = ""
    target_agent: str | None = None
    caller_agent: str | None = None
    continue_conversation: bool = False  # Agent intent: reuse existing chain instance or start fresh.

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> TalkToRequestPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            request_id=data.get("request_id", ""),
            text=data.get("text", ""),
            target_agent=data.get("target_agent"),
            caller_agent=data.get("caller_agent"),
            continue_conversation=data.get("continue_conversation", False),
        )


@dataclass
class TalkToResponsePackage(EventPackage):
    """Response to a ``talk_to`` request.

    Sent by the target agent instance when it finishes processing.
    Relayed by the engine back to the caller's ``instance_id``.
    ``turn_id`` identifies the target instance's turn so the Host Router
    can assemble the transcript of what the target produced.
    """

    TYPE: ClassVar[str] = "agent.event.talk_to.response"

    request_id: str = ""
    turn_id: str | None = None
    response: str | None = None
    error: str | None = None           # Set when the call failed.

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> TalkToResponsePackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            turn_id=data.get("turn_id"),
            request_id=data.get("request_id", ""),
            response=data.get("response"),
            error=data.get("error"),
        )


@dataclass
class RequestAlivePackage(EventPackage):
    """Chain-alive heartbeat for an active ``talk_to`` request.

    Sent by the engine to the *caller* instance while it is blocked
    waiting for the target agent to respond. If the caller stops
    receiving these, it assumes the chain is dead and unblocks with
    an error.
    """

    TYPE: ClassVar[str] = "agent.event.request.alive"

    request_id: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> RequestAlivePackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            request_id=data.get("request_id", ""),
        )


@dataclass
class RequestFailedPackage(EventPackage):
    """Talk-to chain terminated — the target agent is gone.

    Sent by the engine to the *caller* instance so it can unblock
    immediately without waiting for the watchdog timeout.
    """

    TYPE: ClassVar[str] = "agent.event.request.failed"

    request_id: str = ""
    reason: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> RequestFailedPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            request_id=data.get("request_id", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class InquiryRequestPackage(EventPackage):
    """Agent creates an inquiry that requires a human response.

    ``inquiry_id`` is generated by the agent and echoed back in
    ``InquiryResponsePackage`` so the waiting agent can validate
    that the response matches its pending inquiry.
    ``suggestions`` is a list of plain strings (2–4 items).
    """

    TYPE: ClassVar[str] = "agent.event.inquiry.request"

    inquiry_id: str = ""
    content_markdown: str = ""
    priority: InquiryPriority = "normal"
    suggestions: list[str] = field(default_factory=list)
    file_paths: list[str] | None = None

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> InquiryRequestPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            inquiry_id=data.get("inquiry_id", ""),
            content_markdown=data.get("content_markdown", ""),
            priority=data.get("priority", "normal"),
            suggestions=data.get("suggestions", []),
            file_paths=data.get("file_paths"),
        )


@dataclass
class InquiryResponsePackage(EventPackage):
    """Response to a pending inquiry.

    Sent by the supervisor agent instance (or injected by the Host Router
    when a human answers). Relayed to the waiting agent instance.
    ``turn_id`` identifies the supervisor's turn so the Host Router can
    associate the response with the turn that produced it.
    ``inquiry_id`` lets the agent validate the response matches its
    pending inquiry.
    """

    TYPE: ClassVar[str] = "agent.event.inquiry.response"

    inquiry_id: str = ""
    turn_id: str | None = None
    response_text: str | None = None
    response_suggestion_index: int | None = None

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> InquiryResponsePackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            inquiry_id=data.get("inquiry_id", ""),
            turn_id=data.get("turn_id"),
            response_text=data.get("response_text"),
            response_suggestion_index=data.get("response_suggestion_index"),
        )


@dataclass
class InquiryAlivePackage(EventPackage):
    """Liveness heartbeat for a pending inquiry.

    Symmetric to ``RequestAlivePackage`` for the inquiry flow. Sent by
    the engine to the waiting agent instance while the inquiry is still
    open (user hasn't responded yet). Lets the agent distinguish a dead
    connection from a slow user.
    """

    TYPE: ClassVar[str] = "agent.event.inquiry.alive"

    inquiry_id: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> InquiryAlivePackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            inquiry_id=data.get("inquiry_id", ""),
        )


@dataclass
class InquiryFailedPackage(EventPackage):
    """Inquiry cancelled or expired before the user responded.

    Symmetric to ``RequestFailedPackage`` for the inquiry flow. Sent by
    the engine to the waiting agent instance so it can unblock
    immediately.
    """

    TYPE: ClassVar[str] = "agent.event.inquiry.failed"

    inquiry_id: str = ""
    reason: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> InquiryFailedPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            inquiry_id=data.get("inquiry_id", ""),
            reason=data.get("reason", ""),
        )


# ── Signal packets ────────────────────────────────────────────────────────────

@dataclass
class DrainPackage(SignalPackage):
    """Engine requests graceful shutdown of this agent instance.

    The instance should finish the current turn then stop. Always
    instance-scoped — the engine sends one per instance.
    """

    TYPE: ClassVar[str] = "agent.signal.drain"

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> DrainPackage:
        return cls(instance_id=data.get("instance_id", ""))


@dataclass
class TerminatePackage(SignalPackage):
    """Engine requests immediate hard-stop of this agent instance.

    The instance task should be cancelled without waiting for the
    current turn to complete. Always instance-scoped.
    """

    TYPE: ClassVar[str] = "agent.signal.terminate"

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> TerminatePackage:
        return cls(instance_id=data.get("instance_id", ""))


@dataclass
class InterruptPackage(SignalPackage):
    """Engine requests interruption of the current generation.

    Unlike drain/terminate, the instance stays alive and transitions
    back to idle — ready for new input. Used for "stop generating".
    """

    TYPE: ClassVar[str] = "agent.signal.interrupt"

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> InterruptPackage:
        return cls(instance_id=data.get("instance_id", ""))


@dataclass
class StateQueryPackage(SignalPackage):
    """Engine requests the current state of this agent instance.

    No ``request_id`` needed — ``instance_id`` is the implicit correlation
    key. The engine queries instance X and the report from instance X is
    the answer.
    """

    TYPE: ClassVar[str] = "agent.signal.state_query"

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> StateQueryPackage:
        return cls(instance_id=data.get("instance_id", ""))


@dataclass
class StateReportPackage(SignalPackage):
    """Agent reports its current state — response to ``StateQueryPackage``.

    ``state`` is the instance's current ``AgentState``.
    ``instances`` carries the full host-level state map when the engine
    queries all instances at once (keyed by instance_id).
    """

    TYPE: ClassVar[str] = "agent.signal.state_report"

    state: AgentState = "idle"
    instances: dict[str, AgentState] | None = None  # host-level report: instance_id → state.

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> StateReportPackage:
        return cls(
            instance_id=data.get("instance_id", ""),
            state=data.get("state", "idle"),  # type: ignore[arg-type]
            instances=data.get("instances"),
        )


@dataclass
class InstanceSpawnedPackage(SignalPackage):
    """Agent host confirms a new instance has been successfully spawned.

    ``instance_id`` is the ID of the newly spawned instance. Sent as an
    explicit ack after processing a ``SpawnInstancePackage``; the engine
    also uses heartbeat diffing as the authoritative source.
    """

    TYPE: ClassVar[str] = "agent.signal.instance_spawned"

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> InstanceSpawnedPackage:
        return cls(instance_id=data.get("instance_id", ""))


# ── Connection packets ────────────────────────────────────────────────────────

@dataclass
class ConnectionPackage(Package):
    """Physical connection-layer packet — no instance_id.

    These packets manage the WebSocket connection itself: auth handshake,
    agent registration, and heartbeat. They are handled by
    ``ConnectionService`` before any event routing occurs.
    """


@dataclass
class AuthPackage(ConnectionPackage):
    """First message on a new WebSocket connection — authenticate.

    Must be sent before any other packet. The server closes the connection
    if auth is not received within 10 seconds.
    """

    TYPE: ClassVar[str] = "connection.auth"

    api_key: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> AuthPackage:
        return cls(api_key=data.get("api_key", ""))


@dataclass
class AuthAckPackage(ConnectionPackage):
    """Server acknowledges successful authentication."""

    TYPE: ClassVar[str] = "connection.auth_ack"

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> AuthAckPackage:
        return cls()


@dataclass
class AuthErrorPackage(ConnectionPackage):
    """Server rejects authentication — connection will be closed."""

    TYPE: ClassVar[str] = "connection.auth_error"

    message: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> AuthErrorPackage:
        return cls(message=data.get("message", ""))


@dataclass
class RegisterPackage(ConnectionPackage):
    """Agent announces its identity after successful authentication.

    ``name`` is the agent key (e.g. ``"lead"``, ``"coder"``).
    ``role`` is currently ``"host"`` for all SDK agents.
    ``capabilities`` is reserved for future feature negotiation.
    """

    TYPE: ClassVar[str] = "connection.register"

    name: str = ""
    role: str | None = None
    capabilities: list[str] | None = None

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> RegisterPackage:
        return cls(
            name=data.get("name", ""),
            role=data.get("role"),
            capabilities=data.get("capabilities"),
        )


@dataclass
class HeartbeatPackage(ConnectionPackage):
    """Periodic liveness signal from the agent host.

    ``instances`` maps each live instance ID to its current ``AgentState``
    (e.g. ``{"abc123": "idle", "def456": "generating"}``).
    ``ConnectionService`` diffs successive heartbeats to detect instance
    creation and destruction.
    """

    TYPE: ClassVar[str] = "connection.heartbeat"

    instances: dict[str, AgentState] = field(default_factory=dict)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> HeartbeatPackage:
        raw = data.get("instances", {})
        return cls(
            instances={k: v for k, v in raw.items()  # type: ignore[misc]
                       if isinstance(k, str) and isinstance(v, str)},
        )


@dataclass
class SpawnInstancePackage(ConnectionPackage):
    """Engine requests a new agent instance — before that instance exists.

    Lives under ``ConnectionPackage`` because it creates a new connection
    entity (the instance) rather than addressing an existing one.
    Only ``instance_id`` is carried — all talk_to context is delivered
    separately via ``TalkToRequestPackage`` after the instance is spawned.
    """

    TYPE: ClassVar[str] = "connection.spawn_instance"

    instance_id: str = ""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> SpawnInstancePackage:
        return cls(
            instance_id=data.get("instance_id", ""),
        )


# ── Unknown fallback ──────────────────────────────────────────────────────────

@dataclass
class UnknownPackage:
    """Fallback for unrecognised wire types.

    Not registered in the registry — produced only by ``Package.from_dict``
    when no concrete class matches the ``type`` field. Preserved as-is so
    newer protocol versions don't crash older SDK versions.
    """

    unknown_type: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return self.unknown_type

    def to_dict(self) -> dict[str, Any]:
        return self.raw

    def to_json(self) -> str:
        return json.dumps(self.raw)
