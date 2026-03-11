# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""Minimal echo agent for integration testing."""

from dspatch import Context, DspatchEngine

dspatch = DspatchEngine()


@dspatch.agent(Context)
async def echo(prompt, ctx):
    ctx.log(f"Received: {prompt}")
    return f"Echo: {prompt}"


dspatch.run()
