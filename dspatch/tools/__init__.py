# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""dspatch.tools — pre-built, reusable tools for agent developers.

Core tool definitions live in submodules (e.g. ``inquiry``).
Framework-specific adapters live in ``claude`` and ``openai``.
"""

from .inquiry import (
    DESCRIPTION as INQUIRY_DESCRIPTION,
    NAME as INQUIRY_NAME,
    SCHEMA as INQUIRY_SCHEMA,
    execute as execute_inquiry,
)
from .inquiry_interrupt import (
    REPLY_DESCRIPTION as INQUIRY_REPLY_DESCRIPTION,
    REPLY_NAME as INQUIRY_REPLY_NAME,
    REPLY_SCHEMA as INQUIRY_REPLY_SCHEMA,
    execute_reply as execute_inquiry_reply,
    format_inquiry_injection,
)

__all__ = [
    "INQUIRY_DESCRIPTION",
    "INQUIRY_NAME",
    "INQUIRY_SCHEMA",
    "execute_inquiry",
    "INQUIRY_REPLY_DESCRIPTION",
    "INQUIRY_REPLY_NAME",
    "INQUIRY_REPLY_SCHEMA",
    "execute_inquiry_reply",
    "format_inquiry_injection",
]
