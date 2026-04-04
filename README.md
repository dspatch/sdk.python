# dspatch-sdk

Python SDK for building containerized AI agents on the [d:spatch](https://dspatch.dev) orchestration platform.

Agents run inside Docker containers and communicate with the d:spatch router over gRPC. The SDK handles connection lifecycle, turn management, and provides a simple `Context` API for logging, messaging, inter-agent communication, and user inquiries.

## Installation

```bash
pip install dspatch-sdk
```

Requires Python 3.10+.

## Quick Start

```python
from dspatch import DspatchEngine, Context

engine = DspatchEngine()

@engine.agent()
async def my_agent(ctx: Context):
    await ctx.log("info", "Agent started")
    await ctx.message("Hello from my agent!")

engine.run()
```

### With Claude

```python
from dspatch import DspatchEngine, ClaudeAgentContext

engine = DspatchEngine()

@engine.agent(context_class=ClaudeAgentContext)
async def my_agent(ctx: ClaudeAgentContext):
    await ctx.run()

engine.run()
```

### With OpenAI

```python
from dspatch import DspatchEngine, OpenAiAgentContext

engine = DspatchEngine()

@engine.agent(context_class=OpenAiAgentContext)
async def my_agent(ctx: OpenAiAgentContext):
    await ctx.run()

engine.run()
```

## Context API

The `Context` object is passed to your agent function each turn:

| Method | Description |
|--------|-------------|
| `ctx.log(level, message)` | Structured logging (visible in the d:spatch app) |
| `ctx.activity(description)` | Activity status updates |
| `ctx.message(content, role)` | Send a message to the conversation |
| `ctx.files(paths)` | Attach files |
| `ctx.inquire(question, priority, timeout)` | Ask the user a question (blocks until answered) |
| `ctx.talk_to(peer, message)` | Send a message to another agent (blocks until response) |
| `ctx.prompt(text)` | Raw prompt passthrough |

## Agent Template

Agents are configured with a `dspatch.agent.yml` in their project directory:

```yaml
name: My Agent
description: What this agent does.
entry_point: agent.py
fields:
  system_prompt: <base64-encoded prompt>
required_env:
  - ANTHROPIC_API_KEY
```

See the [user guide](https://dspatch.dev/docs) for the full config reference.

## Documentation

Full documentation at [dspatch.dev/docs](https://dspatch.dev/docs).

## License

AGPL-3.0 — see [LICENSE](LICENSE) for details.
