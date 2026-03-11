# d:spatch SDK — User Guide

Build agents that run inside d:spatch workspace containers. This guide covers everything you need to integrate your own agents, models, and stacks.

## Table of Contents

- [Agent Template Config](#agent-template-config)
- [Using ClaudeAgentContext](#using-claudecontext)
  - [System Prompt & Authority](#system-prompt--authority)
- [Using OpenAiAgentContext](#using-openaicontext)
  - [System Prompt & Authority](#system-prompt--authority-1)
- [Using Any Custom LLM / Framework](#using-any-custom-llm--framework)
  - [System Prompt & Authority](#system-prompt--authority-2)
- [Context API Reference](#context-api-reference)
- [Agent Lifecycle](#agent-lifecycle)

---

## Agent Template Config

Every agent template lives in its own directory and must contain a `dspatch.agent.yml` file. This is the only accepted config filename.

### Directory Structure

```
my-agent/
├── dspatch.agent.yml      # Agent config (required)
├── agent.py                # Entry point (Python)
├── README.md               # Documentation
├── pyproject.toml          # Auto-installed python dependencies (uv/pip)
├── requirements.txt        # Alternative dependency file
└── scripts/
    ├── post_install.sh     # Optional install hook
    └── pre_install.sh      # Optional install hook
```

### `dspatch.agent.yml` Reference

```yaml
name: My Custom Agent
description: A brief description of what this agent does.
entry_point: agent.py
readme: README.md
pre_install: ./scripts/pre_install.sh
post_install: ./scripts/post_install.sh
fields:
  system_prompt: WW91IGFyZSBhIGhlbHBmdWwgY29kaW5nIGFzc2lzdGFudC4=
  authority: WW91IG1heSBmcmVlbHkgcmVmYWN0b3IgY29kZSBhbmQgZml4IGJ1Z3Mu
required_env:
  - ANTHROPIC_API_KEY
  - MY_CUSTOM_VAR
required_mounts:
  - /root/.claude/.credentials.json
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | — | Display name in the app |
| `description` | string | Yes | — | Short description of the agent's purpose |
| `entry_point` | string | No | `agent.py` | Python file to execute |
| `readme` | string | No | auto-detected | Path to README file |
| `pre_install` | string | No | — | Shell script to run before dependency installation |
| `post_install` | string | No | — | Shell script to run after dependency installation |
| `fields` | map | No | `{}` | Base64-encoded key-value pairs (see [Template Fields](#template-fields)) |
| `required_env` | list | No | — | Environment variable keys this agent needs |
| `required_mounts` | list | No | — | Container paths that must be bind-mounted from the host |

### Environment Variables

Environment variables are resolved through three layers at container startup:

1. **System variables** (set by d:spatch, cannot be overridden) — all prefixed with `DSPATCH_`.
2. **Workspace-level variables** — defined in `dspatch.workspace.yml` under the `env` key.
3. **Per-agent overrides** — defined in `dspatch.workspace.yml` under `agents.<name>.env`.

Per-agent values take priority over workspace-level defaults.

**Important:** Only keys listed in your template's `required_env` are forwarded to the container. If your agent needs `ANTHROPIC_API_KEY`, you must declare it to enforce it during workspace creation:

```yaml
required_env:
  - ANTHROPIC_API_KEY
```

The d:spatch app reads `required_env` when a workspace uses your template and prompts the user to supply values (or link them to stored secrets). Inside your agent code, access them with `os.environ`:

```python
import os
api_key = os.environ["OPENAI_API_KEY"]
```

#### System Variables (Available Automatically)

These are set by d:spatch and available to every agent — you do not need to declare them in `required_env`:

| Variable | Description |
|----------|-------------|
| `DSPATCH_AGENT_KEY` | This agent's key within the workspace |
| `DSPATCH_AGENT_INSTANCE` | Instance index (for multi-instance agents) |
| `DSPATCH_AGENT_ID` | Full agent identifier |
| `DSPATCH_PEERS` | Comma-separated list of peer agent keys |
| `DSPATCH_WORKSPACE_DIR` | Workspace directory inside the container |
| `DSPATCH_FIELD_*` | Base64-encoded template field values (decoded by SDK) |

### Required Mounts

Use `required_mounts` to declare container paths that must be bind-mounted from the host. The app prompts users to specify the host path for each mount.

Common example — Claude CLI credentials:

```yaml
required_mounts:
  - /root/.claude/.credentials.json
```

### Template Fields

Use `fields` to embed base64-encoded configuration values directly in your agent template. These are exposed to the agent process as `DSPATCH_FIELD_<KEY>` environment variables (key uppercased, value is the raw base64 string).

The Python SDK automatically decodes two well-known fields as defaults for `ctx.setup()`:

| Field Key | Env Var | SDK Behavior |
|-----------|---------|-------------|
| `system_prompt` | `DSPATCH_FIELD_SYSTEM_PROMPT` | Used as default `system_prompt` in `ctx.setup()` |
| `authority` | `DSPATCH_FIELD_AUTHORITY` | Used as default `authority` in `ctx.setup()` |

Explicit arguments to `ctx.setup()` always override env var defaults.

#### Encoding Values

Values must be base64-encoded UTF-8 strings. On the command line:

```bash
echo -n "You are a helpful coding assistant." | base64
# Output: WW91IGFyZSBhIGhlbHBmdWwgY29kaW5nIGFzc2lzdGFudC4=
```

#### Example

```yaml
fields:
  system_prompt: WW91IGFyZSBhIGhlbHBmdWwgY29kaW5nIGFzc2lzdGFudC4=
  authority: WW91IG1heSBmcmVlbHkgcmVmYWN0b3IgY29kZS4=
```

With this config, agents using this template can call `ctx.setup()` without arguments and still get the system prompt and authority from the template:

```python
ctx.setup()  # Uses system_prompt and authority from template fields
```

Or override selectively:

```python
ctx.setup(system_prompt="Custom prompt")  # Overrides template, keeps authority from template
```

### Dependencies

The container runtime installs dependencies automatically:

| File | Install Command |
|------|----------------|
| `pyproject.toml` | `uv sync --no-dev` |
| `requirements.txt` | `pip install -r requirements.txt` |
| `package.json` | `npm install` (or pnpm/yarn if lockfile present) |

---

## Using ClaudeAgentContext

`ClaudeAgentContext` integrates with the **Claude Agent SDK** (`claude_agent_sdk`). It wraps Claude Code's CLI client, automatically wires up d:spatch platform tools as an MCP server, and bridges the response stream (streaming messages, tool-use activity, thinking blocks, token usage) back to the d:spatch app.

### Authentication

Claude Agent SDK uses **Claude Code CLI sessions** for authentication — there is no API key involved. We recommend mounting the credentials file from your host machine into the container.

In your `dspatch.agent.yml`:

```yaml
required_mounts:
  - /root/.claude/.credentials.json
```

When creating a workspace, d:spatch prompts you for the host path. On most systems, this is `~/.claude/.credentials.json`. If you have an active Claude Code session on your host, the containerized agent inherits it.

### Minimal Example

```python
from claude_agent_sdk import ClaudeAgentOptions
from dspatch import ClaudeAgentContext, DspatchEngine

dspatch = DspatchEngine()

@dspatch.agent(ClaudeAgentContext)
async def my_agent(prompt: str, ctx: ClaudeAgentContext):
    ctx.setup(
        system_prompt="You are a helpful coding assistant.",
        options=ClaudeAgentOptions(
            model="claude-sonnet-4-5-20250929",
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

### System Prompt & Authority

`ctx.setup()` accepts a `system_prompt` and an optional `authority` string. When the context manager is entered, your system prompt is **augmented** with d:spatch platform instructions — you never need to document workspace paths, inquiry tools, or coordination tools yourself.

#### Authority

The `authority` parameter defines what decisions the agent may make on its own versus what it must escalate via the inquiry tool. When provided, the injected instructions explicitly list the agent's authority and instruct the LLM to escalate anything outside that scope.

```python
ctx.setup(
    system_prompt="You are a senior backend engineer.",
    authority=(
        "You may freely refactor code, fix bugs, and write tests. "
        "You must escalate any changes to the public API surface, "
        "database schema migrations, and dependency upgrades."
    ),
    options=ClaudeAgentOptions(
        model="claude-sonnet-4-5-20250929",
        max_turns=200,
    ),
)
```

When `authority` is omitted, the agent receives generic escalation guidelines — it has full autonomy for routine decisions but is instructed to escalate significant architectural choices and ambiguous requirements.

### How It Works

1. **`ctx.setup()`** — Stores your system prompt, authority, and [`ClaudeAgentOptions`](https://platform.claude.com/docs/en/agent-sdk/python#claude-agent-options). Call this before entering the context manager. It manages the agents lifecycle, ensuring that your sessions persists for multi-turn prompting.
2. **`async with ctx:`** — Creates the Claude SDK client. Your system prompt is augmented with d:spatch platform instructions (inquiry/coordination tools). An MCP server with d:spatch tools is injected into the client options. The working directory defaults to the workspace path.
3. **`await ctx.run(prompt)`** — Sends the prompt to Claude, then iterates the response stream. Text is streamed **token-by-token** as partial messages. Thinking content is streamed and emitted as activities. Tool use is logged as activities. Token usage is recorded automatically.
4. **`prompt = yield`** — Suspends the generator. The next user message resumes it with the new prompt.

### Accessing the Raw Client

Inside `async with ctx:`, `ctx.client` exposes the underlying Claude SDK client. You can use it directly if you need low-level access:

```python
async with ctx:
    # ctx.client is the ClaudeSDKClient instance
    await ctx.client.query("What files are in the workspace?")
    async for message in ctx.client.receive_response():
        # Process raw response messages
        ...
```

---

## Using OpenAiAgentContext

`OpenAiAgentContext` integrates with the **OpenAI Agents SDK** (`openai-agents` package). It builds an `Agent` with d:spatch platform tools as `FunctionTool` objects, runs prompts via `Runner.run_streamed()`, and bridges streaming events (text deltas, tool calls, reasoning, usage) back to the d:spatch app in real time.

### Authentication

The OpenAI Agents SDK reads `OPENAI_API_KEY` from the environment by default. Declare it in your template:

```yaml
required_env:
  - OPENAI_API_KEY
```

### Minimal Example

```python
from dspatch import OpenAiAgentContext, DspatchEngine

dspatch = DspatchEngine()

@dspatch.agent(OpenAiAgentContext)
async def my_agent(prompt: str, ctx: OpenAiAgentContext):
    ctx.setup(system_prompt="You are a helpful coding assistant.")
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

### System Prompt & Authority

The same `system_prompt` and `authority` parameters are available. Your prompt is augmented identically — workspace instructions, inquiry/authority instructions, and coordination instructions are appended automatically.

```python
ctx.setup(
    system_prompt="You are a code reviewer. Review pull requests for correctness and style.",
    authority=(
        "You may approve or request changes on any PR. "
        "You must escalate if a PR introduces a new external dependency "
        "or changes the CI pipeline."
    ),
)
```

See the [ClaudeAgentContext section](#system-prompt--authority) above for a full explanation of how authority affects escalation behavior.

### How It Works

1. **`ctx.setup()`** — Stores your system prompt, authority, and options. Set `options.model` to choose the model (default: `gpt-4o`).
2. **`async with ctx:`** — Builds an OpenAI Agents SDK `Agent` with your augmented system prompt and d:spatch tools as `FunctionTool` objects.
3. **`await ctx.run(prompt)`** — Calls `Runner.run_streamed()` and iterates the event stream. Text is streamed token-by-token. Tool calls and reasoning events are logged as activities. Usage is recorded automatically. Multi-turn continuity is maintained via `previous_response_id`.
4. **`prompt = yield`** — Same generator pattern as ClaudeAgentContext.

### Using a Custom Model

Pass the model name via options:

```python
from dataclasses import dataclass

@dataclass
class Options:
    model: str = "gpt-4o"

ctx.setup(
    system_prompt="You are a helpful assistant.",
    options=Options(model="gpt-4o-mini"),
)
```

### Using a Custom Endpoint

For OpenAI-compatible APIs (Azure, local models, etc.), set `ctx.client` to an `AsyncOpenAI` instance inside the context manager. The context wraps it in an `OpenAIChatCompletionsModel` automatically:

```python
from openai import AsyncOpenAI

async with ctx:
    ctx.client = AsyncOpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed",
    )
    await ctx.run(prompt)
```

---

## Using Any Custom LLM / Framework

If you're using a framework that isn't supported yet, use the base `Context` class and call the platform methods directly.

### System Prompt & Authority

When using the base `Context`, system prompt augmentation is **not automatic** — you must call `ctx._get_augmented_system_prompt()` yourself and pass the result to your LLM as the system prompt.

```python
ctx.setup(
    system_prompt="You are a helpful assistant.",
    authority="You may write and modify code freely. Escalate any database migrations.",
)
async with ctx:
    # Build the full system prompt with platform instructions injected.
    full_system_prompt = ctx._get_augmented_system_prompt()

    # Pass it to your LLM client.
    client = MyLLMClient(system_prompt=full_system_prompt)
```

The augmented prompt includes workspace boundaries, inquiry/authority instructions, and coordination instructions — the same content that `ClaudeAgentContext` and `OpenAiAgentContext` inject automatically.

If you skip `_augment_system_prompt()`, your agent will still function but the LLM won't know about the inquiry tool, its authority boundaries, or peer agents.

### Minimal Example

```python
from dspatch import Context, DspatchEngine

dspatch = DspatchEngine()

@dspatch.agent(Context)
async def my_agent(prompt: str, ctx: Context):
    # Initialize your own client / framework.
    client = MyLLMClient(api_key=os.environ["MY_API_KEY"])

    try:
        while True:
            # Call your LLM.
            response = await client.generate(prompt)

            # Send the response to the user.
            await ctx.message(response.text)

            # Record token usage (optional but recommended).
            await ctx.usage(
                model="my-model",
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.cost,
            )

            # Yield and wait for the next message.
            prompt = yield
            if prompt is None:
                break
    finally:
        await client.close()

dspatch.run()
```

### Streaming Responses

Use `is_delta=True` and pass the returned `id` to append content to the same message:

```python
msg_id = None
async for chunk in client.stream(prompt):
    msg_id = await ctx.message(chunk, is_delta=True, id=msg_id)
```

When `is_delta=True`, each chunk is **appended** to the existing message content. When `is_delta=False` (the default), the content **replaces** the message entirely.

### Wiring d:spatch Platform Tools into Your Framework

`ClaudeAgentContext` and `OpenAiAgentContext` automatically inject d:spatch platform tools (inquiries, agent coordination) into their respective SDKs. When using the base `Context` with a custom framework, you can access the same tool definitions via `ctx._dspatch_tool_specs()` and wire them into your framework's tool/function-calling system yourself.

Each `ToolSpec` provides everything you need:

```python
from dspatch.contexts.context import ToolSpec

for spec in ctx._dspatch_tool_specs():
    spec.name         # str — tool name (e.g. "send_inquiry", "talk_to_reviewer")
    spec.description  # str — human-readable description for the LLM
    spec.schema       # dict — JSON Schema for the tool's parameters
    spec.handler      # async (args: dict) -> dict — call this to execute the tool
```

#### Example: LangChain Integration

```python
from langchain_core.tools import StructuredTool
from dspatch import Context, DspatchEngine

dspatch = DspatchEngine()

@dspatch.agent(Context)
async def my_agent(prompt: str, ctx: Context):
    ctx.setup(system_prompt="You are a helpful assistant.")
    async with ctx:
        # Convert dspatch tool specs to LangChain tools.
        lc_tools = []
        for spec in ctx._dspatch_tool_specs():
            handler = spec.handler
            lc_tools.append(StructuredTool.from_function(
                coroutine=lambda args, _h=handler: _h(args),
                name=spec.name,
                description=spec.description,
                args_schema=spec.schema,  # JSON Schema dict
            ))

        # Use lc_tools with your LangChain agent...
```

#### Example: Raw Function-Calling Loop

```python
@dspatch.agent(Context)
async def my_agent(prompt: str, ctx: Context):
    ctx.setup(system_prompt="You are a helpful assistant.")
    async with ctx:
        # Build a tool name -> handler lookup.
        tool_handlers = {
            spec.name: spec.handler
            for spec in ctx._dspatch_tool_specs()
        }

        # Build tool definitions for your LLM (schema varies by provider).
        tool_defs = [
            {"name": s.name, "description": s.description, "parameters": s.schema}
            for s in ctx._dspatch_tool_specs()
        ]

        # In your tool-call dispatch loop:
        if tool_name in tool_handlers:
            result = await tool_handlers[tool_name](tool_arguments)
```

### Asking the User (Inquiries)

When your agent needs human input, use `ctx.inquire()`. It posts a question to the d:spatch app and blocks until the user responds:

```python
response = await ctx.inquire(
    content_markdown="## Which database should I use?\n\nOption A is faster...",
    suggestions=[
        "PostgreSQL (recommended)",
        "SQLite (simpler)",
        "MongoDB (document-based)",
    ],
    priority="normal",
    timeout_hours=72,
)

print(response.text)              # The user's response text
print(response.suggestion_index)  # Index of selected suggestion (or None)
```

### Coordinating with Other Agents

If your workspace has multiple agents, use `ctx.talk_to()` to delegate work:

```python
# Send a message to another agent and wait for their response.
result = await ctx.talk_to("code-reviewer", "Please review the changes in /workspace/src/")

# Continue a previous conversation with that agent.
followup = await ctx.talk_to("code-reviewer", "What about the test coverage?", continue_conversation=True)
```

The list of available peer agents is accessible via `ctx.available_agents`.

### One-Shot Agents

If your agent doesn't need to persist state across messages, skip the generator pattern:

```python
@dspatch.agent(Context)
async def my_agent(prompt: str, ctx: Context):
    result = await do_work(prompt)
    return result  # Auto-sent as an assistant message.
```

Each message creates a fresh invocation. The conversation history is available via `ctx.messages`.

---

## Context API Reference

These are the methods available on all context types (`Context`).

### Sending Messages

```python
# Simple response
msg_id = await ctx.message("Here's what I found...")

# Streaming (delta messages)
msg_id = None
for token in tokens:
    msg_id = await ctx.message(token, is_delta=True, id=msg_id)
```

When `is_delta=True`, content is **appended** to the existing message. When `is_delta=False` (the default), content **replaces** the message entirely.

**Auto-send:** If your agent function returns/yields a string and `ctx.message()` was never called during that turn, the string is auto-sent as a final message. Once you call `ctx.message()` manually, auto-send is suppressed for that turn.

### Logging

```python
ctx.log("Starting analysis...")
ctx.log("Something went wrong", level="error")
```

Levels: `debug`, `info`, `warn`, `error`. Logs appear in the session's Logs tab.

### Activity Tracking

```python
# Single activity event
await ctx.activity("tool_call", data={"tool": "pytest", "input": "..."})

# Streaming activity content (e.g. thinking tokens)
thinking_id = None
for token in thinking_tokens:
    thinking_id = await ctx.activity(
        "thinking", content=token, is_delta=True, id=thinking_id,
    )
```

When `is_delta=True`, `content` and `data` are **appended/merged** independently into the existing activity. When `is_delta=False` (the default), they **replace** the activity entirely. Fields set to `None` are left untouched in the database.

### Token Usage

```python
await ctx.usage(
    model="claude-sonnet-4-5-20250929",
    input_tokens=1500,
    output_tokens=800,
    cost_usd=0.012,
)
```

### File Operations

```python
await ctx.files([
    {"file_path": "/workspace/src/main.py", "operation": "write"},
    {"file_path": "/workspace/tests/test_main.py", "operation": "write"},
])
```

### Inquiries

```python
response = await ctx.inquire(
    content_markdown="## Question\n\nDetails here...",
    suggestions=["Option A", "Option B"],    # 2-4 options
    file_paths=["/workspace/src/main.py"],   # Optional: files for context
    priority="normal",                        # "normal" or "high"
    timeout_hours=72,
)
```

### Inter-Agent Communication

```python
result = await ctx.talk_to("other-agent", "Do this task")
followup = await ctx.talk_to("other-agent", "Continue with...", continue_conversation=True)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `ctx.messages` | `list[Message]` | Current conversation history |
| `ctx.available_agents` | `list[str]` | Peer agent keys in this workspace |
| `ctx.workspace_dir` | `str` | Workspace directory path (default `/workspace`) |
| `ctx.client` | `Any` | The underlying SDK client (inside `async with ctx:`) |

### Summary Table

| Method | Blocking | Description |
|--------|----------|-------------|
| `ctx.message()` | Yes | Send or stream a message (returns ID) |
| `ctx.log()` | No | Append a log entry |
| `ctx.activity()` | Yes | Record or stream an activity event (returns ID) |
| `ctx.usage()` | Yes | Record token usage |
| `ctx.files()` | Yes | Record file operations |
| `ctx.inquire()` | Yes | Post an inquiry, block until response |
| `ctx.talk_to()` | Yes | Talk to another agent, block until response |
