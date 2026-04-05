# d:spatch Python Agent SDK

Python SDK for building containerized AI agents on the d:spatch orchestration platform. Published to PyPI as `dspatch-sdk`. Agents run inside Docker containers and communicate with the d:spatch-router over gRPC using protobuf-defined messages.

## Architecture

```
sdk.python/
├── dspatch/                          # Main package
│   ├── __init__.py                  # Public API exports
│   ├── engine.py                    # DspatchEngine — top-level entry point
│   ├── grpc_channel.py              # GrpcChannel — gRPC transport (Unix socket)
│   ├── agent_worker.py              # AgentWorker — runs agent function per turn
│   ├── models.py                    # Data classes (Message, InquiryResponse, TalkToResponse)
│   ├── errors.py                    # Exception types
│   ├── generated/                   # Protobuf-generated stubs (dspatch_router_pb2, _grpc)
│   ├── contexts/                    # Context implementations
│   │   ├── context.py               # Base Context — primary agent interface
│   │   ├── claude_context.py        # ClaudeAgentContext — Claude SDK integration
│   │   └── openai_context.py        # OpenAiAgentContext — OpenAI SDK integration
│   └── tools/                       # Pre-built reusable tools
│       ├── inquiry.py               # send_inquiry tool
│       └── agents.py                # Per-peer talk_to_<name> tools
├── tests/                           # Test suite
│   ├── conftest.py                  # Shared pytest fixtures
│   └── agents/                      # Test fixture agents
├── docs/
│   ├── guide.md
│   └── user_guide.md               # Comprehensive agent development guide
└── pyproject.toml                   # Project config, dependencies, version
```

### Layer boundaries

The SDK communicates with the dspatch-router (a Rust sidecar in the same container) over a Unix-domain gRPC socket. The router handles all external connectivity, buffering, and state management.

```
┌─────────────────────────────────────────────┐
│ Agent Function (user code)                  │
├─────────────────────────────────────────────┤
│ Context (log, inquire, talk_to, activity)   │
├─────────────────────────────────────────────┤
│ AgentWorker (runs agent fn per turn)        │
├─────────────────────────────────────────────┤
│ DspatchEngine (lifecycle, gRPC setup)       │
├─────────────────────────────────────────────┤
│ GrpcChannel (gRPC transport, Unix socket)   │
├─────────────────────────────────────────────┤
│ dspatch-router (Rust sidecar, external)     │
└─────────────────────────────────────────────┘
```

- **DspatchEngine** — Lifecycle only. Decorator-based agent registration, spawns worker.
- **GrpcChannel** — I/O only. gRPC connection management, protobuf serialization.
- **AgentWorker** — Execution only. Receives turns from router, creates Context, runs agent fn.
- **Context** — Agent interface only. No internal state management.

### Key classes

| Module | Class | Purpose |
|--------|-------|---------|
| `engine.py` | `DspatchEngine` | Decorator-based agent registration, logging setup, gRPC channel lifecycle |
| `grpc_channel.py` | `GrpcChannel` | gRPC transport over Unix socket, auth handshake, stream management |
| `agent_worker.py` | `AgentWorker` | Receives turns from router stream, creates Context, runs agent fn |
| `contexts/context.py` | `Context` | Primary agent interface: `log()`, `activity()`, `message()`, `inquire()`, `talk_to()` |
| `contexts/claude_context.py` | `ClaudeAgentContext` | Claude Agent SDK integration (MCP setup, response bridging) |
| `contexts/openai_context.py` | `OpenAiAgentContext` | OpenAI SDK integration (function calling setup) |

### Context API

`Context` is the interface agents use to interact with d:spatch. Key methods:

- `log(level, message)` — Structured logging (visible in app)
- `activity(description)` — Activity status updates
- `message(content, role)` — Send messages to the conversation
- `files(paths)` — Attach files
- `inquire(question, priority, timeout)` — Ask the user a question (blocks until answered)
- `talk_to(peer, message)` — Send a message to another agent (blocks until response)
- `prompt(text)` — Raw prompt passthrough

Context methods emit protobuf messages through the gRPC channel and block on `asyncio.Event` for responses where needed.

### Tools

Pre-built tools in `dspatch/tools/` are registered automatically by context implementations:

- **inquiry.py** — `send_inquiry` tool for agents to ask users questions
- **agents.py** — Auto-generates `talk_to_<peer>` tools from `DSPATCH_PEERS` env var

Tool specs are framework-specific: Claude uses MCP-prefixed names (`mcp__dspatch__`), OpenAI uses function calling format.

## Environment Variables

These are set by the d:spatch app when spawning agent containers. Agent code reads them automatically — developers don't set them manually.

| Variable | Purpose |
|----------|---------|
| `DSPATCH_GRPC_ADDR` | gRPC address for dspatch-router (default: 127.0.0.1:50051) |
| `DSPATCH_AGENT_KEY` | This agent's key (e.g. "lead", "coder") |
| `DSPATCH_AGENT_ID` | Full agent identifier for routing |
| `DSPATCH_AGENT_INSTANCE` | Instance index (for multi-instance agents) |
| `DSPATCH_PEERS` | Comma-separated list of peer agent keys |
| `DSPATCH_RUN_ID` | Workspace run identifier (routing key) |
| `DSPATCH_WORKSPACE_ID` | Workspace identifier (metadata) |
| `DSPATCH_SESSION_ID` | Session identifier (optional) |
| `DSPATCH_WORKSPACE_DIR` | Workspace directory (/workspace) |
| `DSPATCH_FIELD_*` | Base64-encoded template fields (system_prompt, authority, etc.) |

## Error Handling

- Custom exceptions in `errors.py`: `AgentError`, `DspatchApiError`, `InquiryTimeout`.
- Log errors with context via `logging.getLogger("dspatch.<module>")`.
- Handle `asyncio.CancelledError` explicitly in async tasks — don't let it propagate silently.

## Code Style

### Self-documenting code

- Write code that reads clearly without needing comments for basic logic.
- **Document architectural decisions** inline where relevant — the code serves as living documentation.
- **Document non-obvious bug fixes** — If a fix requires doing something unexpected or specific, add a comment explaining the reasoning and rationale. This prevents unintentional regressions.
- **`# TODO:`** — All unfinished work, known limitations, or planned improvements MUST be marked with a `# TODO:` comment.

### Conventions

- `from __future__ import annotations` in every file for forward references
- Type hints throughout (PEP 484). Use `TYPE_CHECKING` blocks for circular imports.
- `snake_case` for functions/variables, `UPPER_CASE` for module-level constants
- Private attributes/methods prefixed with `_`
- Grouped imports: standard library → third-party → local (relative)
- Module-level docstrings for every file
- Async/await throughout — use `asyncio.Queue` for inter-task communication, `asyncio.Event` for synchronization
- Copyright header: `# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.`

## Testing

**Framework:** pytest + pytest-asyncio

**Fixtures:** `tests/conftest.py` auto-sets `DSPATCH_*` env vars for all tests.

```bash
# Run all tests
py -m pytest tests/ -v

# Run specific test module
pytest tests/test_context_setup.py -v

# With coverage
pytest tests/ --cov=dspatch --cov-report=html
```

**Test categories:**
- **gRPC & Transport:** test_grpc_channel, test_proto_smoke
- **Engine:** test_engine_grpc
- **Worker:** test_agent_worker_grpc
- **Context:** test_context_setup, test_context_grpc, test_claude_context_run, test_openai_context_run

## Development Commands

```bash
# Install for development
pip install -e ".[dev]"

# Run tests
py -m pytest tests/ -v

# Version bumps (auto-commits and tags)
pip install bump-my-version
bump-my-version bump patch    # 0.1.0 → 0.1.1
bump-my-version bump minor    # 0.1.0 → 0.2.0

# Build distribution
pip install build
python -m build

# Push tags to trigger PyPI publish (GitHub Actions)
git push origin main --tags
```

## Git Rules

- **Commit after each logical unit of work** (usually one step in an implementation plan).
- **Use specific `git add`** — never `git add -A` or `git add .`.
- **NEVER sign commits as Claude** — no `Co-Authored-By` lines, no Claude attribution in commits.
- **Commit messages** — concise, imperative mood, describing what changed and why.

## Design Principles

- **No hacky solutions.** If an existing architecture or design doesn't fit, stop and re-evaluate. Refactor properly to account for the unexpected — don't patch around it.
- **Service boundaries** — Each layer has a single responsibility. Use async queues and events for loose coupling between layers.
- **Testable architecture** — Keep logic separated and mockable. Each layer can be tested in isolation with its neighbors stubbed.
- **YAGNI** — Don't build for hypothetical futures. Solve the current problem well.
- **Best practices always** — Apply SOLID principles, DRY (but don't over-abstract), and clean architecture patterns thoughtfully.
- **Refactor when needed** — If development reveals a miscalculation or misdesign, re-evaluate the architecture first. Then refactor to properly account for it before continuing.
