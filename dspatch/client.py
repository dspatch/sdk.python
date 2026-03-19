# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""WebSocket client for v2 workspace communication."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import deque

import websockets
import websockets.exceptions

logger = logging.getLogger("dspatch.client")

_RECONNECT_BASE = 2
_RECONNECT_MAX = 30
_BUFFER_MAX = 5000
_CRITICAL_TYPES = frozenset({
    "agent.event.inquiry.request", "agent.event.talk_to.request",
    "agent.event.talk_to.response", "connection.register",
})


class WsClient:
    """WebSocket client for v2 workspace communication.

    Single bidirectional JSON channel per agent, replacing all
    v1 HTTP endpoints.

    Env vars:
      DSPATCH_API_URL  → http://host.docker.internal:{port}
      DSPATCH_API_KEY  → per-run auth key
      DSPATCH_RUN_ID   → workspace run identifier (WebSocket routing key)
      DSPATCH_WORKSPACE_ID → workspace identifier (metadata only)
      DSPATCH_AGENT_ID → this agent's ID (e.g. "lead", "coder-0")
    """

    def __init__(self, instance_id: str | None = None) -> None:
        api_url = os.environ.get("DSPATCH_API_URL", "")
        api_key = os.environ.get("DSPATCH_API_KEY", "")
        run_id = os.environ.get("DSPATCH_RUN_ID", "")
        workspace_id = os.environ.get("DSPATCH_WORKSPACE_ID", "")
        agent_id = os.environ.get("DSPATCH_AGENT_ID", "")

        missing = [
            name
            for name, val in [
                ("DSPATCH_API_URL", api_url),
                ("DSPATCH_API_KEY", api_key),
                ("DSPATCH_RUN_ID", run_id),
                ("DSPATCH_AGENT_ID", agent_id),
            ]
            if not val
        ]
        if missing:
            raise RuntimeError(
                f"Missing required env vars: {', '.join(missing)}. "
                "Are you running inside a dspatch v2 workspace container?"
            )

        # Convert http:// to ws:// for the WebSocket URL.
        # WebSocket route is keyed by runId, not workspaceId.
        ws_url = api_url.replace("http://", "ws://").replace("https://", "wss://")
        base_url = f"{ws_url}/ws/{run_id}/{agent_id}"
        self._ws_url = f"{base_url}/{instance_id}" if instance_id else base_url
        self._api_key = api_key
        self._workspace_id = workspace_id
        self._agent_id = agent_id
        self._instance_id = instance_id

        self._ws: websockets.WebSocketClientProtocol | None = None  # type: ignore[name-defined]
        self._connected = asyncio.Event()
        self._receive_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10_000)
        self._receive_task: asyncio.Task | None = None
        self._outgoing_buffer: deque[str] = deque(maxlen=_BUFFER_MAX)
        self._register_event: dict | None = None
        self._reconnect_task: asyncio.Task | None = None

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def instance_id(self) -> str | None:
        return self._instance_id

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._connected.is_set()

    # ── Connection lifecycle ──────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to the WebSocket server and authenticate."""
        backoff = _RECONNECT_BASE

        while True:
            try:
                self._ws = await websockets.connect(
                    self._ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                )

                # Send auth event.
                await self._ws.send(json.dumps({
                    "type": "connection.auth",
                    "api_key": self._api_key,
                }))

                # Wait for auth_ack or auth_error.
                raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
                resp = json.loads(raw)

                if resp.get("type") == "connection.auth_ack":
                    self._connected.set()
                    logger.info("Connected and authenticated: %s", self._ws_url)

                    # Start receive loop.
                    self._receive_task = asyncio.create_task(self._receive_loop())
                    return
                else:
                    msg = resp.get("message", "Unknown auth error")
                    raise RuntimeError(f"Auth failed: {msg}")

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(
                    "Connection failed (%s), retrying in %ds...",
                    exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX)

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket connection."""
        self._connected.clear()

        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.info("Disconnected")

    async def reconnect(self) -> None:
        """Reconnect after a connection drop."""
        logger.info("Reconnecting...")
        self._connected.clear()

        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        await self._background_reconnect()

    # ── Send methods ─────────────────────────────────────────────────────

    _NO_INSTANCE_ID_TYPES = frozenset({"connection.auth", "connection.heartbeat"})

    async def send_event(self, event: dict) -> None:
        """Send a typed JSON event to the app.

        Automatically injects ``instance_id`` from the constructor when
        the event doesn't already carry one (skipped for *auth* and
        *heartbeat* types).

        If disconnected, the event is buffered and will be replayed
        automatically once the connection is re-established.
        """
        if (
            self._instance_id is not None
            and "instance_id" not in event
            and event.get("type") not in self._NO_INSTANCE_ID_TYPES
        ):
            event = {**event, "instance_id": self._instance_id}

        payload = json.dumps(event)

        if not self.is_connected or self._ws is None:
            self._buffer_payload(payload)
            return

        try:
            await self._ws.send(payload)
        except Exception:
            # Send failed mid-flight — buffer for later replay.
            self._buffer_payload(payload)

    def _buffer_payload(self, payload: str) -> None:
        """Append *payload* to the outgoing buffer, evicting if full."""
        if len(self._outgoing_buffer) >= _BUFFER_MAX:
            self._evict_non_critical()
        self._outgoing_buffer.append(payload)

    def _evict_non_critical(self) -> None:
        """Remove the oldest non-critical event from the buffer.

        If every event in the buffer is critical, do nothing and let
        the deque's *maxlen* silently drop the oldest entry instead.
        """
        for i, raw in enumerate(self._outgoing_buffer):
            try:
                evt = json.loads(raw)
            except Exception:
                # Malformed — safe to evict.
                del self._outgoing_buffer[i]
                return
            if evt.get("type") not in _CRITICAL_TYPES:
                del self._outgoing_buffer[i]
                return

    async def send_heartbeat(self, instances: dict[str, str] | None = None) -> None:
        """Send a heartbeat, optionally including an instance status map.

        Unlike other events, heartbeats are fire-and-forget and are
        **not** buffered when the connection is down.
        """
        event: dict = {"type": "connection.heartbeat"}
        if instances is not None:
            event["instances"] = instances
        if not self.is_connected or self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(event))
        except Exception:
            pass

    async def send_register(
        self, name: str, role: str = "", capabilities: list[str] | None = None,
    ) -> None:
        """Send register event after authentication."""
        event = {
            "type": "connection.register",
            "name": name,
            "role": role,
            "capabilities": capabilities or [],
        }
        self._register_event = event
        await self.send_event(event)

    async def send_message(
        self,
        content: str,
        role: str = "assistant",
        message_id: str | None = None,
        is_delta: bool = False,
        **kwargs: object,
    ) -> str:
        """Send a chat message. Returns the message id."""
        msg_id = message_id or uuid.uuid4().hex
        await self.send_event({
            "type": "agent.output.message",
            "id": msg_id,
            "role": role,
            "content": content,
            "is_delta": is_delta,
            **kwargs,
        })
        return msg_id

    async def send_activity(
        self,
        event_type: str,
        *,
        content: str | None = None,
        is_delta: bool = False,
        activity_id: str | None = None,
        data: dict | None = None,
    ) -> str:
        """Report a tool call or other activity. Returns the activity id."""
        aid = activity_id or uuid.uuid4().hex
        event: dict = {
            "type": "agent.output.activity",
            "id": aid,
            "event_type": event_type,
            "is_delta": is_delta,
        }
        if content is not None:
            event["content"] = content
        if data is not None:
            event["data"] = data
        await self.send_event(event)
        return aid

    async def send_log(self, level: str, message: str) -> None:
        """Send a single log entry."""
        await self.send_event({
            "type": "agent.output.log",
            "level": level,
            "message": message,
        })

    async def send_logs(self, entries: list[dict]) -> None:
        """Send multiple log entries (one event per entry)."""
        for entry in entries:
            await self.send_log(
                entry.get("level", "info"),
                entry.get("message", ""),
            )

    async def send_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        **kwargs: object,
    ) -> None:
        """Report token usage for an LLM call."""
        await self.send_event({
            "type": "agent.output.usage",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            **kwargs,
        })

    async def send_files(self, files: list[dict]) -> None:
        """Report file operations."""
        await self.send_event({"type": "agent.output.files", "files": files})

    async def send_inquiry(
        self,
        content_markdown: str,
        inquiry_id: str | None = None,
        suggestions: list[dict] | None = None,
        file_paths: list[str] | None = None,
        priority: str = "normal",
    ) -> None:
        """Create an inquiry for the user."""
        event: dict = {
            "type": "agent.event.inquiry.request",
            "content_markdown": content_markdown,
            "priority": priority,
        }
        if inquiry_id is not None:
            event["inquiry_id"] = inquiry_id
        if suggestions is not None:
            event["suggestions"] = suggestions
        if file_paths is not None:
            event["file_paths"] = file_paths
        await self.send_event(event)

    async def send_agent_message(
        self, target_agent_id: str, content: str,
    ) -> None:
        """Send a message to another agent in the workspace."""
        await self.send_event({
            "type": "agent.event.agent_message",
            "target_agent_id": target_agent_id,
            "content": content,
        })

    async def send_talk_to_request(
        self,
        target_agent: str,
        text: str,
        request_id: str,
        continue_conversation: bool = False,
        conversation_id: str | None = None,
    ) -> None:
        """Request the Dart server to route a message to a target agent instance."""
        event: dict = {
            "type": "agent.event.talk_to.request",
            "target_agent": target_agent,
            "text": text,
            "request_id": request_id,
            "continue_conversation": continue_conversation,
        }
        if conversation_id is not None:
            event["conversation_id"] = conversation_id
        await self.send_event(event)

    # ── Receive ──────────────────────────────────────────────────────────

    async def receive_event(self, timeout: float | None = None) -> dict:
        """Wait for the next event from the app."""
        if timeout is not None:
            return await asyncio.wait_for(
                self._receive_queue.get(), timeout=timeout,
            )
        return await self._receive_queue.get()

    # ── Internal ─────────────────────────────────────────────────────────

    def _start_background_reconnect(self) -> None:
        """Kick off a background reconnect task if one is not already running."""
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._background_reconnect())

    async def _background_reconnect(self) -> None:
        """Reconnect with exponential backoff, re-auth, replay buffer."""
        # Clean up the old connection.
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        backoff = _RECONNECT_BASE

        while True:
            try:
                self._ws = await websockets.connect(
                    self._ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                )

                # Authenticate.
                await self._ws.send(json.dumps({
                    "type": "connection.auth",
                    "api_key": self._api_key,
                }))

                raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
                resp = json.loads(raw)

                if resp.get("type") != "connection.auth_ack":
                    msg = resp.get("message", "Unknown auth error")
                    raise RuntimeError(f"Auth failed: {msg}")

                self._connected.set()
                logger.info("Reconnected and authenticated: %s", self._ws_url)

                # Re-send saved register event so the engine knows who we are.
                if self._register_event is not None:
                    await self._ws.send(json.dumps(self._register_event))

                # Drain buffered outgoing events in FIFO order.
                # Peek before pop so events survive a mid-drain failure.
                while self._outgoing_buffer:
                    payload = self._outgoing_buffer[0]
                    await self._ws.send(payload)
                    self._outgoing_buffer.popleft()

                # Restart receive loop.
                self._receive_task = asyncio.create_task(self._receive_loop())
                return

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(
                    "Reconnect failed (%s), retrying in %ds...",
                    exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX)

    async def _receive_loop(self) -> None:
        """Background task: read from WebSocket, enqueue events."""
        try:
            while self._ws is not None:
                try:
                    raw = await self._ws.recv()
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        try:
                            self._receive_queue.put_nowait(data)
                        except asyncio.QueueFull:
                            # Drop oldest to make room for incoming event.
                            try:
                                self._receive_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            logger.warning(
                                "Receive queue full (%d), dropping oldest event",
                                self._receive_queue.maxsize,
                            )
                            self._receive_queue.put_nowait(data)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON message received, skipping")
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Connection lost, reconnecting in background")
                    self._connected.clear()
                    self._start_background_reconnect()
                    break
                except Exception:
                    logger.debug("Receive loop error", exc_info=True)
                    break
        except asyncio.CancelledError:
            pass
