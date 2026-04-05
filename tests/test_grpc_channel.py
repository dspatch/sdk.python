"""Tests for gRPC channel wrapper."""

import os
from unittest.mock import MagicMock, patch

from dspatch.grpc_channel import GrpcChannel


def test_reads_addr_from_env(monkeypatch):
    monkeypatch.setenv("DSPATCH_GRPC_ADDR", "10.0.0.1:9999")
    ch = GrpcChannel.__new__(GrpcChannel)
    ch._read_config()
    assert ch._grpc_addr == "10.0.0.1:9999"


def test_default_grpc_addr(monkeypatch):
    monkeypatch.delenv("DSPATCH_GRPC_ADDR", raising=False)
    ch = GrpcChannel.__new__(GrpcChannel)
    ch._read_config()
    assert ch._grpc_addr == "127.0.0.1:50051"


def test_reads_agent_env(monkeypatch):
    monkeypatch.setenv("DSPATCH_GRPC_ADDR", "127.0.0.1:50051")
    monkeypatch.setenv("DSPATCH_AGENT_KEY", "lead")
    monkeypatch.setenv("DSPATCH_AGENT_INSTANCE", "0")
    ch = GrpcChannel.__new__(GrpcChannel)
    ch._read_config()
    assert ch.agent_key == "lead"
    assert ch.instance_id == "lead-0"
