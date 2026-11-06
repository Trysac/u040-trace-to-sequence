"""Typed error raised by every public entry point of the library."""

from __future__ import annotations

from typing import Literal

__all__ = ["ErrorCode", "TraceError", "preview"]

ErrorCode = Literal[
    "unsupported_format",
    "invalid_id",
    "multiple_traces",
    "empty_trace",
    "parent_cycle",
    "input_too_large",
    "input_invalid",
]

MAX_DETAIL = 200
_ELLIPSIS = "\u2026"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + _ELLIPSIS


def preview(value: object, limit: int = 40) -> str:
    """Return a short, safe description of ``value`` for error messages.

    Strings are quoted and clipped to ``limit`` characters; any other type is
    reduced to its type name so large structures never end up in a message.
    """
    if isinstance(value, str):
        return repr(_clip(value, limit))
    return f"<{type(value).__name__}>"


class TraceError(Exception):
    """Base error of the library.

    Attributes:
        code: stable machine-readable error code.
        detail: human readable detail, at most 200 characters.
        trace_ids: the trace ids found, only set for ``multiple_traces``.
    """

    def __init__(self, code: ErrorCode, detail: str, trace_ids: list[str] | None = None) -> None:
        clipped = _clip(detail, MAX_DETAIL)
        super().__init__(f"{code}: {clipped}")
        self.code: ErrorCode = code
        self.detail = clipped
        self.trace_ids = None if trace_ids is None else list(trace_ids)

    def __reduce__(self) -> tuple[type[TraceError], tuple[ErrorCode, str, list[str] | None]]:
        """Support copying and pickling despite the custom constructor."""
        return (type(self), (self.code, self.detail, self.trace_ids))
