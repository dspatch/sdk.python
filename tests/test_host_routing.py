# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for AgentHostRouter event routing and dispatch."""

from __future__ import annotations

import asyncio
import json

import pytest

from dspatch.client import WsClient
from dspatch.host import AgentHostRouter


class FakeWebSocket:
    """Minimal fake WebSocket for testing send behavior."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, data: str) -> None:
        self.sent.append(data)


def _make_connected_client() -> WsClient:
    """Create a WsClient wired to a FakeWebSocket (no real connection)."""
    client = WsClient()  # no instance_id — host-level
    fake_ws = FakeWebSocket()
    client._ws = fake_ws
    client._connected.set()
    return client


def _make_host(client: WsClient | None = None) -> AgentHostRouter:
    """Create an AgentHostRouter with a fake client and trivial agent_fn."""

    async def dummy_agent(text, ctx):
        return "ok"

    if client is None:
        client = _make_connected_client()
    return AgentHostRouter(agent_fn=dummy_agent, client=client)


class TestEventRouting:
    """Events with instance_id are dispatched to the correct instance queue."""

    @pytest.mark.asyncio
    async def test_routes_event_to_correct_instance(self) -> None:
        host = _make_host()

        # Register two instance queues.
        q1: asyncio.Queue[dict] = asyncio.Queue()
        q2: asyncio.Queue[dict] = asyncio.Queue()
        host._instance_dispatch["inst_001"] = q1
        host._instance_dispatch["inst_002"] = q2

        # Inject an event targeting inst_001 into the client receive queue.
        event = {"type": "agent.event.user_input", "instance_id": "inst_001", "content": "hello"}
        await host._client._receive_queue.put(event)

        # Also inject a stop signal so the event loop exits.
        await host._client._receive_queue.put(
            {"type": "agent.signal.terminate"}
        )

        host._running = True
        await host._event_loop()

        # inst_001 should have the event; inst_002 should be empty.
        assert not q1.empty()
        routed = q1.get_nowait()
        assert routed["content"] == "hello"
        assert q2.empty()

    @pytest.mark.asyncio
    async def test_unknown_instance_id_not_routed(self) -> None:
        host = _make_host()

        q1: asyncio.Queue[dict] = asyncio.Queue()
        host._instance_dispatch["inst_001"] = q1

        # Event for an unknown instance.
        event = {"type": "agent.event.user_input", "instance_id": "inst_999", "content": "lost"}
        await host._client._receive_queue.put(event)
        await host._client._receive_queue.put(
            {"type": "agent.signal.terminate"}
        )

        await host._event_loop()

        # Nothing should be routed anywhere.
        assert q1.empty()

    @pytest.mark.asyncio
    async def test_event_without_instance_id_logged_as_warning(self) -> None:
        """Events with unknown type and no instance_id are not routed."""
        host = _make_host()

        event = {"type": "some_unknown_event"}
        await host._client._receive_queue.put(event)
        await host._client._receive_queue.put(
            {"type": "agent.signal.terminate"}
        )

        # Should not raise.
        await host._event_loop()


class TestHostLevelEvents:
    """Host-level events (spawn_instance, state_query, terminate) are handled by the host,
    not routed to instance queues."""

    @pytest.mark.asyncio
    async def test_state_query_handled_by_host(self) -> None:
        client = _make_connected_client()
        host = _make_host(client=client)

        q1: asyncio.Queue[dict] = asyncio.Queue()
        host._instance_dispatch["inst_001"] = q1

        await client._receive_queue.put(
            {"type": "agent.signal.state_query", "request_id": "req_1", "instance_id": "inst_001"}
        )
        await client._receive_queue.put(
            {"type": "agent.signal.terminate"}
        )

        await host._event_loop()

        # state_query should NOT be routed to inst_001.
        assert q1.empty()

        # Host should have sent a state_report.
        sent = [json.loads(s) for s in client._ws.sent]
        state_reports = [e for e in sent if e.get("type") == "agent.signal.state_report"]
        assert len(state_reports) == 1
        assert state_reports[0]["request_id"] == "req_1"

    @pytest.mark.asyncio
    async def test_terminate_stops_host(self) -> None:
        host = _make_host()
        host._running = True

        await host._client._receive_queue.put(
            {"type": "agent.signal.terminate"}
        )

        await host._event_loop()

        assert host._running is False

    @pytest.mark.asyncio
    async def test_terminate_instance_handled_by_host(self) -> None:
        host = _make_host()

        # Create a fake task and queue for an instance.
        q: asyncio.Queue[dict] = asyncio.Queue()
        host._instance_dispatch["inst_001"] = q

        async def _dummy():
            await asyncio.sleep(100)

        task = asyncio.create_task(_dummy())
        host._instances["inst_001"] = task

        await host._client._receive_queue.put(
            {"type": "agent.signal.terminate", "instance_id": "inst_001"}
        )
        await host._client._receive_queue.put(
            {"type": "agent.signal.terminate"}
        )

        await host._event_loop()

        # Instance should be removed from dispatch.
        assert "inst_001" not in host._instance_dispatch
        assert task.cancelled()


class TestHeartbeatWithInstances:
    """Heartbeat collects instance states from _instance_sms."""

    @pytest.mark.asyncio
    async def test_heartbeat_sends_instance_states(self) -> None:
        from dspatch.state_manager import StateManager

        client = _make_connected_client()
        host = _make_host(client=client)

        sm1 = StateManager()
        sm1._state = "generating"
        sm2 = StateManager()
        sm2._state = "waiting_for_agent"
        host._instance_sms["inst_001"] = sm1
        host._instance_sms["inst_002"] = sm2

        # Build the states dict the same way the heartbeat loop does.
        states = {iid: sm.current_state for iid, sm in host._instance_sms.items()}
        await client.send_heartbeat(states)

        sent = json.loads(client._ws.sent[-1])
        assert sent["type"] == "heartbeat"
        assert sent["instances"]["inst_001"] == "generating"
        assert sent["instances"]["inst_002"] == "waiting_for_agent"

    @pytest.mark.asyncio
    async def test_heartbeat_empty_when_no_instances(self) -> None:
        client = _make_connected_client()
        host = _make_host(client=client)

        states = {iid: sm.current_state for iid, sm in host._instance_sms.items()}
        await client.send_heartbeat(states)

        sent = json.loads(client._ws.sent[-1])
        assert sent["type"] == "heartbeat"
        assert sent["instances"] == {}


class TestSpawnInstance:
    """_handle_open_conversation creates a dispatch queue and StateManager."""

    @pytest.mark.asyncio
    async def test_spawn_registers_dispatch_queue(self) -> None:
        host = _make_host()

        event = {
            "type": "connection.spawn_instance",
            "instance_id": "inst_abc",
        }

        await host._handle_spawn_instance(event)

        # Should have created dispatch queue and state manager entry.
        assert "inst_abc" in host._instance_dispatch
        assert "inst_abc" in host._instance_sms
        assert host._instance_sms["inst_abc"].current_state == "idle"
        assert "inst_abc" in host._instances

        # Clean up spawned task.
        task = host._instances.get("inst_abc")
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
