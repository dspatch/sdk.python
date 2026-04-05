# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""GrpcChannel — gRPC connection to the container-local dspatch-router.

Replaces WsClient. Provides a stub for calling DspatchRouter RPCs.
"""

from __future__ import annotations

import os
import logging

import grpc

from .generated import dspatch_router_pb2_grpc

logger = logging.getLogger("dspatch.grpc")


class GrpcChannel:
    """Manages the gRPC channel and stub for communicating with dspatch-router."""

    def __init__(self) -> None:
        self._read_config()
        self._channel: grpc.aio.Channel | None = None
        self._stub: dspatch_router_pb2_grpc.DspatchRouterStub | None = None

    def _read_config(self) -> None:
        self._grpc_addr = os.environ.get("DSPATCH_GRPC_ADDR", "127.0.0.1:50051")
        self.agent_key = os.environ.get("DSPATCH_AGENT_KEY", "unknown")
        instance_index = os.environ.get("DSPATCH_AGENT_INSTANCE", "0")
        self.instance_id = f"{self.agent_key}-{instance_index}"
        self.workspace_dir = os.environ.get("DSPATCH_WORKSPACE_DIR", "/workspace")

    async def connect(self) -> None:
        """Open gRPC channel to the router."""
        self._channel = grpc.aio.insecure_channel(self._grpc_addr)
        self._stub = dspatch_router_pb2_grpc.DspatchRouterStub(self._channel)
        logger.info("Connected to router at %s", self._grpc_addr)

    async def disconnect(self) -> None:
        """Close gRPC channel."""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None

    @property
    def stub(self) -> dspatch_router_pb2_grpc.DspatchRouterStub:
        """Get the gRPC stub. Raises if not connected."""
        if self._stub is None:
            raise RuntimeError("GrpcChannel not connected. Call connect() first.")
        return self._stub
