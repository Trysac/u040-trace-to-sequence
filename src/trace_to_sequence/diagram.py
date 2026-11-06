"""Render a trace as a Mermaid sequence diagram."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from .errors import TraceError
from .model import Span, check_spans

__all__ = ["DiagramOptions", "to_mermaid"]

MAX_LABEL_LIMIT = 10_000
_ELLIPSIS = "\u2026"
_ESCAPES = str.maketrans(
    {
        "#": "#35;",
        ";": "#59;",
        ":": "#58;",
        "<": "#lt;",
        ">": "#gt;",
        "\r": " ",
        "\n": " ",
    }
)


@dataclass(frozen=True)
class DiagramOptions:
    """Rendering options.

    Attributes:
        show_internal: render same-service child spans as notes instead of skipping them.
        show_durations: add the duration in milliseconds to every return arrow.
        max_label: longest label before it is cut and ends with an ellipsis (1..10_000).
        autonumber: emit the ``autonumber`` directive.
    """

    show_internal: bool = False
    show_durations: bool = True
    max_label: int = 40
    autonumber: bool = True

    def __post_init__(self) -> None:
        limit = self.max_label
        valid = isinstance(limit, int) and not isinstance(limit, bool)
        if not valid or not 1 <= limit <= MAX_LABEL_LIMIT:
            detail = f"max_label must be between 1 and {MAX_LABEL_LIMIT}"
            raise TraceError("input_invalid", detail)


_DEFAULT_OPTIONS = DiagramOptions()


class _Event(NamedTuple):
    key: tuple[int, int, int, str]
    kind: str
    span: Span
    caller: Span | None


def _label(text: str, max_label: int) -> str:
    """Cut ``text`` to ``max_label`` characters, then escape it in a single pass."""
    if len(text) > max_label:
        text = text[: max_label - 1] + _ELLIPSIS
    return text.translate(_ESCAPES)


def _format_ms(duration_ns: int) -> str:
    tenths = (duration_ns + 50_000) // 100_000
    return f"{tenths // 10}.{tenths % 10}"


def _return_text(span: Span, options: DiagramOptions) -> str:
    status = "error" if span.status == "error" else "ok"
    if not options.show_durations:
        return status
    return f"{status} {_format_ms(span.end_ns - span.start_ns)} ms"


def _collect_events(
    spans: Sequence[Span], depths: dict[str, int], options: DiagramOptions
) -> list[_Event]:
    by_id = {span.span_id: span for span in spans}
    events: list[_Event] = []
    for span in spans:
        caller = None if span.parent_id is None else by_id.get(span.parent_id)
        depth = depths[span.span_id]
        start_key = (span.start_ns, 1, depth, span.span_id)
        if caller is None or caller.service != span.service:
            rank = 2 if span.end_ns == span.start_ns else 0
            return_key = (span.end_ns, rank, -depth, span.span_id)
            events.append(_Event(start_key, "request", span, caller))
            events.append(_Event(return_key, "return", span, caller))
        elif options.show_internal:
            events.append(_Event(start_key, "note", span, caller))
    return events


def to_mermaid(spans: Sequence[Span], options: DiagramOptions = _DEFAULT_OPTIONS) -> str:
    """Render the spans of one trace as a Mermaid ``sequenceDiagram``.

    A root (or orphan) span is a request from the synthetic participant ``Client``;
    every parent-child pair that crosses services is a request arrow at the child's
    start and a dashed return at its end. Events are ordered by time, then returns
    before requests, deeper returns first, shallower requests first, then span id.
    A zero-duration span returns right after its own request, never before it.
    Same-service children are skipped unless ``options.show_internal`` is set.

    Returns:
        LF-joined lines ending with a newline.

    Raises:
        TraceError: when the spans are empty, belong to several traces, contain a
            duplicate id or a parent cycle, or a span ends before it starts.
    """
    depths = check_spans(spans)
    participants: dict[str, str] = {}
    declarations = ["participant Client"]
    body: list[str] = []
    limit = options.max_label

    def ref(service: str) -> str:
        if service not in participants:
            alias = f"p{len(participants) + 1}"
            participants[service] = alias
            declarations.append(f"participant {alias} as {_label(service, limit)}")
        return participants[service]

    for event in sorted(_collect_events(spans, depths, options), key=lambda item: item.key):
        span = event.span
        caller_ref = "Client" if event.caller is None else ref(event.caller.service)
        own = ref(span.service)
        if event.kind == "request":
            body.append(f"{caller_ref}->>{own}: {_label(span.name, limit)}")
        elif event.kind == "return":
            body.append(f"{own}-->>{caller_ref}: {_return_text(span, options)}")
        else:
            body.append(f"Note over {own}: {_label(span.name, limit)}")

    lines = ["sequenceDiagram"]
    if options.autonumber:
        lines.append("autonumber")
    lines.extend(declarations)
    lines.extend(body)
    return "\n".join(lines) + "\n"
