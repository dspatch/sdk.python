# Copyright (c) 2026 Osman Alperen Çinar-Koraş (oakisnotree). Licensed under AGPL-3.0.
"""SDK error types."""


class DspatchApiError(Exception):
    """Raised when an engine API call fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class InquiryTimeout(Exception):
    """Raised when the SSE stream closes without a response."""


class AgentError(Exception):
    """Raised when the agent function throws."""
