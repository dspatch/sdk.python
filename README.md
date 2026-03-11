# dspatch-sdk

Python SDK for the [d:spatch](https://dspatch.dev) agent orchestration platform.

## Installation

```bash
pip install dspatch-sdk
```

## Quick Start

```python
from dspatch import DspatchEngine, Context

async def my_agent(ctx: Context):
    await ctx.log("Agent started")
    # Your agent logic here

engine = DspatchEngine(agent_fn=my_agent)
engine.run()
```

## Documentation

See the full documentation at [dspatch.dev/docs](https://dspatch.dev/docs).

## License

AGPL-3.0 — see [LICENSE](LICENSE) for details.

Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree).
