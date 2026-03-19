# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for WsClient transparent connection buffering."""

from __future__ import annotations

import asyncio
import json

import pytest

from dspatch.client import WsClient, _BUFFER_MAX, _CRITICAL_TYPES


class FakeWebSocket:
    """Minimal fake WebSocket for testing send/recv behavior."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send(self, data: str) -> None:
        if self.closed:
            raise ConnectionError("closed")
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def client() -> WsClient:
    return WsClient()


class TestSendEventBuffering:
    """send_event buffers when disconnected, sends when connected."""

    @pytest.mark.asyncio
    async def test_buffers_when_disconnected(self, client: WsClient) -> None:
        await client.send_event({"type": "agent.output.message", "content": "hello"})
        assert len(client._outgoing_buffer) == 1
        payload = json.loads(client._outgoing_buffer[0])
        assert payload["type"] == "agent.output.message"

    @pytest.mark.asyncio
    async def test_sends_directly_when_connected(self, client: WsClient) -> None:
        fake_ws = FakeWebSocket()
        client._ws = fake_ws
        client._connected.set()
        await client.send_event({"type": "agent.output.log", "level": "info", "message": "hi"})
        assert len(fake_ws.sent) == 1
        assert len(client._outgoing_buffer) == 0

    @pytest.mark.asyncio
    async def test_falls_back_to_buffer_on_send_failure(self, client: WsClient) -> None:
        fake_ws = FakeWebSocket()
        fake_ws.closed = True
        client._ws = fake_ws
        client._connected.set()
        await client.send_event({"type": "agent.output.message", "content": "hello"})
        assert len(client._outgoing_buffer) == 1

    @pytest.mark.asyncio
    async def test_heartbeat_dropped_when_disconnected(self, client: WsClient) -> None:
        await client.send_heartbeat()
        assert len(client._outgoing_buffer) == 0


class TestBufferOverflow:

    @pytest.mark.asyncio
    async def test_evicts_non_critical_when_full(self, client: WsClient) -> None:
        for i in range(_BUFFER_MAX):
            client._outgoing_buffer.append(
                json.dumps({"type": "agent.output.log", "level": "info", "message": f"msg-{i}"})
            )
        await client.send_event({"type": "agent.event.inquiry.request", "content_markdown": "test"})
        assert len(client._outgoing_buffer) == _BUFFER_MAX
        last = json.loads(client._outgoing_buffer[-1])
        assert last["type"] == "agent.event.inquiry.request"


class TestRegisterReplay:

    @pytest.mark.asyncio
    async def test_register_event_saved(self, client: WsClient) -> None:
        await client.send_register(name="test-agent", role="host")
        assert client._register_event is not None
        assert client._register_event["type"] == "connection.register"
        assert client._register_event["name"] == "test-agent"
        assert client._register_event["role"] == "host"
        assert len(client._outgoing_buffer) == 1
