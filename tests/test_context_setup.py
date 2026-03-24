# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Tests for Context setup / run / context manager stubs."""

import asyncio
import base64
import os
from unittest.mock import MagicMock, AsyncMock
import pytest
from dspatch.contexts import Context
from dspatch.generated import dspatch_router_pb2


def _make_ctx():
    """Create a Context with a mock GrpcChannel for testing."""
    channel = MagicMock()
    channel.agent_key = "test"
    channel.instance_id = "test-0"
    channel.stub = MagicMock()
    channel.stub.SendOutput = AsyncMock(
        return_value=dspatch_router_pb2.Ack(ok=True)
    )
    return Context(channel=channel, instance_id="test-0", turn_id="turn-1", messages=[])


class TestContextStubs:
    def test_setup_stores_values(self):
        ctx = _make_ctx()
        ctx.setup(system_prompt="hello", authority="full", options={"model": "x"})
        assert ctx._user_system_prompt == "hello"
        assert ctx._user_authority == "full"
        assert ctx._user_options == {"model": "x"}

    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        ctx = _make_ctx()
        with pytest.raises(NotImplementedError):
            await ctx.run("hello")

    @pytest.mark.asyncio
    async def test_context_manager_without_setup_raises(self):
        ctx = _make_ctx()
        with pytest.raises(RuntimeError, match="setup.*before"):
            async with ctx:
                pass

    def test_existing_methods_still_work(self):
        """Existing platform methods are unaffected by new stubs."""
        ctx = _make_ctx()
        # log() should not raise
        ctx.log("test message")


class TestFieldFallback:
    def test_read_field_decodes_base64(self):
        ctx = _make_ctx()
        os.environ["DSPATCH_FIELD_SYSTEM_PROMPT"] = base64.b64encode(b"Hello world").decode()
        try:
            assert ctx._read_field("system_prompt") == "Hello world"
        finally:
            del os.environ["DSPATCH_FIELD_SYSTEM_PROMPT"]

    def test_read_field_returns_none_when_missing(self):
        ctx = _make_ctx()
        os.environ.pop("DSPATCH_FIELD_NONEXISTENT", None)
        assert ctx._read_field("nonexistent") is None

    def test_setup_falls_back_to_env_system_prompt(self):
        ctx = _make_ctx()
        os.environ["DSPATCH_FIELD_SYSTEM_PROMPT"] = base64.b64encode(b"From env").decode()
        try:
            ctx.setup()
            assert ctx._user_system_prompt == "From env"
        finally:
            del os.environ["DSPATCH_FIELD_SYSTEM_PROMPT"]

    def test_setup_falls_back_to_env_authority(self):
        ctx = _make_ctx()
        os.environ["DSPATCH_FIELD_AUTHORITY"] = base64.b64encode(b"May fix bugs").decode()
        try:
            ctx.setup()
            assert ctx._user_authority == "May fix bugs"
        finally:
            del os.environ["DSPATCH_FIELD_AUTHORITY"]

    def test_setup_explicit_overrides_env(self):
        ctx = _make_ctx()
        os.environ["DSPATCH_FIELD_SYSTEM_PROMPT"] = base64.b64encode(b"From env").decode()
        os.environ["DSPATCH_FIELD_AUTHORITY"] = base64.b64encode(b"From env auth").decode()
        try:
            ctx.setup(system_prompt="Explicit prompt", authority="Explicit auth")
            assert ctx._user_system_prompt == "Explicit prompt"
            assert ctx._user_authority == "Explicit auth"
        finally:
            del os.environ["DSPATCH_FIELD_SYSTEM_PROMPT"]
            del os.environ["DSPATCH_FIELD_AUTHORITY"]

    def test_setup_empty_string_falls_through(self):
        ctx = _make_ctx()
        os.environ["DSPATCH_FIELD_SYSTEM_PROMPT"] = base64.b64encode(b"Fallback").decode()
        try:
            ctx.setup(system_prompt="")
            assert ctx._user_system_prompt == "Fallback"
        finally:
            del os.environ["DSPATCH_FIELD_SYSTEM_PROMPT"]

    def test_read_field_handles_invalid_base64(self):
        ctx = _make_ctx()
        os.environ["DSPATCH_FIELD_BAD"] = "not-valid-base64!!!"
        try:
            assert ctx._read_field("bad") is None
        finally:
            del os.environ["DSPATCH_FIELD_BAD"]

    def test_read_field_handles_unicode(self):
        ctx = _make_ctx()
        text = "You are a 日本語 assistant 🤖"
        os.environ["DSPATCH_FIELD_TEST"] = base64.b64encode(text.encode("utf-8")).decode()
        try:
            assert ctx._read_field("test") == text
        finally:
            del os.environ["DSPATCH_FIELD_TEST"]
