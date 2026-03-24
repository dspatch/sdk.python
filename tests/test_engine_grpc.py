# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for DspatchEngine gRPC integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dspatch.engine import DspatchEngine


def test_agent_decorator():
    engine = DspatchEngine()

    @engine.agent()
    async def my_agent(text, ctx):
        pass

    assert engine._agent_fn is my_agent
    assert engine._context_class is not None


def test_agent_decorator_with_context():
    from dspatch.contexts.context import Context

    engine = DspatchEngine()

    @engine.agent(context_class=Context)
    async def my_agent(text, ctx):
        pass

    assert engine._context_class is Context
