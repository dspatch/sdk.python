# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Context — the primary interface agents use inside their handler."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TYPE_CHECKING, Literal

from ..models import InquiryResponse, Message
from ..generated import dspatch_router_pb2

if TYPE_CHECKING:
    from ..grpc_channel import GrpcChannel

logger = logging.getLogger("dspatch.context")


def _task_done_callback(task: asyncio.Task) -> None:
    """Log any unhandled exception from a fire-and-forget task."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(
            "Background task %s failed: %s", task.get_name(), exc, exc_info=exc,
        )


@dataclass
class ToolSpec:
    """Canonical definition of a dspatch platform tool.

    Returned by ``Context._dspatch_tool_specs()``.  Subclasses wrap these
    into their provider-specific format (OpenAI function defs, Claude MCP
    closures, etc.).
    """

    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _uuid7_hex() -> str:
    """Generate a UUID7 (time-ordered) as a 32-char hex string.

    UUID7 layout: 48-bit unix_ts_ms | 4-bit version(7) | 12-bit rand_a | 2-bit variant(10) | 62-bit rand_b
    """
    import time as _time
    import secrets
    ts_ms = int(_time.time() * 1000)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    uuid_int = (ts_ms & 0xFFFF_FFFF_FFFF) << 80
    uuid_int |= 0x7 << 76          # version 7
    uuid_int |= rand_a << 64
    uuid_int |= 0x2 << 62          # variant 10
    uuid_int |= rand_b
    return f"{uuid_int:032x}"


_INQUIRY_INSTRUCTIONS = """\
## Inquiries
Use the `{tool_ref}` tool to escalate significant decisions to the \
appropriate authority (a supervisor agent or the user). Only escalate when \
it matters — you have full autonomy for routine decisions.

Escalate when:
- You need to choose between multiple valid architectural approaches.
- A requirement is ambiguous and you need clarification.
- You are about to make a significant change that could affect the project's \
direction.
- You encounter an issue that requires a judgment call.

When sending an inquiry:
1. Write a clear, comprehensive markdown document explaining the situation.
2. Provide your recommended approach as the FIRST suggestion.
3. Include at least one alternative approach as additional suggestions.
4. Attach relevant code files for context.

Do NOT escalate trivial decisions you can make on your own \
(formatting, variable naming, standard patterns, etc.)."""

_INQUIRY_AUTHORITY_INSTRUCTIONS = """\
## Inquiries & Authority
Use the `{tool_ref}` tool to escalate decisions that fall outside your \
authority.

Your authority:
{authority}

Any decision outside the scope described above MUST be escalated via \
`{tool_ref}`. Decisions within your authority should be made autonomously \
without escalation.

Escalate when:
- You need to choose between multiple valid architectural approaches.
- A requirement is ambiguous and you need clarification.
- You are about to make a significant change that could affect the project's \
direction.
- You encounter an issue that requires a judgment call.

When sending an inquiry:
1. Write a clear, comprehensive markdown document explaining the situation.
2. Provide your recommended approach as the FIRST suggestion.
3. Include at least one alternative approach as additional suggestions.
4. Attach relevant code files for context.

Do NOT escalate trivial decisions you can make on your own \
(formatting, variable naming, standard patterns, etc.)."""


class Context:
    """Agent context for workspace-based agents.

    All event methods send immediately through gRPC to the container-local
    dspatch-router. Every outgoing event is tagged with ``instance_id``.
    """

    def __init__(
        self,
        channel: GrpcChannel,
        instance_id: str,
        turn_id: str,
        messages: list[Message],
    ) -> None:
        self._channel = channel
        self._instance_id = instance_id
        self._turn_id = turn_id
        self._message_sent = False
        self.messages: list[Message] = messages

        self._pending_inquiry_id: str | None = None

        # Peers/available agents from env.
        peers_str = os.environ.get("DSPATCH_PEERS", "")
        self.available_agents: list[str] = (
            [p.strip() for p in peers_str.split(",") if p.strip()]
            if peers_str
            else []
        )
        logger.info(
            "Context created: DSPATCH_PEERS=%r -> available_agents=%s",
            peers_str, self.available_agents,
        )

        # Workspace directory (project root inside the container).
        self.workspace_dir: str = os.environ.get("DSPATCH_WORKSPACE_DIR", "/workspace")

        # Maps peer_name -> last conversation_id (for continue_conversation).
        self._peer_conversations: dict[str, str] = {}

        # Shared setup fields (populated by setup()).
        self._user_system_prompt: str | None = None
        self._user_authority: str | None = None
        self._user_options: Any = None
        self.client: Any = None

    def _read_field(self, key: str) -> str | None:
        """Read a base64-encoded field from DSPATCH_FIELD_<KEY> env var.

        Returns the decoded UTF-8 string, or None if the env var is not set
        or contains invalid base64.
        """
        env_key = f"DSPATCH_FIELD_{key.upper()}"
        raw = os.environ.get(env_key)
        if raw is None:
            return None
        try:
            return base64.b64decode(raw).decode("utf-8")
        except Exception:
            logger.warning("Invalid base64 in env var %s, ignoring", env_key)
            return None

    # ── Tool name prefix (override in subclasses) ─────────────────────

    @property
    def _tool_name_prefix(self) -> str:
        """Prefix for tool names in system prompt instructions.

        Override in subclasses: returns ``""`` for plain names (OpenAI),
        ``"mcp__dspatch__"`` for MCP-qualified names (Claude).
        """
        return ""

    # ── Setup / run / context manager (override in subclasses) ────────

    def setup(self, *, system_prompt: str = "", authority: str | None = None, options: Any = None) -> None:
        """Configure the context before entering the async context manager.

        Parameters
        ----------
        system_prompt:
            The agent's base system prompt (will be augmented with dspatch
            platform instructions).  When empty, falls back to the
            ``DSPATCH_FIELD_SYSTEM_PROMPT`` env var (base64-decoded).
        authority:
            Optional freeform string defining the agent's decision boundaries.
            When not provided, falls back to the ``DSPATCH_FIELD_AUTHORITY``
            env var (base64-decoded).
        options:
            An optional options object (e.g. model name, temperature).
            Stored as ``_user_options`` for use in ``run()``.
        """
        if not system_prompt:
            system_prompt = self._read_field("system_prompt") or ""
        if authority is None:
            authority = self._read_field("authority")
        self._user_system_prompt = system_prompt
        self._user_authority = authority
        self._user_options = options

    async def run(self, prompt: str) -> str:
        """Run one turn. Override in subclasses."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement run(). "
            "Use a specialized context (ClaudeAgentContext, OpenAiAgentContext)."
        )

    async def __aenter__(self):
        if self._user_system_prompt is None:
            raise RuntimeError("Call setup() before entering the context manager.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    # ── System prompt augmentation ────────────────────────────────────────

    def _get_augmented_system_prompt(self) -> str:
        """Return the system prompt augmented with d:spatch platform instructions.

        Call ``setup()`` first — this method reads the ``system_prompt`` and
        ``authority`` you configured there and appends workspace, inquiry, and
        coordination sections automatically.
        """
        if self._user_system_prompt is None:
            raise RuntimeError("Call setup() before _get_augmented_system_prompt().")
        return self._augment_system_prompt(self._user_system_prompt)

    def _augment_system_prompt(self, user_prompt: str) -> str:
        """Augment a user-defined system prompt with dspatch platform instructions.

        Appends documentation for the inquiry and agent-coordination tools.
        Tool names are formatted using ``_tool_name_prefix`` so subclasses
        (Claude, OpenAI) get the correct naming convention automatically.
        """
        if self._tool_name_prefix:
            tool_ref = f"send_inquiry ({self._tool_name_prefix}send_inquiry)"
        else:
            tool_ref = "send_inquiry"

        sections = [user_prompt]
        sections.append(
            "## Workspace\n"
            f"Your workspace is `{self.workspace_dir}`. All code, output, artifacts, and "
            "created files MUST be placed within it — never write to paths "
            "outside the workspace."
        )
        if self._user_authority:
            sections.append(
                _INQUIRY_AUTHORITY_INSTRUCTIONS.format(
                    authority=self._user_authority, tool_ref=tool_ref,
                )
            )
        else:
            sections.append(_INQUIRY_INSTRUCTIONS.format(tool_ref=tool_ref))
        if self.available_agents:
            sections.append(self._coordination_instructions())
        return "\n\n".join(sections)

    def _coordination_instructions(self) -> str:
        agents_list = ", ".join(self.available_agents)
        tool_examples = ", ".join(
            f"{self._tool_name_prefix}talk_to_{a}" for a in self.available_agents
        )
        return (
            "## Agent Coordination\n"
            f"The following agents are available in your workspace: {agents_list}.\n"
            f"You can use the corresponding tools ({tool_examples}) to "
            "coordinate work — delegate subtasks, request reviews, or share "
            "context. Each tool sends a message and waits for the other "
            "agent's response."
        )

    # ── Tool specs & dispatch ────────────────────────────────────────────

    def _dspatch_tool_specs(self) -> list[ToolSpec]:
        """Return the canonical list of dspatch platform tools.

        Each :class:`ToolSpec` carries ``name``, ``description``, ``schema``
        **and** an async ``handler(args)`` callable.  Subclasses iterate this
        list and wrap each entry into their provider-specific format.
        """
        from ..tools import agents, inquiry

        ctx = self  # capture for closures

        async def _inquiry_handler(args: dict[str, Any]) -> dict[str, Any]:
            return await inquiry.execute(ctx, args)

        specs: list[ToolSpec] = [
            ToolSpec(inquiry.NAME, inquiry.DESCRIPTION, inquiry.SCHEMA, _inquiry_handler),
        ]

        if self.available_agents:
            for peer in self.available_agents:
                defn = agents._make_definition(peer)

                async def _talk_handler(args: dict[str, Any], _peer: str = peer) -> dict[str, Any]:
                    return await agents.execute(ctx, _peer, args)

                specs.append(ToolSpec(defn["name"], defn["description"], defn["schema"], _talk_handler))

        return specs

    async def _handle_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a tool call by name using :meth:`_dspatch_tool_specs`.

        Returns MCP-style result dict with ``"content"`` key.
        """
        for spec in self._dspatch_tool_specs():
            if spec.name == tool_name:
                return await spec.handler(arguments)
        raise KeyError(f"Unknown dspatch tool: {tool_name!r}")

    # ── Turn ID access ───────────────────────────────────────────────────

    @property
    def turn_id(self) -> str | None:
        """Current turn_id, stored directly from constructor."""
        return self._turn_id

    # ── Immediate event methods ──────────────────────────────────────────

    LogLevel = Literal["debug", "info", "warn", "error"]

    _VALID_LOG_LEVELS = {"debug", "info", "warn", "error"}

    async def message(
        self,
        content: str,
        is_delta: bool = False,
        id: str | None = None,
        role: str = "assistant",
    ) -> None:
        """Send a message via gRPC SendOutput."""
        self._message_sent = True
        await self._channel.stub.SendOutput(
            dspatch_router_pb2.OutputEvent(
                instance_id=self._instance_id,
                message=dspatch_router_pb2.MessageOutput(
                    id=id or _uuid7_hex(),
                    role=role,
                    content=content,
                    is_delta=is_delta,
                ),
            )
        )

    def log(self, message: str, level: LogLevel = "info") -> None:
        """Send a log entry immediately (fire-and-forget)."""
        if level not in self._VALID_LOG_LEVELS:
            raise ValueError(
                f"Invalid log level {level!r}, "
                f"must be one of {sorted(self._VALID_LOG_LEVELS)}"
            )
        try:
            loop = asyncio.get_running_loop()
            t = loop.create_task(
                self._channel.stub.SendOutput(
                    dspatch_router_pb2.OutputEvent(
                        instance_id=self._instance_id,
                        log=dspatch_router_pb2.LogOutput(
                            level=level,
                            message=message,
                        ),
                    )
                ),
                name="ctx-log-send",
            )
            t.add_done_callback(_task_done_callback)
        except RuntimeError:
            logger.debug("log() called with no running event loop, dropping entry")

    async def activity(
        self,
        event_type: str,
        content: str | None = None,
        is_delta: bool = False,
        id: str | None = None,
        data: dict | None = None,
    ) -> str:
        """Record an activity event via gRPC SendOutput. Returns the activity id."""
        import json
        aid = id or _uuid7_hex()
        await self._channel.stub.SendOutput(
            dspatch_router_pb2.OutputEvent(
                instance_id=self._instance_id,
                activity=dspatch_router_pb2.ActivityOutput(
                    id=aid,
                    event_type=event_type,
                    content=content or "",
                    is_delta=is_delta,
                    data=json.dumps(data) if data else "",
                ),
            )
        )
        return aid

    async def usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = 0.0,
        **kwargs: object,
    ) -> None:
        """Record token usage for an LLM call via gRPC SendOutput."""
        await self._channel.stub.SendOutput(
            dspatch_router_pb2.OutputEvent(
                instance_id=self._instance_id,
                usage=dspatch_router_pb2.UsageOutput(
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                ),
            )
        )

    async def files(self, file_list: list[dict]) -> None:
        """Record file operations via gRPC SendOutput."""
        entries = [
            dspatch_router_pb2.FileEntry(
                path=f.get("path", ""),
                action=f.get("action", ""),
            )
            for f in file_list
        ]
        await self._channel.stub.SendOutput(
            dspatch_router_pb2.OutputEvent(
                instance_id=self._instance_id,
                files=dspatch_router_pb2.FilesOutput(files=entries),
            )
        )

    async def prompt(
        self,
        content: str,
        *,
        sender_name: str | None = None,
    ) -> None:
        """Record an incoming prompt received by this agent via gRPC SendOutput."""
        await self._channel.stub.SendOutput(
            dspatch_router_pb2.OutputEvent(
                instance_id=self._instance_id,
                prompt_received=dspatch_router_pb2.PromptReceivedOutput(
                    content=content,
                    sender_name=sender_name or "",
                ),
            )
        )

    # ── Blocking RPC methods ─────────────────────────────────────────────

    async def talk_to(
        self,
        target_agent: str,
        text: str,
        *,
        continue_conversation: bool = False,
    ) -> str:
        """Talk to another agent. Single blocking gRPC call with interrupt loop.

        Returns the target agent's response text.
        """
        response = await self._channel.stub.TalkTo(
            dspatch_router_pb2.TalkToRpcRequest(
                instance_id=self._instance_id,
                target_agent=target_agent,
                text=text,
                continue_conversation=continue_conversation,
            )
        )

        while True:
            which = response.WhichOneof("result")

            if which == "success":
                conv_id = response.success.conversation_id
                if conv_id:
                    self._peer_conversations[target_agent] = conv_id
                return response.success.response

            elif which == "error":
                raise RuntimeError(response.error.reason)

            elif which == "interrupt":
                reply = await self._handle_inquiry_interrupt(response.interrupt)
                response = await self._channel.stub.ResumeTalkTo(
                    dspatch_router_pb2.ResumeTalkToRequest(
                        instance_id=self._instance_id,
                        request_id=response.interrupt.inquiry_id,
                        inquiry_response_text=reply,
                    )
                )

    async def inquire(
        self,
        content_markdown: str,
        suggestions: list[str | dict] | None = None,
        file_paths: list[str] | None = None,
        priority: str = "normal",
        timeout_hours: float | None = None,
    ) -> InquiryResponse | str:
        """Post an inquiry and block until the user responds or an interrupt arrives.

        Single blocking gRPC call with interrupt loop.
        """
        # Wire protocol: suggestions is list[string].
        suggestion_strings: list[str] | None = None
        if suggestions is not None:
            if len(suggestions) < 2:
                raise ValueError("suggestions must contain at least 2 items")
            suggestion_strings = []
            for s in suggestions:
                if isinstance(s, str):
                    suggestion_strings.append(s)
                elif isinstance(s, dict):
                    suggestion_strings.append(s.get("text", str(s)))
                else:
                    suggestion_strings.append(str(s))

        response = await self._channel.stub.Inquire(
            dspatch_router_pb2.InquireRpcRequest(
                instance_id=self._instance_id,
                content_markdown=content_markdown,
                suggestions=suggestion_strings or [],
                file_paths=file_paths or [],
                priority=priority,
            )
        )

        while True:
            which = response.WhichOneof("result")

            if which == "success":
                if response.success.response_text:
                    return response.success.response_text
                return InquiryResponse(
                    text=response.success.response_text,
                    # TODO: Proto3 scalar int defaults to 0, so index 0 is indistinguishable
                    # from "no selection". Consider using a wrapper type or sentinel value.
                    suggestion_index=response.success.suggestion_index if response.success.suggestion_index != 0 else None,
                )

            elif which == "error":
                raise RuntimeError(response.error.reason)

            elif which == "interrupt":
                reply = await self._handle_inquiry_interrupt(response.interrupt)
                response = await self._channel.stub.ResumeInquire(
                    dspatch_router_pb2.ResumeInquireRequest(
                        instance_id=self._instance_id,
                        inquiry_id=response.interrupt.inquiry_id,
                        inquiry_response_text=reply,
                    )
                )

    # ── Interrupt handling ───────────────────────────────────────────────

    async def _handle_inquiry_interrupt(
        self, interrupt: dspatch_router_pb2.InquiryInterrupt,
    ) -> str:
        """Handle an inquiry interrupt inline — run the agent's handler and return the reply text.

        For now, auto-responds with a placeholder. In the future, this could invoke the agent's
        inquiry handling logic.
        """
        # TODO: Implement proper interrupt handling (let LLM decide response)
        return f"[Auto-reply to inquiry from {interrupt.from_agent}]: Acknowledged."
