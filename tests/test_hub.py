# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for DspatchEngine (hub)."""

import pytest

from dspatch import Context, DspatchEngine


def test_run_without_decorator_raises():
    engine = DspatchEngine()
    with pytest.raises(RuntimeError, match="No agent function"):
        engine.run()


def test_decorator_registers_function():
    engine = DspatchEngine()

    @engine.agent(Context)
    async def my_fn(prompt, ctx):
        return prompt

    assert engine._agent_fn is my_fn


def test_decorator_returns_original_function():
    engine = DspatchEngine()

    @engine.agent(Context)
    async def my_fn(prompt, ctx):
        return prompt

    # The decorator should return the original function (passthrough).
    assert my_fn.__name__ == "my_fn"
