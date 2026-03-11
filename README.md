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

## Releasing

Releases are published to PyPI automatically when a version tag is pushed.

```bash
pip install bump-my-version

# bump version (patch/minor/major), auto-commits and tags
bump-my-version bump patch   # 0.1.0 → 0.1.1
bump-my-version bump minor   # 0.1.0 → 0.2.0
bump-my-version bump major   # 0.1.0 → 1.0.0

# push commit + tag to trigger publish
git push origin main --tags
```

## Documentation

See the full documentation at [dspatch.dev/docs](https://dspatch.dev/docs).

## License

AGPL-3.0 — see [LICENSE](LICENSE) for details.

Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree).
