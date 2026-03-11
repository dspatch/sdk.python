# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Agent host router — single connection owner and event router for all instances."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import traceback
import uuid
from collections.abc import Callable

from .agent_worker import AgentWorker
from .client import WsClient
from .contexts import Context
from .instance_router import AgentInstanceRouter
from .state_manager import StateManager

logger = logging.getLogger("dspatch.host")

_HEARTBEAT_INTERVAL = 5  # seconds

_LEVEL_MAP: dict[int, str] = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class _DspatchLogHandler(logging.Handler):
    """Buffers ``dspatch.*`` log records until the host connects, then forwards live.

    Installed on ``logging.getLogger("dspatch")`` with ``propagate=False``
    so records never reach the root stderr handler — no duplication, no
    root-logger side effects.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self._client: WsClient | None = None
        self._buffer: list[tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _LEVEL_MAP.get(record.levelno, "info")
            message = self.format(record)
            if self._client is None:
                self._buffer.append((level, message))
            else:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._client.send_log(level, message))
                except RuntimeError:
                    # No running loop — keep buffering.
                    self._buffer.append((level, message))
        except Exception:
            self.handleError(record)

    async def attach(self, client: WsClient) -> None:
        """Flush the pre-connection buffer then forward new records live."""
        for level, message in self._buffer:
            await client.send_log(level, message)
        self._buffer.clear()
        self._client = client

    def detach(self) -> None:
        """Stop live forwarding."""
        self._client = None


class AgentHostRouter:
    """Manages instances of a single agent type.

    Single WsClient connection owner.  All inbound events flow through one
    ``_event_loop`` and are dispatched to per-instance ``asyncio.Queue``s
    via ``_instance_dispatch``.

    - Connects at the type level: /ws/<workspace>/<agent-name>
    - Listens for spawn_instance events from the engine
    - Spawns AgentWorker asyncio tasks
    - Routes instance-level events to the correct queue
    - Sends aggregated heartbeats with all instance states
    - For root agents: auto-spawns one persistent instance
    """

    def __init__(
        self,
        agent_fn: Callable,
        client: WsClient,
        *,
        context_class: type[Context] = Context,
    ) -> None:
        self._agent_fn = agent_fn
        self._client = client
        self._context_class = context_class
        self._running = True
        self._instances: dict[str, asyncio.Task] = {}
        self._agent_name = os.environ.get("DSPATCH_AGENT_KEY", "")
        self._heartbeat_task: asyncio.Task | None = None

        # Per-instance event dispatch and state tracking.
        self._instance_dispatch: dict[str, asyncio.Queue] = {}
        self._instance_routers: dict[str, AgentInstanceRouter] = {}
        self._instance_sms: dict[str, StateManager] = {}
        self._instance_workers: dict[str, AgentWorker] = {}
        self._instance_worker_tasks: dict[str, asyncio.Task] = {}

        # Install buffering log handler on the dspatch logger namespace.
        # propagate=False keeps records out of the root stderr handler so
        # there is no duplication — dspatch.* logs go exclusively over the
        # WebSocket once connected.
        self._log_handler = _DspatchLogHandler()
        _dspatch_logger = logging.getLogger("dspatch")
        _dspatch_logger.addHandler(self._log_handler)
        _dspatch_logger.propagate = False

    async def start(self) -> None:
        """Main entry — connect, register, listen for events."""
        import sys

        logger.info("=" * 44)
        logger.info("d:spatch Agent Host Starting")
        logger.info("=" * 44)
        logger.info("Python: %s", sys.version.split()[0])
        logger.info("Agent: %s", self._agent_name)
        logger.info("Workspace: %s", self._client.workspace_id)
        logger.info("DSPATCH_PEERS: %s", os.environ.get("DSPATCH_PEERS", "<not set>"))
        logger.info("DSPATCH_AGENTS_META: %s", os.environ.get("DSPATCH_AGENTS_META", "<not set>"))
        logger.info("=" * 44)

        # Log all environment variables (buffered until connected).
        for key, value in sorted(os.environ.items()):
            logger.debug("ENV %s=%s", key, value)

        # Install signal handlers.
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._request_stop)
            except NotImplementedError:
                signal.signal(sig, lambda *_: self._request_stop())

        try:
            # 1. Connect and authenticate.
            await self._client.connect()
            logger.info("Host connected and authenticated")

            # 2. Register as agent host.
            await self._client.send_register(
                name=self._agent_name,
                role="host",
            )
            logger.info("Host registered")

            # 3. Flush buffered logs and start live forwarding.
            await self._log_handler.attach(self._client)

            # 4. Start heartbeat.
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("Heartbeat started (interval: %ds)", _HEARTBEAT_INTERVAL)

            # 5. Event loop.
            await self._event_loop()

        except Exception:
            logger.error("Fatal error in host:\n%s", traceback.format_exc())
        finally:
            logger.info("Host shutting down...")
            self._log_handler.detach()
            _dspatch_logger = logging.getLogger("dspatch")
            _dspatch_logger.removeHandler(self._log_handler)
            _dspatch_logger.propagate = True
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            await self._cancel_all_instances()
            await self._client.disconnect()
            logger.info("Host shut down.")

    async def _event_loop(self) -> None:
        """Receive events and route by type.

        Host-level events (connection.spawn_instance, agent.signal.terminate,
        agent.signal.drain, agent.signal.state_query) are handled directly.
        Instance-level events are forwarded to the per-instance queue
        identified by ``instance_id``.
        """
        while self._running:
            try:
                event = await self._client.receive_event(timeout=60)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._running:
                    break
                logger.warning("Event receive error", exc_info=True)
                continue

            event_type = event.get("type", "")
            instance_id = event.get("instance_id")

            # ── Host-level events ────────────────────────────────────────
            if event_type == "connection.spawn_instance":
                await self._handle_spawn_instance(event)
            elif event_type == "agent.signal.drain":
                iid = event.get("instance_id")
                if iid:
                    await self._drain_instance(iid)
                else:
                    logger.info("Draining whole host")
                    self._running = False
            elif event_type == "agent.signal.terminate":
                iid = event.get("instance_id")
                if iid:
                    await self._kill_instance(iid)
                else:
                    logger.info("Terminating whole host")
                    self._running = False
            elif event_type == "agent.signal.interrupt":
                iid = event.get("instance_id")
                if iid:
                    await self._interrupt_instance(iid)
            elif event_type == "agent.signal.state_query":
                request_id = event.get("request_id", "")
                states = {iid: sm.current_state for iid, sm in self._instance_sms.items()}
                await self._client.send_event({
                    "type": "agent.signal.state_report",
                    "request_id": request_id,
                    "state": "idle",
                    "instances": states,
                })
            # ── Instance-level events → route to queue ───────────────────
            elif instance_id and instance_id in self._instance_dispatch:
                self._instance_dispatch[instance_id].put_nowait(event)

            # Events without instance_id → route to first available instance.
            elif not instance_id and self._instance_dispatch:
                first_id = next(iter(self._instance_dispatch))
                logger.debug(
                    "Routing %s to instance %s (no instance_id)",
                    event_type, first_id,
                )
                self._instance_dispatch[first_id].put_nowait(event)

            else:
                logger.warning(
                    "No route for event: %s (instance=%s)", event_type, instance_id,
                )

    async def _handle_spawn_instance(self, event: dict) -> None:
        """Handle an open_conversation event from the engine.

        Spawns a new long-lived instance that runs the unified event loop.
        The engine will detect the instance via heartbeat and then route
        messages to it.
        """
        instance_id = event.get("instance_id", "")

        logger.info("Opening conversation: instance %s", instance_id)

        await self._spawn_instance(instance_id=instance_id)

    async def _spawn_instance(
        self,
        *,
        instance_id: str,
    ) -> None:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        sm = StateManager()
        router = AgentInstanceRouter(state_manager=sm)
        router.on_control = lambda e: self._handle_instance_control(instance_id, e)
        router.on_keepalive = lambda e: self._handle_instance_keepalive(instance_id, e)

        worker = AgentWorker(
            agent_fn=self._agent_fn,
            agent_name=self._agent_name,
            instance_id=instance_id,
            router=router,
            state_manager=sm,
            host=self,
            context_class=self._context_class,
        )

        # Wire proactive state reports: on every state change, send a
        # StateReportPackage so the Dart side updates immediately instead of
        # waiting for the next heartbeat (up to 5 s).
        # Must be done AFTER router creation (router.__init__ sets on_state_changed).
        _router_state_cb = sm.on_state_changed

        def _proactive_state_report(old_state: str, new_state: str) -> None:
            if _router_state_cb is not None:
                _router_state_cb(old_state, new_state)
            asyncio.create_task(self._client.send_event({
                "type": "agent.signal.state_report",
                "instance_id": instance_id,
                "state": new_state,
            }))

        sm.on_state_changed = _proactive_state_report

        self._instance_dispatch[instance_id] = queue
        self._instance_routers[instance_id] = router
        self._instance_sms[instance_id] = sm
        self._instance_workers[instance_id] = worker

        task = asyncio.create_task(
            self._instance_event_loop(instance_id, queue, router, worker),
            name=f"instance-{instance_id}",
        )
        self._instances[instance_id] = task

        def _on_done(t, iid=instance_id):
            self._instances.pop(iid, None)
            self._instance_dispatch.pop(iid, None)
            self._instance_routers.pop(iid, None)
            self._instance_sms.pop(iid, None)
            self._instance_workers.pop(iid, None)
            self._instance_worker_tasks.pop(iid, None)

        task.add_done_callback(_on_done)

        # Send instance_spawned ack to Dart.
        await self._client.send_event({
            "type": "agent.signal.instance_spawned",
            "instance_id": instance_id,
        })

    async def _instance_event_loop(
        self,
        instance_id: str,
        queue: asyncio.Queue,
        router: AgentInstanceRouter,
        worker: AgentWorker,
    ) -> None:
        """Feed raw queue events into the AgentInstanceRouter, run worker in parallel."""
        worker_task = asyncio.create_task(
            worker.run(), name=f"worker-{instance_id}",
        )
        self._instance_worker_tasks[instance_id] = worker_task

        def _log_worker_error(t: asyncio.Task, iid=instance_id):
            if not t.cancelled() and t.exception() is not None:
                logger.error("Worker %s crashed: %s", iid, t.exception())
        worker_task.add_done_callback(_log_worker_error)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=60)
                except asyncio.TimeoutError:
                    continue
                router.receive(event)

                # If the worker was cancelled (e.g. by interrupt), restart it.
                if worker_task.done():
                    worker_task = asyncio.create_task(
                        worker.run(), name=f"worker-{instance_id}",
                    )
                    self._instance_worker_tasks[instance_id] = worker_task
                    worker_task.add_done_callback(_log_worker_error)
        except asyncio.CancelledError:
            raise
        finally:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    def _handle_instance_control(self, instance_id: str, event: dict) -> None:
        """Handle instance-level control events (state_query, terminate, drain, interrupt)."""
        event_type = event.get("type", "")
        if event_type == "agent.signal.state_query":
            request_id = event.get("request_id", "")
            sm = self._instance_sms.get(instance_id)
            state = sm.current_state if sm else "idle"
            asyncio.create_task(self._client.send_event({
                "type": "agent.signal.state_report",
                "instance_id": instance_id,
                "request_id": request_id,
                "state": state,
                "instances": {instance_id: state},
            }))
        elif event_type == "agent.signal.terminate":
            asyncio.create_task(self._kill_instance(instance_id))
        elif event_type == "agent.signal.drain":
            asyncio.create_task(self._drain_instance(instance_id))
        elif event_type == "agent.signal.interrupt":
            asyncio.create_task(self._interrupt_instance(instance_id))

    def _handle_instance_keepalive(self, instance_id: str, event: dict) -> None:
        """Handle keepalive events for an instance — forward to its Context."""
        worker = self._instance_workers.get(instance_id)
        if worker is not None and worker._ctx is not None:
            # request.alive carries request_id; inquiry.alive carries inquiry_id.
            alive_id = event.get("request_id") or event.get("inquiry_id", "")
            worker._ctx._record_request_alive(alive_id)

    async def _interrupt_instance(self, instance_id: str) -> None:
        """Interrupt current generation — cancel the worker, reset to idle, keep instance alive.

        The worker task is cancelled (which aborts the running agent function),
        state is reset to idle, and the _instance_event_loop will restart the
        worker on its next iteration.
        """
        sm = self._instance_sms.get(instance_id)
        router = self._instance_routers.get(instance_id)
        worker = self._instance_workers.get(instance_id)
        worker_task = self._instance_worker_tasks.get(instance_id)

        if sm is None or router is None:
            logger.warning("Interrupt: instance %s not found", instance_id)
            return

        if sm.current_state == "idle":
            logger.debug("Interrupt: instance %s already idle", instance_id)
            return

        # 1. Cancel the worker task — this aborts the running agent function.
        if worker_task is not None and not worker_task.done():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

        # 2. Reset state: pop any active turns and force idle.
        #    Use _set_state to bypass guards — interrupt can happen from any state.
        while router.current_turn_id is not None:
            router.pop_turn()
        sm._pending_wait = None
        sm._current_interrupt = None
        sm._set_state("idle")

        # 3. Reset the worker so it can be restarted by _instance_event_loop.
        if worker is not None:
            worker._running = True
            worker._gen = None

        logger.info("Instance interrupted: %s", instance_id)

    async def _drain_instance(self, instance_id: str) -> None:
        """Gracefully stop an instance — let it finish current turn, then cancel."""
        # Mark instance as draining by stopping its event loop cleanly.
        # For now: same as kill (graceful shutdown not yet implemented).
        await self._kill_instance(instance_id)
        logger.info("Instance drained (immediate kill — graceful drain not yet implemented): %s", instance_id)

    async def _kill_instance(self, instance_id: str) -> None:
        """Cancel a running instance task and clean up dispatch state."""
        task = self._instances.pop(instance_id, None)
        self._instance_dispatch.pop(instance_id, None)
        self._instance_routers.pop(instance_id, None)
        self._instance_sms.pop(instance_id, None)
        self._instance_workers.pop(instance_id, None)
        self._instance_worker_tasks.pop(instance_id, None)

        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info("Instance killed: %s", instance_id)

    async def _cancel_all_instances(self) -> None:
        """Cancel all running instances."""
        for task in self._instances.values():
            task.cancel()
        for task in self._instances.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._instances.clear()
        self._instance_dispatch.clear()
        self._instance_routers.clear()
        self._instance_sms.clear()
        self._instance_workers.clear()
        self._instance_worker_tasks.clear()

    def _request_stop(self) -> None:
        logger.info("Shutdown requested.")
        self._running = False

    async def _heartbeat_loop(self) -> None:
        """Background task: send heartbeat with instance states every interval."""
        try:
            while self._running:
                states = {
                    iid: sm.current_state
                    for iid, sm in self._instance_sms.items()
                }
                await self._client.send_heartbeat(states)
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            pass

    # ── Public API for AgentWorkers ──────────────────────────────────────

    async def send_event(self, event: dict) -> None:
        """Forward an event through the single WsClient connection."""
        await self._client.send_event(event)
