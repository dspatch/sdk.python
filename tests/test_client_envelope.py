# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for WsClient event envelope injection and heartbeat format."""

from __future__ import annotations

import json

import pytest

from dspatch.client import WsClient


class FakeWebSocket:
    """Minimal fake WebSocket for testing send behavior."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, data: str) -> None:
        self.sent.append(data)


@pytest.fixture
def client() -> WsClient:
    return WsClient(instance_id="inst_001")


@pytest.fixture
def connected_client(client: WsClient) -> WsClient:
    fake_ws = FakeWebSocket()
    client._ws = fake_ws
    client._connected.set()
    return client


class TestEventEnvelopeInjection:
    """send_event injects instance_id from constructor when not present."""

    @pytest.mark.asyncio
    async def test_send_event_injects_instance_id(self, connected_client: WsClient) -> None:
        await connected_client.send_event({"type": "agent.output.message", "content": "hi"})
        sent = json.loads(connected_client._ws.sent[-1])
        assert sent["instance_id"] == "inst_001"

    @pytest.mark.asyncio
    async def test_send_event_preserves_explicit_instance_id(self, connected_client: WsClient) -> None:
        await connected_client.send_event({"type": "agent.output.message", "instance_id": "inst_002"})
        sent = json.loads(connected_client._ws.sent[-1])
        assert sent["instance_id"] == "inst_002"  # explicit wins

    @pytest.mark.asyncio
    async def test_no_injection_for_auth_type(self, connected_client: WsClient) -> None:
        await connected_client.send_event({"type": "connection.auth", "api_key": "key"})
        sent = json.loads(connected_client._ws.sent[-1])
        assert "instance_id" not in sent

    @pytest.mark.asyncio
    async def test_no_injection_for_heartbeat_type(self, connected_client: WsClient) -> None:
        await connected_client.send_event({"type": "connection.heartbeat"})
        sent = json.loads(connected_client._ws.sent[-1])
        assert "instance_id" not in sent

    @pytest.mark.asyncio
    async def test_no_injection_when_instance_id_is_none(self) -> None:
        client = WsClient()  # no instance_id
        fake_ws = FakeWebSocket()
        client._ws = fake_ws
        client._connected.set()
        await client.send_event({"type": "agent.output.message", "content": "hi"})
        sent = json.loads(fake_ws.sent[-1])
        assert "instance_id" not in sent

    @pytest.mark.asyncio
    async def test_injection_in_buffered_events(self, client: WsClient) -> None:
        # Not connected, so event gets buffered
        await client.send_event({"type": "agent.output.message", "content": "hello"})
        assert len(client._outgoing_buffer) == 1
        buffered = json.loads(client._outgoing_buffer[0])
        assert buffered["instance_id"] == "inst_001"


class TestHeartbeatFormat:
    """send_heartbeat accepts an optional instance map."""

    @pytest.mark.asyncio
    async def test_heartbeat_sends_instance_map(self, connected_client: WsClient) -> None:
        await connected_client.send_heartbeat({"inst_001": "running", "inst_002": "completed"})
        sent = json.loads(connected_client._ws.sent[-1])
        assert sent["type"] == "connection.heartbeat"
        assert sent["instances"] == {"inst_001": "running", "inst_002": "completed"}

    @pytest.mark.asyncio
    async def test_heartbeat_without_instances(self, connected_client: WsClient) -> None:
        await connected_client.send_heartbeat()
        sent = json.loads(connected_client._ws.sent[-1])
        assert sent["type"] == "connection.heartbeat"
        assert "instances" not in sent

    @pytest.mark.asyncio
    async def test_heartbeat_no_instance_id_injection(self, connected_client: WsClient) -> None:
        """Heartbeat should not get instance_id injected."""
        await connected_client.send_heartbeat({"inst_001": "running"})
        sent = json.loads(connected_client._ws.sent[-1])
        assert "instance_id" not in sent
