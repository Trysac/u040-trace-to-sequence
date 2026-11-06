"""Tests for the public API and the command line of trace_to_sequence."""

from __future__ import annotations

import copy
import json
import logging
import runpy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import trace_to_sequence
from trace_to_sequence import (
    DiagramOptions,
    Span,
    TraceError,
    find_orphans,
    load_trace,
    parse_trace,
    to_mermaid,
)
from trace_to_sequence.__main__ import main
from trace_to_sequence.errors import preview
from trace_to_sequence.model import Status

TRACE = "ab" * 16
MS = 1_000_000


def sid(number: int) -> str:
    return f"{number:016x}"


def span(
    number: int,
    parent: int | None = None,
    *,
    name: str = "op",
    service: str = "svc",
    start: int = 0,
    end: int = 1,
    status: Status = "ok",
    trace: str = TRACE,
) -> Span:
    parent_id = None if parent is None else sid(parent)
    return Span(trace, sid(number), parent_id, name, service, start, end, status)


def otlp_span(number: int, parent: int | None = None, **overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "traceId": TRACE.upper(),
        "spanId": sid(number),
        "parentSpanId": "" if parent is None else sid(parent),
        "name": "op",
        "startTimeUnixNano": "1000",
        "endTimeUnixNano": "2000",
        "status": {"code": 0},
    }
    raw.update(overrides)
    return raw


def otlp_doc(spans: list[dict[str, Any]], service: str | None = "svc") -> dict[str, Any]:
    resource: dict[str, Any] = {}
    if service is not None:
        attribute = {"key": "service.name", "value": {"stringValue": service}}
        resource = {"attributes": [attribute]}
    return {"resourceSpans": [{"resource": resource, "scopeSpans": [{"spans": spans}]}]}


def simple_span(number: int, parent: int | None = None, **overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "trace_id": TRACE,
        "span_id": sid(number),
        "parent_id": None if parent is None else sid(parent),
        "name": "op",
        "service": "svc",
        "start": 0,
        "end": 1,
    }
    raw.update(overrides)
    return raw


def code_of(action: Callable[[], object]) -> str:
    with pytest.raises(TraceError) as info:
        action()
    return info.value.code


def write_json(tmp_path: Path, data: object, name: str = "trace.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def nest(levels: int) -> list[Any]:
    value: list[Any] = []
    for _ in range(levels - 1):
        value = [value]
    return value


def nest_dict(levels: int) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for _ in range(levels - 1):
        value = {"a": value}
    return value


# --- package metadata ---------------------------------------------------------------


def test_version_and_null_handler() -> None:
    assert trace_to_sequence.__version__ == "0.1.0"
    handlers = logging.getLogger("trace_to_sequence").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)


# --- errors -------------------------------------------------------------------------


def test_error_is_clipped_copyable_and_carries_code() -> None:
    error = TraceError("input_invalid", "x" * 500)
    assert len(error.detail) == 200
    assert error.code == "input_invalid"
    assert error.trace_ids is None
    clone = copy.copy(TraceError("multiple_traces", "two", ["a", "b"]))
    assert (clone.code, clone.detail, clone.trace_ids) == ("multiple_traces", "two", ["a", "b"])
    assert str(clone) == "multiple_traces: two"


def test_preview_never_echoes_large_input() -> None:
    assert preview(5) == "<int>"
    assert preview([1, 2, 3]) == "<list>"
    assert len(preview("y" * 1000)) <= 45
    assert preview("abc") == "'abc'"


# --- OTLP parsing -------------------------------------------------------------------


def test_otlp_nanosecond_fields_and_status() -> None:
    first = otlp_span(1, startTimeUnixNano="1000")
    second = otlp_span(2, 1, startTimeUnixNano=1000, status={"code": 2})
    third = otlp_span(3, 1, status={"code": "STATUS_CODE_ERROR"})
    spans = parse_trace(otlp_doc([first, second, third]))
    assert [item.start_ns for item in spans] == [1000, 1000, 1000]
    assert [item.status for item in spans] == ["unset", "error", "error"]
    assert spans[1].parent_id == sid(1)
    assert spans[0].end_ns == 2000
    assert all(item.service == "svc" for item in spans)


def test_float_nanoseconds_are_rejected() -> None:
    doc = otlp_doc([otlp_span(1, startTimeUnixNano=1000.0)])
    assert code_of(lambda: parse_trace(doc)) == "input_invalid"


@pytest.mark.parametrize(
    "value",
    [1000.0, True, False, -1, "12x", "1" * 21, 2**64, None, [1], " 1", "12\n", "\u0661"],
)
def test_bad_nanosecond_values(value: object) -> None:
    doc = otlp_doc([otlp_span(1, endTimeUnixNano=value)])
    assert code_of(lambda: parse_trace(doc)) == "input_invalid"


def test_end_before_start_is_invalid() -> None:
    doc = otlp_doc([otlp_span(1, startTimeUnixNano="2000", endTimeUnixNano="1999")])
    assert code_of(lambda: parse_trace(doc)) == "input_invalid"


def test_ids_are_lower_cased_and_empty_parent_is_root() -> None:
    raw = otlp_span(1, traceId="AB" * 16, parentSpanId="")
    parsed = parse_trace(otlp_doc([raw]))[0]
    assert parsed.trace_id == "ab" * 16
    assert parsed.parent_id is None
    upper = otlp_span(2, 1, spanId="ABCDEF0123456789")
    assert parse_trace(otlp_doc([raw, upper]))[1].span_id == "abcdef0123456789"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("traceId", "q83vEjRWeJA="),
        ("spanId", "q83vEjRWeJA="),
        ("spanId", "abcdef012345678"),
        ("spanId", "a" * 17),
        ("parentSpanId", "abc"),
        ("traceId", "g" * 32),
        ("traceId", 5),
        ("spanId", None),
        ("traceId", "a" * 10_000),
    ],
)
def test_invalid_ids(field: str, value: object) -> None:
    doc = otlp_doc([otlp_span(1, **{field: value})])
    with pytest.raises(TraceError) as info:
        parse_trace(doc)
    assert info.value.code == "invalid_id"
    assert len(info.value.detail) <= 200


def test_service_name_fallbacks() -> None:
    raw = [otlp_span(1)]
    assert parse_trace(otlp_doc(raw, service=None))[0].service == "unknown_service"
    assert parse_trace(otlp_doc(raw, service=""))[0].service == "unknown_service"
    host = {"attributes": [{"key": "host", "value": {"stringValue": "h"}}]}
    doc = {"resourceSpans": [{"resource": host, "scopeSpans": [{"spans": raw}]}]}
    assert parse_trace(doc)[0].service == "unknown_service"
    number = {"attributes": [{"key": "service.name", "value": {"intValue": 3}}]}
    doc = {"resourceSpans": [{"resource": number, "scopeSpans": [{"spans": raw}]}]}
    assert parse_trace(doc)[0].service == "unknown_service"
    doc = {"resourceSpans": [{"scopeSpans": [{"spans": raw}]}]}
    assert parse_trace(doc)[0].service == "unknown_service"
    mixed = {"attributes": [5, {"key": "service.name", "value": {"stringValue": "x"}}]}
    doc = {"resourceSpans": [{"resource": mixed, "scopeSpans": [{"spans": raw}]}]}
    assert parse_trace(doc)[0].service == "x"


@pytest.mark.parametrize(
    "doc",
    [
        {"resourceSpans": "x"},
        {"resourceSpans": [1]},
        {"resourceSpans": [{"scopeSpans": {}}]},
        {"resourceSpans": [{"resource": 1}]},
        {"resourceSpans": [{"resource": {"attributes": "x"}}]},
        {"resourceSpans": [{"scopeSpans": [1]}]},
        {"resourceSpans": [{"scopeSpans": [{"spans": {}}]}]},
        {"resourceSpans": [{"scopeSpans": [{"spans": [1]}]}]},
    ],
)
def test_structurally_invalid_otlp(doc: object) -> None:
    assert code_of(lambda: parse_trace(doc)) == "input_invalid"


@pytest.mark.parametrize(
    "doc",
    [[], {"resourceSpans": []}, {"resourceSpans": [{}]}, {"resourceSpans": [{"scopeSpans": []}]}],
)
def test_empty_traces(doc: object) -> None:
    assert code_of(lambda: parse_trace(doc)) == "empty_trace"


@pytest.mark.parametrize("doc", [{}, {"a": 1}, "text", 5, None, 1.5])
def test_unsupported_formats(doc: object) -> None:
    assert code_of(lambda: parse_trace(doc)) == "unsupported_format"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({"code": 0}, "unset"),
        ({"code": "STATUS_CODE_UNSET"}, "unset"),
        ({"code": 1}, "ok"),
        ({"code": "STATUS_CODE_OK"}, "ok"),
        ({"code": 2}, "error"),
        ({"code": "STATUS_CODE_ERROR"}, "error"),
        ({"message": "boom"}, "unset"),
        (None, "unset"),
    ],
)
def test_otlp_status_values(status: object, expected: str) -> None:
    spans = parse_trace(otlp_doc([otlp_span(1, status=status)]))
    assert spans[0].status == expected


@pytest.mark.parametrize("status", [{"code": 3}, {"code": True}, {"code": "ERROR"}, "error", 5])
def test_otlp_bad_status(status: object) -> None:
    doc = otlp_doc([otlp_span(1, status=status)])
    assert code_of(lambda: parse_trace(doc)) == "input_invalid"


# --- simple format ------------------------------------------------------------------


def test_simple_format_with_iso_timestamps() -> None:
    start = "2024-01-01T00:00:00Z"
    end = "2024-01-01T01:00:00.000000123+01:00"
    parsed = parse_trace([simple_span(1, start=start, end=end)])[0]
    assert parsed.start_ns == 1_704_067_200_000_000_000
    assert parsed.end_ns == parsed.start_ns + 123
    assert parsed.service == "svc"
    assert parsed.status == "unset"


def test_simple_format_offsets_and_digit_strings() -> None:
    start = "2024-01-01 00:00:00-05:00"
    end = "2024-01-01t05:00:01z"
    parsed = parse_trace([simple_span(2, start=start, end=end)])[0]
    assert parsed.start_ns == 1_704_067_200_000_000_000 + 18_000 * 10**9
    assert parsed.end_ns == parsed.start_ns + 1_000_000_000
    digits = parse_trace([simple_span(3, start="5", end="10")])[0]
    assert (digits.start_ns, digits.end_ns) == (5, 10)


@pytest.mark.parametrize(
    "value",
    [
        "2024-01-01T00:00:00",
        "2024-13-01T00:00:00Z",
        "2024-01-01T00:00:00+24:00",
        "2024-01-01T00:00:00+00:60",
        "0001-01-01T00:00:00+23:59",
        "1969-12-31T23:59:59Z",
        "2024-01-01T00:00:60Z",
        "2024-01-01",
        1.5,
        None,
    ],
)
def test_bad_simple_times(value: object) -> None:
    data = [simple_span(1, end=value)]
    assert code_of(lambda: parse_trace(data)) == "input_invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service", None),
        ("service", ""),
        ("service", 3),
        ("name", None),
        ("name", 5),
        ("status", "weird"),
        ("status", 3),
        ("start", 5),
        ("end", "x"),
    ],
)
def test_invalid_simple_fields(field: str, value: object) -> None:
    data = [simple_span(1, **{field: value})]
    assert code_of(lambda: parse_trace(data)) == "input_invalid"


def test_simple_status_and_parent_variants() -> None:
    data = [simple_span(1, status="error", parent_id=""), simple_span(2, 1, status="ok")]
    spans = parse_trace(data)
    assert [item.status for item in spans] == ["error", "ok"]
    assert spans[0].parent_id is None
    assert code_of(lambda: parse_trace([1])) == "input_invalid"


# --- trace selection, structure and limits -----------------------------------------


def test_multiple_traces_and_selection() -> None:
    other = "cd" * 16
    data = [simple_span(1), simple_span(2, trace_id=other)]
    with pytest.raises(TraceError) as info:
        parse_trace(data)
    assert info.value.code == "multiple_traces"
    assert info.value.trace_ids == [TRACE, other]
    assert TRACE in info.value.detail
    assert other in info.value.detail
    chosen = parse_trace(data, trace_id=other.upper())
    assert [item.span_id for item in chosen] == [sid(2)]


def test_many_traces_are_summarised() -> None:
    data = [simple_span(n, trace_id=f"{n:032x}") for n in range(1, 7)]
    with pytest.raises(TraceError) as info:
        parse_trace(data)
    assert info.value.trace_ids is not None
    assert len(info.value.trace_ids) == 6
    assert info.value.detail.endswith(", ...")
    assert len(info.value.detail) <= 200


def test_unknown_or_malformed_trace_id() -> None:
    data = [simple_span(1)]
    assert code_of(lambda: parse_trace(data, trace_id="cd" * 16)) == "empty_trace"
    assert code_of(lambda: parse_trace(data, trace_id="xyz")) == "invalid_id"


def test_parent_cycles_are_rejected() -> None:
    pair = [simple_span(1, 2), simple_span(2, 1)]
    assert code_of(lambda: parse_trace(pair)) == "parent_cycle"
    itself = [simple_span(1, 1)]
    assert code_of(lambda: parse_trace(itself)) == "parent_cycle"
    ring = [simple_span(4, 1), simple_span(1, 3), simple_span(2, 1), simple_span(3, 2)]
    assert code_of(lambda: parse_trace(ring)) == "parent_cycle"
    spans = [span(1, 2), span(2, 1)]
    assert code_of(lambda: to_mermaid(spans)) == "parent_cycle"


def test_duplicate_span_ids_are_rejected() -> None:
    data = [simple_span(1), simple_span(1)]
    assert code_of(lambda: parse_trace(data)) == "input_invalid"


def test_max_spans_limit() -> None:
    otlp = otlp_doc([otlp_span(n) for n in range(1, 4)])
    simple = [simple_span(n) for n in range(1, 4)]
    assert len(parse_trace(otlp, max_spans=3)) == 3
    assert len(parse_trace(simple, max_spans=3)) == 3
    assert code_of(lambda: parse_trace(otlp, max_spans=2)) == "input_too_large"
    assert code_of(lambda: parse_trace(simple, max_spans=2)) == "input_too_large"


def test_json_depth_limit() -> None:
    deep = nest(65)
    with pytest.raises(TraceError) as info:
        parse_trace(deep)
    assert info.value.code == "input_invalid"
    assert "nesting" in info.value.detail
    with pytest.raises(TraceError) as ok_info:
        parse_trace(nest(64))
    assert "nesting" not in ok_info.value.detail
    deep = {"resourceSpans": [], "x": nest_dict(64)}
    assert code_of(lambda: parse_trace(deep)) == "input_invalid"
    assert code_of(lambda: parse_trace({"resourceSpans": [], "x": nest_dict(63)})) == "empty_trace"
    cyclic: list[Any] = []
    cyclic.append(cyclic)
    assert code_of(lambda: parse_trace(cyclic)) == "input_invalid"


# --- files --------------------------------------------------------------------------


def test_load_trace_reads_files(tmp_path: Path) -> None:
    path = write_json(tmp_path, otlp_doc([otlp_span(1)]))
    assert load_trace(path)[0].span_id == sid(1)
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + json.dumps([simple_span(1)]).encode("utf-8"))
    assert load_trace(bom)[0].span_id == sid(1)


def test_load_trace_size_limits(tmp_path: Path) -> None:
    max_bytes = 100
    path = tmp_path / "big.json"
    path.write_bytes(b"[]" + b" " * (max_bytes - 2))
    assert code_of(lambda: load_trace(path, max_bytes=max_bytes)) == "empty_trace"
    path.write_bytes(b"[]" + b" " * (max_bytes - 1))
    assert code_of(lambda: load_trace(path, max_bytes=max_bytes)) == "input_too_large"
    spans = write_json(tmp_path, [simple_span(n) for n in range(1, 4)], "spans.json")
    assert len(load_trace(spans, max_spans=3)) == 3
    assert code_of(lambda: load_trace(spans, max_spans=2)) == "input_too_large"


def test_load_trace_depth_and_recursion(tmp_path: Path) -> None:
    path = tmp_path / "deep.json"
    path.write_text("[" * 65 + "]" * 65, encoding="utf-8")
    assert code_of(lambda: load_trace(path)) == "input_invalid"
    path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    assert code_of(lambda: load_trace(path)) == "input_invalid"


def test_load_trace_rejects_unreadable_input(tmp_path: Path) -> None:
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    assert code_of(lambda: load_trace(bad_json)) == "input_invalid"
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00")
    assert code_of(lambda: load_trace(binary)) == "input_invalid"
    assert code_of(lambda: load_trace(tmp_path)) == "input_invalid"
    assert code_of(lambda: load_trace(tmp_path / "missing.json")) == "input_invalid"


def test_end_before_start_in_file(tmp_path: Path) -> None:
    path = write_json(tmp_path, [simple_span(1, start=10, end=5)])
    assert code_of(lambda: load_trace(path)) == "input_invalid"


# --- diagram ------------------------------------------------------------------------


def test_acceptance_diagram() -> None:
    child_ns = 12_000_000
    spans = [
        span(1, name="GET /", service="frontend", start=0, end=30_000_000),
        span(2, 1, name="GET /users", service="api", start=1_000_000, end=1_000_000 + child_ns),
    ]
    result = to_mermaid(spans)
    assert result.splitlines() == [
        "sequenceDiagram",
        "autonumber",
        "participant Client",
        "participant p1 as frontend",
        "participant p2 as api",
        "Client->>p1: GET /",
        "p1->>p2: GET /users",
        "p2-->>p1: ok 12.0 ms",
        "p1-->>Client: ok 30.0 ms",
    ]
    assert result.endswith("ms\n")
    assert not result.endswith("\n\n")


def test_otlp_file_to_diagram(tmp_path: Path) -> None:
    root = otlp_span(1, name="root", startTimeUnixNano="0", endTimeUnixNano="2000000")
    doc = otlp_doc([root])
    lines = to_mermaid(parse_trace(doc)).splitlines()
    assert lines[-2:] == ["Client->>p1: root", "p1-->>Client: ok 2.0 ms"][:1] + lines[-1:]
    assert lines[-1] == "p1-->>Client: ok 2.0 ms"


def test_child_ending_with_parent_returns_first() -> None:
    spans = [
        span(1, name="root", service="a", start=0, end=100 * MS),
        span(2, 1, name="child", service="b", start=10 * MS, end=100 * MS),
    ]
    assert to_mermaid(spans).splitlines()[5:] == [
        "Client->>p1: root",
        "p1->>p2: child",
        "p2-->>p1: ok 90.0 ms",
        "p1-->>Client: ok 100.0 ms",
    ]


def test_deeper_returns_first_and_shallower_requests_first() -> None:
    spans = [
        span(3, 2, service="c", start=0, end=10 * MS),
        span(2, 1, service="b", start=0, end=10 * MS),
        span(1, service="a", start=0, end=10 * MS),
    ]
    assert to_mermaid(spans).splitlines()[6:] == [
        "Client->>p1: op",
        "p1->>p2: op",
        "p2->>p3: op",
        "p3-->>p2: ok 10.0 ms",
        "p2-->>p1: ok 10.0 ms",
        "p1-->>Client: ok 10.0 ms",
    ]


def test_same_instant_requests_are_ordered_by_span_id() -> None:
    spans = [
        span(1, service="a", start=0, end=10 * MS),
        span(3, 1, name="c", service="c", start=MS, end=2 * MS),
        span(2, 1, name="b", service="b", start=MS, end=2 * MS),
    ]
    lines = to_mermaid(spans).splitlines()
    assert lines[6:9] == ["Client->>p1: op", "p1->>p2: b", "p1->>p3: c"]
    assert lines[9:11] == ["p2-->>p1: ok 1.0 ms", "p3-->>p1: ok 1.0 ms"]


def test_concurrent_children() -> None:
    spans = [
        span(1, name="root", service="a", start=0, end=100 * MS),
        span(3, 1, name="third", service="c", start=20 * MS, end=80 * MS),
        span(2, 1, name="second", service="b", start=10 * MS, end=60 * MS),
    ]
    assert to_mermaid(spans).splitlines()[6:] == [
        "Client->>p1: root",
        "p1->>p2: second",
        "p1->>p3: third",
        "p2-->>p1: ok 50.0 ms",
        "p3-->>p1: ok 60.0 ms",
        "p1-->>Client: ok 100.0 ms",
    ]


def test_duration_rounding_is_half_up() -> None:
    up = to_mermaid([span(1, start=0, end=12_050_000)]).splitlines()
    down = to_mermaid([span(1, start=0, end=12_049_999)]).splitlines()
    assert up[-1] == "p1-->>Client: ok 12.1 ms"
    assert down[-1] == "p1-->>Client: ok 12.0 ms"


def test_zero_duration_spans() -> None:
    spans = [
        span(1, service="a", start=0, end=10 * MS),
        span(2, 1, name="instant", service="b", start=5 * MS, end=5 * MS),
    ]
    assert to_mermaid(spans).splitlines()[5:] == [
        "Client->>p1: op",
        "p1->>p2: instant",
        "p2-->>p1: ok 0.0 ms",
        "p1-->>Client: ok 10.0 ms",
    ]
    nested = [span(1, service="a", start=7, end=7), span(2, 1, service="b", start=7, end=7)]
    assert to_mermaid(nested).splitlines()[5:] == [
        "Client->>p1: op",
        "p1->>p2: op",
        "p2-->>p1: ok 0.0 ms",
        "p1-->>Client: ok 0.0 ms",
    ]


def test_label_and_service_escaping() -> None:
    assert "participant p1 as a#59;b" in to_mermaid([span(1, service="a;b")]).splitlines()
    lines = to_mermaid([span(1, name="x#1: <y>\nz")]).splitlines()
    assert lines[-2] == "Client->>p1: x#35;1#58; #lt;y#gt; z"
    assert to_mermaid([span(1, name="a#59;")]).splitlines()[-2] == "Client->>p1: a#35;59#59;"
    assert to_mermaid([span(1, name="a\rb")]).splitlines()[-2] == "Client->>p1: a b"


def test_label_truncation() -> None:
    name = "abcdefghij" * 4 + "k"
    assert len(name) == 41
    options = DiagramOptions(max_label=40)
    lines = to_mermaid([span(1, name=name)], options).splitlines()
    assert lines[-2] == "Client->>p1: " + name[:39] + "\u2026"
    exact = to_mermaid([span(1, name=name[:40])], options).splitlines()
    assert exact[-2] == "Client->>p1: " + name[:40]
    hashes = to_mermaid([span(1, name="#" * 45)], DiagramOptions(max_label=3)).splitlines()
    assert hashes[-2] == "Client->>p1: #35;#35;\u2026"
    long_service = to_mermaid([span(1, service="s" * 50)], options).splitlines()
    assert long_service[3] == "participant p1 as " + "s" * 39 + "\u2026"


def internal_trace() -> list[Span]:
    return [
        span(1, name="root", service="a", start=0, end=10 * MS),
        span(2, 1, name="cache lookup", service="a", start=MS, end=3 * MS),
        span(3, 2, name="db", service="b", start=2 * MS, end=3 * MS),
    ]


def test_internal_spans_are_skipped_by_default() -> None:
    assert to_mermaid(internal_trace()).splitlines()[5:] == [
        "Client->>p1: root",
        "p1->>p2: db",
        "p2-->>p1: ok 1.0 ms",
        "p1-->>Client: ok 10.0 ms",
    ]


def test_internal_spans_become_notes() -> None:
    result = to_mermaid(internal_trace(), DiagramOptions(show_internal=True))
    assert result.splitlines()[5:] == [
        "Client->>p1: root",
        "Note over p1: cache lookup",
        "p1->>p2: db",
        "p2-->>p1: ok 1.0 ms",
        "p1-->>Client: ok 10.0 ms",
    ]


def test_orphan_attaches_to_client() -> None:
    spans = [span(1, service="a"), Span(TRACE, sid(2), sid(99), "lost", "b", 0, 1, "ok")]
    assert find_orphans(spans) == [sid(2)]
    assert find_orphans([span(1)]) == []
    assert "Client->>p2: lost" in to_mermaid(spans).splitlines()


def test_diagram_options() -> None:
    spans = [
        span(1, service="a", start=0, end=10 * MS, status="unset"),
        span(2, 1, service="b", start=MS, end=6 * MS, status="error"),
    ]
    plain = to_mermaid(spans, DiagramOptions(show_durations=False, autonumber=False))
    lines = plain.splitlines()
    assert lines[0] == "sequenceDiagram"
    assert "autonumber" not in lines
    assert lines[-2:] == ["p2-->>p1: error", "p1-->>Client: ok"]
    assert to_mermaid(spans).splitlines()[-2] == "p2-->>p1: error 5.0 ms"
    assert to_mermaid(spans).splitlines()[-1] == "p1-->>Client: ok 10.0 ms"


@pytest.mark.parametrize("limit", [0, -1, 10_001, True, "5", 2.5])
def test_invalid_max_label(limit: Any) -> None:
    assert code_of(lambda: DiagramOptions(max_label=limit)) == "input_invalid"


def test_options_are_frozen_and_boundaries_accepted() -> None:
    options = DiagramOptions(max_label=1)
    with pytest.raises(AttributeError):
        options.max_label = 3  # type: ignore[misc]
    assert DiagramOptions(max_label=10_000).max_label == 10_000
    assert to_mermaid([span(1, name="abc")], options).splitlines()[-2] == "Client->>p1: \u2026"


def test_to_mermaid_rejects_bad_span_sets() -> None:
    assert code_of(lambda: to_mermaid([])) == "empty_trace"
    mixed = [span(1), span(2, trace="cd" * 16)]
    assert code_of(lambda: to_mermaid(mixed)) == "multiple_traces"
    backwards = [span(1, start=5, end=4)]
    assert code_of(lambda: to_mermaid(backwards)) == "input_invalid"
    twice = [span(1), span(1)]
    assert code_of(lambda: to_mermaid(twice)) == "input_invalid"


# --- command line -------------------------------------------------------------------


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def basic_data() -> list[dict[str, Any]]:
    root = simple_span(1, name="GET /", service="frontend", start=0, end=30_000_000)
    child = simple_span(2, 1, name="GET /users", service="api", start=1_000_000, end=13_000_000)
    return [root, child]


def test_cli_prints_diagram(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_json(tmp_path, basic_data())
    code, out, err = run([str(path)], capsys)
    assert (code, err) == (0, "")
    assert out == to_mermaid(parse_trace(basic_data()))
    assert "p2-->>p1: ok 12.0 ms" in out


def test_cli_fenced_and_output_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_json(tmp_path, basic_data())
    code, out, _ = run([str(path), "--fenced"], capsys)
    assert code == 0
    assert out.startswith("```mermaid\nsequenceDiagram\n")
    assert out.endswith("ms\n```\n")
    target = tmp_path / "out.md"
    code, out, _ = run([str(path), "-o", str(target)], capsys)
    assert (code, out) == (0, "")
    assert target.read_text(encoding="utf-8") == to_mermaid(parse_trace(basic_data()))


def test_cli_output_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_json(tmp_path, basic_data())
    target = tmp_path / "missing-dir" / "out.md"
    code, _, err = run([str(path), "-o", str(target)], capsys)
    assert code == 2
    assert err.startswith("error: input_invalid: ")


def test_cli_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = [
        simple_span(1, name="root", service="a", start=0, end=10 * MS),
        simple_span(2, 1, name="cache lookup", service="a", start=MS, end=3 * MS),
    ]
    path = write_json(tmp_path, data)
    _, plain, _ = run([str(path), "--no-durations"], capsys)
    assert "cache lookup" not in plain
    assert "p1-->>Client: ok\n" in plain
    _, internal, _ = run([str(path), "--show-internal"], capsys)
    assert "Note over p1: cache lookup" in internal


def test_cli_multiple_traces_and_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = "cd" * 16
    path = write_json(tmp_path, [simple_span(1), simple_span(2, trace_id=other)])
    code, out, err = run([str(path)], capsys)
    assert (code, out) == (2, "")
    assert err.startswith("error: multiple_traces: ")
    assert TRACE in err
    assert other in err
    code, out, _ = run([str(path), "--trace-id", other.upper()], capsys)
    assert code == 0
    assert "participant p1 as svc" in out


def test_cli_reports_orphans(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_json(tmp_path, [simple_span(1), simple_span(2, 99)])
    code, _, err = run([str(path)], capsys)
    assert code == 0
    assert err == f"orphan span: {sid(2)}\n"


def test_cli_caps_orphan_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_json(tmp_path, [simple_span(n, 5000 + n) for n in range(1, 26)])
    code, _, err = run([str(path)], capsys)
    lines = err.splitlines()
    assert code == 0
    assert lines[:20] == [f"orphan span: {sid(n)}" for n in range(1, 21)]
    assert lines[20:] == ["..."]


def test_cli_input_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run([str(tmp_path / "missing.json")], capsys)
    assert (code, out) == (2, "")
    assert err.startswith("error: input_invalid: ")
    path = write_json(tmp_path, {"unrelated": True})
    code, _, err = run([str(path)], capsys)
    assert code == 2
    assert err.startswith("error: unsupported_format: ")


def test_cli_usage_errors(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run([], capsys)
    assert code == 2
    assert "usage" in err
    code, _, _ = run(["file.json", "--bogus"], capsys)
    assert code == 2
    code, out, _ = run(["--help"], capsys)
    assert code == 0
    assert "trace2seq" in out


def test_main_reads_sys_argv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_json(tmp_path, basic_data())
    monkeypatch.setattr(sys, "argv", ["trace2seq", str(path)])
    assert main() == 0
    assert capsys.readouterr().out.startswith("sequenceDiagram\n")


def test_module_entry_point(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_json(tmp_path, basic_data())
    monkeypatch.setattr(sys, "argv", ["trace2seq", str(path)])
    with pytest.raises(SystemExit) as info:
        runpy.run_module("trace_to_sequence", run_name="__main__")
    assert info.value.code == 0
    assert capsys.readouterr().out.startswith("sequenceDiagram\n")
