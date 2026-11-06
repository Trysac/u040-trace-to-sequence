"""Immutable span model and structural validation of a trace."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .errors import TraceError, preview

__all__ = ["Span", "Status", "check_spans", "find_orphans"]

Status = Literal["ok", "error", "unset"]


@dataclass(frozen=True)
class Span:
    """One span of a trace.

    ``parent_id`` is ``None`` for a root span. Times are integer nanoseconds.
    """

    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    service: str
    start_ns: int
    end_ns: int
    status: Status


def find_orphans(spans: Sequence[Span]) -> list[str]:
    """Return the ids of spans whose parent is not part of ``spans``, in input order."""
    known = {span.span_id for span in spans}
    return [s.span_id for s in spans if s.parent_id is not None and s.parent_id not in known]


def _compute_depths(spans: Sequence[Span]) -> dict[str, int]:
    """Return the depth of every span (roots and orphans are 0); raise on a parent cycle."""
    by_id = {span.span_id: span for span in spans}
    depths: dict[str, int] = {}
    for span in spans:
        path: list[str] = []
        on_path: set[str] = set()
        current: Span | None = span
        while current is not None and current.span_id not in depths:
            if current.span_id in on_path:
                raise TraceError("parent_cycle", f"parent cycle at {preview(current.span_id)}")
            on_path.add(current.span_id)
            path.append(current.span_id)
            current = None if current.parent_id is None else by_id.get(current.parent_id)
        depth = -1 if current is None else depths[current.span_id]
        for span_id in reversed(path):
            depth += 1
            depths[span_id] = depth
    return depths


def check_spans(spans: Sequence[Span]) -> dict[str, int]:
    """Validate that ``spans`` form one trace and return the depth of each span id.

    Raises:
        TraceError: ``empty_trace``, ``multiple_traces``, ``input_invalid`` (duplicate
            span id or a span ending before it starts) or ``parent_cycle``.
    """
    if not spans:
        raise TraceError("empty_trace", "trace contains no spans")
    trace_ids = sorted({span.trace_id for span in spans})
    if len(trace_ids) > 1:
        shown = ", ".join(trace_ids[:4]) + (", ..." if len(trace_ids) > 4 else "")
        detail = f"found {len(trace_ids)} trace ids: {shown}"
        raise TraceError("multiple_traces", detail, trace_ids)
    seen: set[str] = set()
    for span in spans:
        if span.span_id in seen:
            raise TraceError("input_invalid", f"duplicate span id {preview(span.span_id)}")
        if span.end_ns < span.start_ns:
            raise TraceError("input_invalid", f"span {preview(span.span_id)} ends before it starts")
        seen.add(span.span_id)
    return _compute_depths(spans)
