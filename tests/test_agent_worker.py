# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
# packages/dspatch-sdk/tests/test_agent_worker.py
"""Tests for AgentWorker."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from dspatch.agent_worker import AgentWorker
from dspatch.instance_router import AgentInstanceRouter
from dspatch.state_manager import StateManager
from dspatch.dispatcher import InputItem, InquiryInterruptItem
from dspatch.contexts import Context


def _make_stack(agent_fn=None):
    if agent_fn is None:
        async def agent_fn(text, ctx):
            return f"echo: {text}"
    sm = StateManager()
    router = AgentInstanceRouter(state_manager=sm)
    host = MagicMock()
    host.send_event = AsyncMock()
    worker = AgentWorker(
        agent_fn=agent_fn,
        agent_name="test",
        instance_id="inst1",
        router=router,
        state_manager=sm,
        host=host,
    )
    return worker, router, sm


class TestAgentWorkerUserInput:
    @pytest.mark.asyncio
    async def test_processes_user_input(self):
        results = []
        async def agent_fn(text, ctx):
            results.append(text)
            return f"echo: {text}"
        worker, router, sm = _make_stack(agent_fn)
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "hello"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)
        assert len(results) == 1
        assert "hello" in results[0]
        assert "{{SENDER: user}}" in results[0]

    @pytest.mark.asyncio
    async def test_sets_generating_before_running(self):
        states = []
        async def agent_fn(text, ctx):
            states.append(sm.current_state)
            return "done"
        worker, router, sm = _make_stack(agent_fn)
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "hi"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)
        assert states == ["generating"]

    @pytest.mark.asyncio
    async def test_empty_user_input_returns_to_idle(self):
        ran = []
        async def agent_fn(text, ctx):
            ran.append(text)
            return "done"
        worker, router, sm = _make_stack(agent_fn)
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": ""}))
        await asyncio.wait_for(worker._run_one(), timeout=2)
        assert sm.current_state == "idle"
        assert len(ran) == 0  # agent should not have been called

    @pytest.mark.asyncio
    async def test_sets_idle_after_running(self):
        async def agent_fn(text, ctx):
            return "done"
        worker, router, sm = _make_stack(agent_fn)
        router.feed.put_nowait(InputItem(event={"type": "agent.event.user_input", "content": "hi"}))
        await asyncio.wait_for(worker._run_one(), timeout=2)
        assert sm.current_state == "idle"


class TestAgentWorkerTalkToRequest:
    @pytest.mark.asyncio
    async def test_processes_talk_to_request_as_input(self):
        results = []
        async def agent_fn(text, ctx):
            results.append(text)
            return "response"
        worker, router, sm = _make_stack(agent_fn)
        router.feed.put_nowait(InputItem(event={
            "type": "agent.event.talk_to.request",
            "text": "help me",
            "request_id": "req1",
        }))
        await asyncio.wait_for(worker._run_one(), timeout=2)
        assert len(results) == 1
        assert "help me" in results[0]
        assert "{{SENDER:" in results[0]

    @pytest.mark.asyncio
    async def test_sends_talk_to_response_after_talk_to_request(self):
        async def agent_fn(text, ctx):
            return "my response"
        worker, router, sm = _make_stack(agent_fn)
        router.feed.put_nowait(InputItem(event={
            "type": "agent.event.talk_to.request",
            "text": "help",
            "request_id": "req1",
        }))
        await asyncio.wait_for(worker._run_one(), timeout=2)
        sent = worker._host.send_event.call_args_list
        types = [c[0][0].get("type") for c in sent]
        assert "agent.event.talk_to.response" in types


class TestAgentWorkerIdleInquiry:
    @pytest.mark.asyncio
    async def test_idle_inquiry_is_processed_as_input(self):
        results = []
        async def agent_fn(text, ctx):
            results.append(text)
            return "handled"
        worker, router, sm = _make_stack(agent_fn)
        router.feed.put_nowait(InquiryInterruptItem(event={
            "type": "agent.event.inquiry.request",
            "inquiry_id": "inq1",
            "content_markdown": "Can you help?",
        }))
        await asyncio.wait_for(worker._run_one(), timeout=2)
        assert len(results) == 1
        assert "Can you help?" in results[0]
