"""Tests for gRPC channel wrapper."""

import os
from unittest.mock import MagicMock, patch

from dspatch.grpc_channel import GrpcChannel


def test_reads_socket_from_env(monkeypatch):
    monkeypatch.setenv("DSPATCH_GRPC_SOCKET", "/tmp/test.sock")
    ch = GrpcChannel.__new__(GrpcChannel)
    ch._read_config()
    assert ch._socket_path == "/tmp/test.sock"


def test_default_socket_path(monkeypatch):
    monkeypatch.delenv("DSPATCH_GRPC_SOCKET", raising=False)
    ch = GrpcChannel.__new__(GrpcChannel)
    ch._read_config()
    assert ch._socket_path == "/tmp/dspatch.sock"


def test_reads_agent_env(monkeypatch):
    monkeypatch.setenv("DSPATCH_GRPC_SOCKET", "/tmp/test.sock")
    monkeypatch.setenv("DSPATCH_AGENT_KEY", "lead")
    monkeypatch.setenv("DSPATCH_AGENT_INSTANCE", "0")
    ch = GrpcChannel.__new__(GrpcChannel)
    ch._read_config()
    assert ch.agent_key == "lead"
    assert ch.instance_id == "lead-0"
