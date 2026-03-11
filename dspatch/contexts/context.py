# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Context — the primary interface agents use inside their handler."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TYPE_CHECKING, Literal

from ..dispatcher import FeedItem, InquiryInterruptItem
from ..models import InquiryResponse, Message

if TYPE_CHECKING:
    from ..agent_worker import AgentWorker  # noqa: F401

logger = logging.getLogger("dspatch.context")


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


_CHAIN_ALIVE_TIMEOUT = 90  # 3x the 30s app heartbeat interval
_CHAIN_WATCHDOG_CHECK = 15  # check frequency in seconds

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

    All event methods send immediately through the host connection.
    Every outgoing event is tagged with ``instance_id`` and ``turn_id``
    by the ``AgentWorker._send_event()`` helper.
    """

    def __init__(
        self,
        host: object,
        runner: object,
        messages: list[Message] | None = None,
        instance_id: str | None = None,
    ) -> None:
        self._host = host
        self._runner = runner
        self._message_sent = False
        self.messages: list[Message] = messages or []

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

        # Instance identity.
        self._instance_id: str | None = instance_id

        # Chain liveness tracking for talk_to requests.
        self._talk_to_chain_dead: dict[str, asyncio.Event] = {}
        self._request_alive_timestamps: dict[str, float] = {}

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
            "\n\n"
            "**Interruptions:** While waiting for an agent's response, you may "
            "receive an inquiry interruption. If a tool returns an INTERRUPTED "
            "message, immediately call receive_incoming_inquiry, handle the "
            "inquiry with reply_to_inquiry, then call "
            "continue_waiting_for_agent_response to resume."
        )

    # ── Tool specs & dispatch ────────────────────────────────────────────

    def _dspatch_tool_specs(self) -> list[ToolSpec]:
        """Return the canonical list of dspatch platform tools.

        Each :class:`ToolSpec` carries ``name``, ``description``, ``schema``
        **and** an async ``handler(args)`` callable.  Subclasses iterate this
        list and wrap each entry into their provider-specific format.
        """
        from ..tools import agents, inquiry, inquiry_interrupt, receive_inquiry, continue_waiting

        ctx = self  # capture for closures

        async def _inquiry_handler(args: dict[str, Any]) -> dict[str, Any]:
            return await inquiry.execute(ctx, args)

        async def _reply_handler(args: dict[str, Any]) -> dict[str, Any]:
            return await inquiry_interrupt.execute_reply(
                ctx, args, ctx._pending_inquiry_id,
            )

        async def _receive_handler(_args: dict[str, Any]) -> dict[str, Any]:
            return await receive_inquiry.execute(ctx)

        async def _continue_handler(_args: dict[str, Any]) -> dict[str, Any]:
            return await continue_waiting.execute(ctx)

        specs: list[ToolSpec] = [
            ToolSpec(inquiry.NAME, inquiry.DESCRIPTION, inquiry.SCHEMA, _inquiry_handler),
            ToolSpec(inquiry_interrupt.REPLY_NAME, inquiry_interrupt.REPLY_DESCRIPTION, inquiry_interrupt.REPLY_SCHEMA, _reply_handler),
            ToolSpec(receive_inquiry.NAME, receive_inquiry.DESCRIPTION, receive_inquiry.SCHEMA, _receive_handler),
            ToolSpec(continue_waiting.NAME, continue_waiting.DESCRIPTION, continue_waiting.SCHEMA, _continue_handler),
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
        """Current turn_id, delegated through runner._router.current_turn_id.

        Returns None if the runner has no _router or the stack is empty.
        """
        router = getattr(self._runner, '_router', None)
        if router is not None:
            return getattr(router, 'current_turn_id', None)
        return None

    # ── Immediate event methods ──────────────────────────────────────────

    LogLevel = Literal["debug", "info", "warn", "error"]

    _VALID_LOG_LEVELS = {"debug", "info", "warn", "error"}

    def log(self, message: str, level: LogLevel = "info") -> None:
        """Send a log entry immediately."""
        if level not in self._VALID_LOG_LEVELS:
            raise ValueError(
                f"Invalid log level {level!r}, "
                f"must be one of {sorted(self._VALID_LOG_LEVELS)}"
            )
        # Fire-and-forget: schedule the coroutine on the running loop.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._runner._send_event({
                "type": "agent.output.log",
                "level": level,
                "message": message,
            }))
        except RuntimeError:
            pass  # No event loop — drop silently.

    async def activity(
        self,
        event_type: str,
        content: str | None = None,
        is_delta: bool = False,
        id: str | None = None,
        data: dict | None = None,
    ) -> str:
        """Record an activity event. Returns the activity id.

        Args:
            event_type: Categorises the activity (e.g. ``"tool_call"``,
                ``"thinking"``).
            content: Optional text content.  When ``is_delta=True``,
                appended to the existing row; when ``False``, replaces it.
                ``None`` leaves the DB column untouched.
            is_delta: If ``True``, non-None fields are *appended* to the
                existing activity with the same ``id``.
            id: Identifies the exact activity row.  When ``None`` a new
                UUID7 is generated automatically.
            data: Optional structured metadata dict.  Follows the same
                delta/replace semantics as ``content``.
        """
        return await self._runner._send_activity(
            event_type,
            content=content,
            is_delta=is_delta,
            activity_id=id,
            data=data,
        )

    async def usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = 0.0,
        **kwargs: object,
    ) -> None:
        """Record token usage for an LLM call. Sends immediately."""
        await self._runner._send_event({
            "type": "agent.output.usage",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            **kwargs,
        })

    async def files(self, file_list: list[dict]) -> None:
        """Record file operations. Sends immediately."""
        await self._runner._send_event({
            "type": "agent.output.files",
            "files": file_list,
        })

    # ── Direct (blocking) ────────────────────────────────────────────────

    async def prompt(
        self,
        content: str,
        *,
        sender_name: str | None = None,
    ) -> None:
        """Record an incoming prompt received by this agent.

        Use this to log prompts the agent receives (from users, other agents,
        or injected inquiries) separately from the agent's own output messages.
        Sends an ``agent.output.prompt_received`` package.
        """
        await self._runner._send_prompt_received(content, sender_name=sender_name)

    async def message(
        self,
        content: str,
        is_delta: bool = False,
        id: str | None = None,
        role: str = "assistant",
        **kwargs: object,
    ) -> str:
        """Send a message immediately. Returns the message id.

        Args:
            content: The message text.
            is_delta: If ``True``, *append* content to the existing message
                with the same ``id`` in the database.  If ``False`` (default),
                *replace* the stored content (or create a new row).
            id: Identifies the exact message.  When ``None`` a new UUID7 is
                generated automatically.
            role: Message role (``"assistant"``, ``"user"``, ``"tool"``).
        """
        self._message_sent = True
        return await self._runner._send_message(
            content, role=role, message_id=id,
            is_delta=is_delta, **kwargs,
        )

    async def inquire(
        self,
        content_markdown: str,
        suggestions: list[str | dict] | None = None,
        file_paths: list[str] | None = None,
        priority: str = "normal",
        timeout_hours: float = 72,
    ) -> InquiryResponse | str:
        """Post an inquiry and block until the user responds or an interrupt arrives.

        Returns InquiryResponse on success, or an interrupt message string.
        """
        from ..dispatcher import ResponseItem, InquiryInterruptItem, TerminationItem

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

        inquiry_id = _uuid7_hex()
        self._pending_inquiry_id = inquiry_id

        # Emit a dedicated inquiry.request activity so the app can render
        # the inquiry card inline in the timeline.
        await self.activity(
            "inquiry.request",
            data={
                "inquiry_id": inquiry_id,
                "priority": priority,
            },
        )

        event: dict = {
            "type": "agent.event.inquiry.request",
            "content_markdown": content_markdown,
            "priority": priority,
            "inquiry_id": inquiry_id,
        }
        if suggestion_strings is not None:
            event["suggestions"] = suggestion_strings
        if file_paths is not None:
            event["file_paths"] = file_paths
        await self._runner._send_event(event)

        # Enter waiting state — StateManager now owns pending_wait.
        self._runner._sm.enter_waiting_for_inquiry(inquiry_id)

        item = await self._await_feed(expected_request_id=inquiry_id)

        if isinstance(item, InquiryInterruptItem):
            return self._runner._sm.receive_unexpected(item)

        if isinstance(item, TerminationItem):
            self._runner._sm.exit_waiting(inquiry_id)
            self._pending_inquiry_id = None
            reason = item.event.get("reason", "Inquiry failed")
            raise RuntimeError(f"Inquiry failed: {reason}")

        # ResponseItem — extract the InquiryResponse.
        self._runner._sm.exit_waiting(inquiry_id)
        self._pending_inquiry_id = None

        resp_event = item.event
        response = InquiryResponse(
            text=resp_event.get("response_text"),
            suggestion_index=resp_event.get("response_suggestion_index"),
        )

        await self.activity(
            "inquiry.response",
            data={
                "inquiry_id": inquiry_id,
                "response_text": response.text,
                "suggestion_index": response.suggestion_index,
            },
        )

        return response

    async def talk_to(
        self,
        target_agent: str,
        text: str,
        *,
        continue_conversation: bool = False,
    ) -> str:
        """Talk to another agent. Blocks until they respond or an interrupt arrives.

        Returns the target agent's response text, or an interrupt message string
        if an inquiry interrupts the wait.
        """
        from ..dispatcher import ResponseItem, InquiryInterruptItem, TerminationItem

        request_id = _uuid7_hex()

        # Emit talk_to.request activity before sending.
        await self.activity(
            "talk_to.request",
            data={
                "request_id": request_id,
                "target_agent": target_agent,
                "text": text,
                "continue_conversation": continue_conversation,
            },
        )

        # Get conversation_id for continuation.
        conversation_id = None
        if continue_conversation:
            conversation_id = self._peer_conversations.get(target_agent)

        # Send request.
        talk_event: dict = {
            "type": "agent.event.talk_to.request",
            "target_agent": target_agent,
            "text": text,
            "request_id": request_id,
            "continue_conversation": continue_conversation,
        }
        if conversation_id is not None:
            talk_event["conversation_id"] = conversation_id
        await self._runner._send_event(talk_event)

        # Enter waiting state — StateManager now owns pending_wait.
        self._runner._sm.enter_waiting_for_agent(request_id, target_agent)

        # Chain liveness tracking.
        chain_dead = asyncio.Event()
        self._talk_to_chain_dead[request_id] = chain_dead
        loop = asyncio.get_running_loop()
        self._request_alive_timestamps[request_id] = loop.time()
        watchdog = asyncio.create_task(self._chain_watchdog(request_id))

        try:
            item = await self._await_feed(
                expected_request_id=request_id,
                cancel_event=chain_dead,
            )
        finally:
            watchdog.cancel()
            try:
                await watchdog
            except asyncio.CancelledError:
                pass
            self._talk_to_chain_dead.pop(request_id, None)
            self._request_alive_timestamps.pop(request_id, None)

        if isinstance(item, InquiryInterruptItem):
            # StateManager preserves pending_wait and transitions to generating.
            return self._runner._sm.receive_unexpected(item)

        if isinstance(item, TerminationItem):
            self._runner._sm.exit_waiting(request_id)
            reason = item.event.get("reason", "")
            detail = reason if reason else "The target agent is no longer alive."
            raise RuntimeError(
                f'talk_to("{target_agent}") failed: {detail}'
            )

        # ResponseItem — success.
        self._runner._sm.exit_waiting(request_id)
        response = item.event

        error = response.get("error")
        if error:
            raise RuntimeError(f"talk_to failed: {error}")

        conv_id = response.get("conversation_id")
        if conv_id:
            self._peer_conversations[target_agent] = conv_id

        response_text = response.get("response", "")

        await self.activity(
            "talk_to.response",
            data={
                "request_id": request_id,
                "target_agent": target_agent,
                "response": response_text,
            },
        )

        return response_text

    # ── Feed loop (shared blocking primitive) ──────────────────────────────

    async def _await_feed(
        self,
        expected_request_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> FeedItem:
        """Consume from router feed until we get the expected response or interrupt.

        Callers MUST call sm.enter_waiting_for_agent/inquiry() before this.
        If *cancel_event* is set while waiting, raises ``RuntimeError``.
        Returns the FeedItem that resolved the wait.
        """
        from ..dispatcher import ResponseItem, TerminationItem

        router = self._runner._router
        while True:
            # Race the feed against an optional cancel signal (chain watchdog).
            feed_task = asyncio.ensure_future(router.feed.get())
            try:
                if cancel_event is not None:
                    cancel_task = asyncio.ensure_future(cancel_event.wait())
                    done, pending = await asyncio.wait(
                        {feed_task, cancel_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for p in pending:
                        p.cancel()
                    if cancel_task in done:
                        raise RuntimeError(
                            "Chain alive timeout — the conversation chain "
                            "appears to be dead."
                        )
                    item = feed_task.result()
                else:
                    item = await feed_task
            except asyncio.CancelledError:
                feed_task.cancel()
                raise

            if isinstance(item, ResponseItem):
                if expected_request_id:
                    # Match by request_id (talk_to) or inquiry_id (inquire).
                    item_id = item.event.get("request_id") or item.event.get("inquiry_id")
                    if item_id != expected_request_id:
                        router._buffer_insert(item)
                        continue
                return item

            if isinstance(item, InquiryInterruptItem):
                return item

            if isinstance(item, TerminationItem):
                return item

    # ── Internal (called by runner) ───────────────────────────────────────

    def _record_request_alive(self, request_id: str) -> None:
        """Record a request_alive heartbeat for a pending talk_to request."""
        if request_id in self._talk_to_chain_dead:
            self._request_alive_timestamps[request_id] = (
                asyncio.get_running_loop().time()
            )

    async def _chain_watchdog(self, request_id: str) -> None:
        """Background task: signal chain death if heartbeats stop arriving."""
        try:
            while True:
                await asyncio.sleep(_CHAIN_WATCHDOG_CHECK)
                last = self._request_alive_timestamps.get(request_id)
                if last is None:
                    return  # Request completed, no longer tracking.
                elapsed = asyncio.get_running_loop().time() - last
                if elapsed > _CHAIN_ALIVE_TIMEOUT:
                    logger.warning(
                        "Chain alive timeout for request %s "
                        "(%.0fs without heartbeat)",
                        request_id, elapsed,
                    )
                    dead = self._talk_to_chain_dead.get(request_id)
                    if dead is not None:
                        dead.set()
                    return
        except asyncio.CancelledError:
            pass

