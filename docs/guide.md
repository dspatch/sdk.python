# dspatch Python SDK — User Guide

The dspatch SDK lets you build agents that run inside Docker containers and communicate with the dspatch desktop app. This guide covers all SDK features and patterns.

## Installation

```bash
pip install dspatch-sdk
```

Or add to your agent's `pyproject.toml`:

```toml
[project]
dependencies = ["dspatch"]
```

## Quick Start

```python
from dspatch import DspatchEngine

dspatch = DspatchEngine()

@dspatch.agent(Context)
async def my_agent(prompt: str, ctx):
    ctx.log(f"Received: {prompt}")
    return f"Echo: {prompt}"

dspatch.run()
```

The `@dspatch.agent(ContextClass)` decorator registers your handler function with a context type. `dspatch.run()` starts the SDK event loop (blocking). It connects to the dspatch app, listens for user messages via SSE, and dispatches each message to your handler. At launch, we support `ClaudeAgentContext` for Claude Agent SDK integration and `OpenAiAgentContext` for OpenAI

## Agent Modes

The SDK supports two agent patterns, auto-detected at startup via `inspect.isasyncgenfunction()`. No configuration needed — just add a `yield` and it switches from one-shot to persistent.

### One-Shot Agents

A regular `async def` that processes one message at a time. Each message creates a fresh invocation — no state is shared between messages.

```python
@dspatch.agent(Context)
async def my_agent(prompt: str, ctx):
    # Process the prompt, return a response.
    result = await do_work(prompt)
    return result
```

**When to use:** Simple stateless agents, quick tasks, agents that don't need conversation context.

**Behavior:**
- Function is called once per user message.
- A new context is created for each call, with the current conversation history available via `ctx.messages`.
- Returning a string auto-sends it as an assistant message (unless `ctx.message()` was already called).
- Exceptions set the session status to `failed` and stop the runner.

### Persistent Agents (Generators)

An `async def` with `yield` — the function stays alive across messages, naturally preserving state and conversation context.

```python
@dspatch.agent(Context)
async def my_agent(prompt: str, ctx):
    # One-time setup (runs only once).
    client = setup_llm_client()

    try:
        while True:
            response = await client.chat(prompt)

            # Yield to suspend — runner feeds next message via asend().
            prompt = yield response
            if prompt is None:
                break
    finally:
        # Cleanup when generator exits.
        await client.close()
```

**When to use:** Agents that wrap LLM clients (Claude, GPT, etc.) and need conversation continuity across messages.

**How it works:**

1. **First message:** The runner calls `gen = handle(prompt, ctx)` then `await gen.asend(None)`, which runs your code until the first `yield`.
2. **Subsequent messages:** The runner calls `await gen.asend(new_prompt)`, which resumes from the `yield` with `prompt` set to the new message.
3. **The initial prompt** comes from the function argument. Subsequent prompts come from the `yield` expression.

**Yielded values:**
- If you yield a non-empty string and haven't called `ctx.message()` during the turn, the string is auto-sent as an assistant message.
- If you already sent messages via `ctx.message()`, the yielded value is ignored.
- Yield `None` or an empty string to skip auto-sending.

**Lifecycle:**
- `StopAsyncIteration` (generator finishes naturally) — the runner cleans up and can create a new generator on the next message.
- Exceptions — the runner sets status to `failed` and stops.
- `finally` blocks run on generator cleanup, so use them for resource teardown.

**Per-turn state reset:** The `_message_sent` flag on the context is reset between turns, so auto-send logic works correctly for each message.

## Resume Handling

When a container restarts with an existing session, the SDK detects the resume state and can recover gracefully.

### `@dspatch.on_resume` Decorator

Register an optional handler that runs on container restart. It receives a `ResumeContext` and should return a prompt string (fed to the `@dspatch.agent` handler) or `None` to wait for new input.

```python
@dspatch.on_resume
async def resume(ctx):
    # ctx is a ResumeContext with:
    #   .status       — session status before restart
    #   .messages     — full conversation history (list[Message])
    #   .last_user_message — shortcut to last user-role message (str | None)
    #   .pending_inquiry   — inquiry being waited on (PendingInquiry | None)

    if ctx.pending_inquiry:
        resp = await ctx.pending_inquiry.wait(client)
        return f"User responded: {resp.text}"

    return ctx.last_user_message  # replay last input
```

If no `on_resume` handler is registered, the runner applies sensible defaults:
- **`waitingForInquiry` + pending inquiry:** Watch the inquiry via SSE and return the response.
- **`waitingForInput`:** Return `None` (wait for new input).
- **Otherwise:** Replay `last_user_message`.

### ResumeContext

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | Session status before restart |
| `messages` | `list[Message]` | Full conversation history |
| `last_user_message` | `str \| None` | Shortcut to the last user-role message |
| `pending_inquiry` | `PendingInquiry \| None` | The inquiry the agent was waiting for (if any) |

### Message

A single conversation message in the history.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique message identifier |
| `role` | `str` | `"user"` or `"assistant"` |
| `content` | `str` | Message text |

### PendingInquiry

A pending inquiry that can be waited on across container restarts.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Inquiry identifier |
| `content_markdown` | `str` | The question / context markdown |
| `is_resolved` | `bool` | Whether the user has responded |
| `response` | `InquiryResponse \| None` | The response (if already resolved) |

**Method:** `async def wait(client) -> InquiryResponse` — Watch via SSE until the user responds. Returns immediately if already resolved.

## Context API

The `ctx` object provides all communication with the dspatch app. Specialized contexts (`ClaudeAgentContext`, `OpenAiAgentContext`) extend the base `Context` with `setup()`, `run()`, and async context manager support for their respective SDK clients.

### Constructor

```python
Context(client, ingester, messages=None)
```

- `messages` is a `list[Message]` with the current conversation history, updated by the runner each turn (for generators, the runner sets `ctx.messages = messages` before each `asend()`).

### Buffered Methods (Non-Blocking)

These buffer data locally and flush to the app periodically (every 2 seconds) or when buffer thresholds are hit.

#### `ctx.log(message, level="info")`

Append a log entry visible in the session's Logs tab.

```python
ctx.log("Starting analysis...")
ctx.log("Something went wrong", level="error")
```

Levels: `debug`, `info`, `warn`, `error`.

#### `ctx.activity(event_type, description="", metadata=None)`

Record an activity event visible in the session's Activity tab.

```python
ctx.activity("file_read", "Read config.yaml", {"path": "/workspace/config.yaml"})
ctx.activity("tool_call", "Running tests", {"tool": "Bash"})
```

#### `ctx.usage(model, input_tokens, output_tokens, cost_usd=0.0, **kwargs)`

Record token usage for an LLM call, visible in the Usage tab.

```python
ctx.usage(
    model="claude-sonnet-4-5-20250929",
    input_tokens=1500,
    output_tokens=800,
    cost_usd=0.012,
)
```

#### `ctx.files(file_list)`

Record file operations.

```python
ctx.files([
    {"file_path": "/workspace/src/main.py", "operation": "write"},
    {"file_path": "/workspace/tests/test_main.py", "operation": "write"},
])
```

### Direct Methods (Blocking HTTP)

These make immediate HTTP calls to the dspatch app.

#### `ctx.message(content, role="assistant", is_partial=False, message_id=None, **kwargs)`

Send a message to the user. Returns the message ID (a `str`).

```python
# Simple response
msg_id = await ctx.message("Here's what I found...")

# Streaming (partial messages)
msg_id = await ctx.message("Working", is_partial=True)
msg_id = await ctx.message("Working on it...", is_partial=True, message_id=msg_id)
await ctx.message("Done! Here's the result.", is_partial=False, message_id=msg_id)
```

**Partial messages:** Set `is_partial=True` for streaming. Pass the same `message_id` to update the message in-place. Set `is_partial=False` on the final update to finalize.

**Auto-send:** If the agent returns/yields a string and `ctx.message()` was never called during that turn, the runner auto-sends the string as a final message. Once you call `ctx.message()`, auto-send is suppressed.

#### `ctx.inquire(content_markdown, suggestions=None, file_paths=None, priority="normal", timeout_hours=72)`

Post an inquiry to the user and block until they respond. Returns an `InquiryResponse`.

```python
response = await ctx.inquire(
    content_markdown="## Which approach should I use?\n\nOption A is faster...",
    suggestions=[
        "Use approach A (faster)",
        "Use approach B (safer)",
    ],
    file_paths=["/workspace/src/main.py"],
    priority="normal",
    timeout_hours=72,
)

print(response.text)              # The user's response text
print(response.suggestion_index)  # Index of selected suggestion (or None)
```

**Parameters:**
- `content_markdown` — Markdown-formatted context for the decision.
- `suggestions` — 2-4 options. Each can be a plain string or `{"text": "...", "is_recommended": True}`. Exactly one may be marked as recommended.
- `file_paths` — Container-local paths to stream to the app for context (e.g. `["/workspace/src/main.py"]`).
- `priority` — `"normal"` or `"high"`.
- `timeout_hours` — Maximum hours to wait (default 72). Raises `InquiryTimeout` if exceeded.

### InquiryResponse

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str \| None` | The user's text response |
| `suggestion_index` | `int \| None` | Index of selected suggestion (or `None` if freeform) |

## Error Types

### `DspatchApiError`

Raised when an engine HTTP API call fails.

```python
from dspatch import DspatchApiError

try:
    await ctx.message("hello")
except DspatchApiError as e:
    print(e.status_code)  # HTTP status code (int)
    print(e.detail)       # Error detail (str)
```

### `InquiryTimeout`

Raised when an inquiry times out without a response.

```python
from dspatch import InquiryTimeout

try:
    response = await ctx.inquire("Pick one:", suggestions=["A", "B"])
except InquiryTimeout:
    ctx.log("User didn't respond in time", level="warn")
```

### `AgentError`

Raised when the agent function throws.

## Environment Variables

The SDK reads these from the container environment (set by the dspatch app):

| Variable | Description |
|----------|-------------|
| `DSPATCH_API_URL` | Base URL of the dspatch embedded server |
| `DSPATCH_API_KEY` | Per-session authentication key |
| `DSPATCH_SESSION_ID` | Current session identifier |

## Lifecycle & Status Flow

```
Container starts
    |
    v
Runner.start()
    +- Fetch context (retries until host available)
    +- Detect resume (status != "idle" + messages exist)
    +- status -> "running"
    +- Start ingester (flush every 2s)
    +- Start heartbeat loop (every 30s)
    |
    +- [If resume] Run on_resume handler or defaults
    |   +- If prompt returned -> dispatch to agent
    |   +- If None returned -> skip to waitingForInput
    |
    +- status -> "waitingForInput"
    |
    v
Input loop (SSE stream)
    +- Receive user message
    +- Fetch current conversation context
    +- status -> "running"
    +- Invoke agent function (one-shot or generator)
    +- status -> "waitingForInput"
    +- (repeat)

Error -> status -> "failed" -> runner stops
Heartbeat returns "completed"/"failed" -> runner stops
Heartbeat returns "disconnected" -> re-assert current status
SIGTERM/SIGINT -> graceful shutdown
```

## Heartbeat

The runner sends heartbeats every 30 seconds via `POST /engine/heartbeat`. The heartbeat response carries the current session status:
- **Terminal status** (`completed` or `failed`) — the runner stops gracefully.
- **`disconnected`** — the runner re-asserts its current status to the host.
- **Otherwise** — no action.

## Error Handling

- **Agent exceptions:** Logged, status set to `failed`, runner stops.
- **SSE stream drops:** Automatic reconnection with exponential backoff (2s -> 4s -> 8s -> ... -> 30s max).
- **Ingester flush failures:** Data retained in buffer for the next attempt.
- **Generator errors:** Generator is cleaned up, error logged to context, status set to `failed`.
- **HTTP client failures:** Up to 5 retries with exponential backoff (2s -> 4s -> 8s -> 16s -> 30s) on `ConnectError` and `TimeoutException`.

## Ingester (Telemetry Buffering)

Buffered methods (`log`, `activity`, `usage`, `files`) are collected by the `Ingester` and flushed:
- Every 2 seconds (periodic timer).
- When buffer thresholds are exceeded (50 logs, 20 activities, 10 usage records, 20 files).
- On shutdown (final flush).

If a flush fails, data is retained in the buffers for the next attempt. Buffers are only cleared after a successful send.

## Input Deduplication

The SSE input stream deduplicates messages by ID (`self._seen_input_ids`). If the stream reconnects, previously seen messages are not re-processed. The server also seeds a consumed set on connection to avoid replaying history.

## Docker-Bundled SDK

A copy of the SDK lives at `app/assets/docker/sdk/dspatch/` and is bundled into agent containers. Changes to `packages/dspatch-sdk/dspatch/` must be mirrored there.

## Pre-Built Tools (`dspatch.tools`)

The SDK provides pre-built tools with framework-specific adapters so you don't have to define tool schemas, handlers, or error handling yourself. The core tool logic is defined once; specialized contexts (`ClaudeAgentContext`, `OpenAiAgentContext`) wire everything up automatically.

```
dspatch/tools/
+-- inquiry.py    # Core: NAME, DESCRIPTION, SCHEMA, execute()
+-- claude.py     # Claude Agent SDK adapter (internal)
+-- openai.py     # OpenAI adapter (internal)
```

### How Tools Work with Specialized Contexts

When you use `ClaudeAgentContext` or `OpenAiAgentContext`, the dspatch tools (e.g. `send_inquiry`) are set up automatically during `async with ctx:`. You do not need to import or call the tool adapters directly.

- **`ClaudeAgentContext`** — creates an MCP server with all dspatch tools, injects it into the Claude SDK client options, and handles the response stream (streaming messages, activity logging, usage tracking) inside `run()`.
- **`OpenAiAgentContext`** — injects OpenAI-compatible function definitions into the chat completions call and dispatches tool calls inside `run()`.

The adapter functions (`_create_dspatch_tools`, `_process_response_stream`, `_get_tool_definitions`, `_handle_tool_call`) are now internal/private and called automatically by the context lifecycle methods.

### Core Tool Definitions

For frameworks without a specialized context, use the core definitions directly:

```python
from dspatch.tools import INQUIRY_NAME, INQUIRY_DESCRIPTION, INQUIRY_SCHEMA, execute_inquiry

# Build your own tool definition using the constants.
# Call execute_inquiry(ctx, args) to run the tool.
```

### Included Tools

#### `send_inquiry`

Ask the user a question with 2-4 suggested options. Blocks until the user responds (up to 72 hours).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `markdown` | `str` | Yes | Markdown context for the decision |
| `suggestions` | `list[str]` | Yes | 2-4 options (first = recommended) |
| `files` | `list[str]` | No | Absolute file paths for user review |

## Full Example: Claude Agent SDK

```python
from claude_agent_sdk import ClaudeAgentOptions
from dspatch import ClaudeAgentContext, DspatchEngine

dspatch = DspatchEngine()

SYSTEM_PROMPT = "You are an autonomous coding agent..."

@dspatch.agent(ClaudeAgentContext)
async def my_agent(prompt: str, ctx: ClaudeAgentContext):
    ctx.setup(
        system_prompt=SYSTEM_PROMPT,
        options=ClaudeAgentOptions(
            model="claude-haiku-4-5-20251001",
            max_turns=200,
        ),
    )
    async with ctx:
        while True:
            try:
                await ctx.run(prompt)
            except Exception as e:
                ctx.log(f"Error: {e}", level="error")
            prompt = yield
            if prompt is None:
                break

dspatch.run()
```

## Full Example: OpenAI

```python
from dspatch import OpenAiAgentContext, DspatchEngine

dspatch = DspatchEngine()

SYSTEM_PROMPT = "You are an autonomous coding agent..."

@dspatch.agent(OpenAiAgentContext)
async def my_agent(prompt: str, ctx: OpenAiAgentContext):
    ctx.setup(system_prompt=SYSTEM_PROMPT)
    async with ctx:
        while True:
            try:
                await ctx.run(prompt)
            except Exception as e:
                ctx.log(f"Error: {e}", level="error")
            prompt = yield
            if prompt is None:
                break

dspatch.run()
```

## Full Example: Manual Streaming (No Adapter)

For custom streaming behavior, skip the specialized contexts and use the base `Context` directly:

```python
from dspatch import Context, DspatchEngine

dspatch = DspatchEngine()

@dspatch.agent(Context)
async def my_agent(prompt: str, ctx: Context):
    client = setup_llm_client()

    try:
        while True:
            response = await client.chat(prompt)
            msg_id = await ctx.message(response, is_partial=True)
            await ctx.message(response, is_partial=False, message_id=msg_id)
            ctx.usage(model="...", input_tokens=1500, output_tokens=800, cost_usd=0.012)

            prompt = yield
            if prompt is None:
                break
    finally:
        await client.close()

dspatch.run()
```

## DIY / Advanced

If you need full control over the SDK client lifecycle, you can skip `setup()` / `async with ctx:` / `run()` entirely and manage the client yourself. Use the base `Context` (or a specialized context without calling its lifecycle methods) and interact with the dspatch app through the base context methods directly:

- `ctx.message()` — send messages to the user
- `ctx.log()` — log entries
- `ctx.activity()` — record activity events
- `ctx.usage()` — record token usage
- `ctx.files()` — record file operations
- `ctx.inquire()` — post an inquiry and wait for a response

This is useful when:
- You are integrating an LLM framework that has no specialized context yet.
- You need custom streaming logic that `run()` does not support.
- You want to call multiple LLM providers in a single agent.

```python
from dspatch import Context, DspatchEngine

dspatch = DspatchEngine()

@dspatch.agent(Context)
async def my_agent(prompt: str, ctx: Context):
    # Manage your own client, call ctx methods directly.
    client = MyCustomLLMClient()
    response = await client.generate(prompt)
    await ctx.message(response)
    ctx.usage(model="custom-model", input_tokens=100, output_tokens=50)
```

## Public API Reference

### Exports from `dspatch`

| Export | Type | Description |
|--------|------|-------------|
| `DspatchEngine` | Class | Entry point with `@dspatch.agent(ContextClass)`, `@dspatch.on_resume`, and `run()` |
| `Context` | Class | Base context object passed to agent handlers |
| `ClaudeAgentContext` | Class | Specialized context for Claude Agent SDK (`setup`, `run`, `async with`) |
| `OpenAiAgentContext` | Class | Specialized context for OpenAI (`setup`, `run`, `async with`) |
| `Message` | Dataclass | Conversation message (`id`, `role`, `content`) |
| `ResumeContext` | Dataclass | Resume state after container restart |
| `InquiryResponse` | Dataclass | User's response to an inquiry |
| `PendingInquiry` | Dataclass | A pending inquiry that can be waited on |
| `DspatchApiError` | Exception | HTTP API call failure |
| `InquiryTimeout` | Exception | Inquiry timed out without response |
| `AgentError` | Exception | Agent function threw an exception |

### Specialized Context API

These methods are available on `ClaudeAgentContext` and `OpenAiAgentContext`:

| Method / Property | Description |
|-------------------|-------------|
| `setup(*, system_prompt, options=None)` | Configure the context before use. `options` is framework-specific (e.g. `ClaudeAgentOptions`). |
| `async with ctx:` | Initialize the SDK client and dspatch tools; clean up on exit. |
| `run(prompt)` | Execute one turn — send the prompt, stream the response, handle tool calls. |
| `client` | Property exposing the raw SDK client (available inside `async with ctx:`). |

### Internal / Private Methods

The following functions from `dspatch.tools.claude` and `dspatch.tools.openai` are now internal and called automatically by the specialized context lifecycle. They should not be imported or called directly:

| Old Public Function | Now Internal | Called By |
|---------------------|-------------|-----------|
| `create_dspatch_tools(ctx)` | `_create_dspatch_tools` | `__aenter__` |
| `process_response_stream(ctx, client)` | `_process_response_stream` | `run()` |
| `get_tool_definitions()` | `_get_tool_definitions` | `__aenter__` |
| `handle_tool_call(ctx, name, args)` | `_handle_tool_call` | `run()` |
| `ctx.augment_system_prompt(prompt)` | `_augment_system_prompt` | `__aenter__` |

### Exports from `dspatch.tools`

| Export | Type | Description |
|--------|------|-------------|
| `INQUIRY_NAME` | `str` | Tool name (`"send_inquiry"`) |
| `INQUIRY_DESCRIPTION` | `str` | Tool description for LLMs |
| `INQUIRY_SCHEMA` | `dict` | JSON Schema for tool parameters |
| `execute_inquiry` | `async fn` | Core tool executor `(ctx, args) -> dict` |
