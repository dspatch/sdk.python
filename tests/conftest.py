# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Shared fixtures for SDK tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Provide default env vars for all tests."""
    monkeypatch.setenv("DSPATCH_GRPC_ADDR", "127.0.0.1:50051")
    monkeypatch.setenv("DSPATCH_AGENT_KEY", "test-agent")
    monkeypatch.setenv("DSPATCH_AGENT_INSTANCE", "0")
    monkeypatch.setenv("DSPATCH_SESSION_ID", "test-session-456")
    monkeypatch.setenv("DSPATCH_WORKSPACE_ID", "test-workspace-456")
    monkeypatch.setenv("DSPATCH_WORKSPACE_DIR", "/workspace")
