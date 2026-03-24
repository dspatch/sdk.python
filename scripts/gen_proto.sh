#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK_DIR="$(dirname "$SCRIPT_DIR")"
PROTO_DIR="$(cd "$SDK_DIR/../../../packages/dspatch-router/proto" 2>/dev/null || cd "$SDK_DIR/../../../../packages/dspatch-router/proto" && pwd)"
OUT_DIR="$SDK_DIR/dspatch/generated"

mkdir -p "$OUT_DIR"

${PYTHON:-python} -m grpc_tools.protoc \
    --proto_path="$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    --pyi_out="$OUT_DIR" \
    dspatch_router.proto

# Fix relative imports in generated gRPC file
# grpc_tools generates `import dspatch_router_pb2` but we need `from . import dspatch_router_pb2`
sed -i 's/^import dspatch_router_pb2/from . import dspatch_router_pb2/' "$OUT_DIR/dspatch_router_pb2_grpc.py"

echo "Proto codegen complete: $OUT_DIR"
