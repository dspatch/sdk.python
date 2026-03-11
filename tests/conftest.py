# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Shared fixtures for SDK tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Provide default env vars for all tests."""
    monkeypatch.setenv("DSPATCH_API_URL", "http://localhost:9999")
    monkeypatch.setenv("DSPATCH_API_KEY", "test-key-123")
    monkeypatch.setenv("DSPATCH_SESSION_ID", "test-session-456")
    monkeypatch.setenv("DSPATCH_WORKSPACE_ID", "test-workspace-456")
    monkeypatch.setenv("DSPATCH_RUN_ID", "test-run-789")
    monkeypatch.setenv("DSPATCH_AGENT_ID", "test-agent")
