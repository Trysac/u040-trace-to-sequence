"""Parse OTLP/JSON and simple span JSON into immutable :class:`Span` objects."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .errors import TraceError, preview
from .model import Span, Status, check_spans

__all__ = ["load_trace", "parse_trace"]

logger = logging.getLogger(__name__)

MAX_DEPTH = 64
DEFAULT_MAX_BYTES = 50_000_000
DEFAULT_MAX_SPANS = 10_000
_MAX_NS = 2**64 - 1
_UNKNOWN_SERVICE = "unknown_service"
_DIGITS = re.compile(r"[0-9]{1,20}")
_ID_PATTERNS = {
    32: re.compile(r"[0-9a-fA-F]{32}"),
    16: re.compile(r"[0-9a-fA-F]{16}"),
}
_ISO = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt ]([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.([0-9]{1,9}))?(Z|z|[+-][0-9]{2}:[0-9]{2})"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_OTLP_STATUS_CODES: dict[int, Status] = {0: "unset", 1: "ok", 2: "error"}
_OTLP_STATUS_NAMES: dict[str, Status] = {
    "STATUS_CODE_UNSET": "unset",
    "STATUS_CODE_OK": "ok",
    "STATUS_CODE_ERROR": "error",
}
_SIMPLE_STATUSES: dict[str, Status] = {"ok": "ok", "error": "error", "unset": "unset"}


def _invalid(detail: str) -> TraceError:
    return TraceError("input_invalid", detail)


def _check_depth(data: Any) -> None:
    """Reject JSON nested deeper than ``MAX_DEPTH`` without recursion."""
    stack: list[tuple[Any, int]] = [(data, 1)]
    while stack:
        node, depth = stack.pop()
        children: list[Any]
        if isinstance(node, dict):
            children = list(node.values())
        elif isinstance(node, list):
            children = node
        else:
            continue
        if depth > MAX_DEPTH:
            raise _invalid(f"JSON nesting deeper than {MAX_DEPTH} levels")
        stack.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))


def _obj(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid(f"{what} must be an object")
    return value


def _list(value: object, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise _invalid(f"{what} must be an array")
    return value


def _opt_list(parent: dict[str, Any], key: str) -> list[Any]:
    value = parent.get(key)
    if value is None:
        return []
    return _list(value, key)


def _hex_id(value: object, length: int, field: str) -> str:
    if not isinstance(value, str) or _ID_PATTERNS[length].fullmatch(value) is None:
        raise TraceError(
            "invalid_id", f"{field} must be {length} hex characters, got {preview(value)}"
        )
    return value.lower()


def _parent_id(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _hex_id(value, 16, field)


def _parse_ns(value: object, field: str) -> int:
    number: int | None = None
    if isinstance(value, int) and not isinstance(value, bool):
        number = value
    elif isinstance(value, str) and _DIGITS.fullmatch(value) is not None:
        number = int(value)
    if number is None or not 0 <= number <= _MAX_NS:
        raise _invalid(f"{field} must be an integer nanosecond count")
    return number


def _iso_to_ns(match: re.Match[str], field: str) -> int:
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    hour = int(match.group(4))
    minute = int(match.group(5))
    second = int(match.group(6))
    fraction = int((match.group(7) or "").ljust(9, "0"))
    zone = match.group(8)
    try:
        if zone in ("Z", "z"):
            offset = timedelta(0)
        else:
            offset_minutes = int(zone[4:6])
            if offset_minutes > 59:
                raise ValueError("offset minutes out of range")
            offset = timedelta(hours=int(zone[1:3]), minutes=offset_minutes)
            if zone[0] == "-":
                offset = -offset
        moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone(offset))
        delta = moment - _EPOCH
    except (ValueError, OverflowError) as exc:
        raise _invalid(f"{field} is not a valid ISO 8601 timestamp") from exc
    number = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + fraction
    if not 0 <= number <= _MAX_NS:
        raise _invalid(f"{field} is outside the supported time range")
    return number


def _parse_time(value: object, field: str) -> int:
    if isinstance(value, str):
        match = _ISO.fullmatch(value)
        if match is not None:
            return _iso_to_ns(match, field)
    return _parse_ns(value, field)


def _otlp_status(value: object) -> Status:
    if value is None:
        return "unset"
    code = _obj(value, "status").get("code")
    if code is None:
        return "unset"
    if isinstance(code, int) and not isinstance(code, bool) and code in _OTLP_STATUS_CODES:
        return _OTLP_STATUS_CODES[code]
    if isinstance(code, str) and code in _OTLP_STATUS_NAMES:
        return _OTLP_STATUS_NAMES[code]
    raise _invalid(f"unknown status code {preview(code)}")


def _simple_status(value: object) -> Status:
    if value is None:
        return "unset"
    if isinstance(value, str) and value in _SIMPLE_STATUSES:
        return _SIMPLE_STATUSES[value]
    raise _invalid(f"unknown status {preview(value)}")


def _make_span(
    trace_id: str,
    span_id: str,
    parent_id: str | None,
    name: object,
    service: str,
    start_ns: int,
    end_ns: int,
    status: Status,
) -> Span:
    if not isinstance(name, str):
        raise _invalid("span name must be a string")
    if end_ns < start_ns:
        raise _invalid(f"span {span_id} ends before it starts")
    return Span(trace_id, span_id, parent_id, name, service, start_ns, end_ns, status)


def _service_name(resource_span: dict[str, Any]) -> str:
    resource = resource_span.get("resource")
    if resource is None:
        return _UNKNOWN_SERVICE
    for attribute in _opt_list(_obj(resource, "resource"), "attributes"):
        if isinstance(attribute, dict) and attribute.get("key") == "service.name":
            value = attribute.get("value")
            text = value.get("stringValue") if isinstance(value, dict) else None
            return text if isinstance(text, str) and text else _UNKNOWN_SERVICE
    return _UNKNOWN_SERVICE


def _otlp_span(raw: object, service: str) -> Span:
    obj = _obj(raw, "span")
    return _make_span(
        _hex_id(obj.get("traceId"), 32, "traceId"),
        _hex_id(obj.get("spanId"), 16, "spanId"),
        _parent_id(obj.get("parentSpanId"), "parentSpanId"),
        obj.get("name"),
        service,
        _parse_ns(obj.get("startTimeUnixNano"), "startTimeUnixNano"),
        _parse_ns(obj.get("endTimeUnixNano"), "endTimeUnixNano"),
        _otlp_status(obj.get("status")),
    )


def _too_many(max_spans: int) -> TraceError:
    return TraceError("input_too_large", f"trace has more than {max_spans} spans")


def _parse_otlp(data: dict[str, Any], max_spans: int) -> list[Span]:
    spans: list[Span] = []
    for resource_span in _list(data.get("resourceSpans"), "resourceSpans"):
        resource_obj = _obj(resource_span, "resourceSpans entry")
        service = _service_name(resource_obj)
        for scope_span in _opt_list(resource_obj, "scopeSpans"):
            scope_obj = _obj(scope_span, "scopeSpans entry")
            for raw in _opt_list(scope_obj, "spans"):
                if len(spans) >= max_spans:
                    raise _too_many(max_spans)
                spans.append(_otlp_span(raw, service))
    return spans


def _simple_span(raw: object) -> Span:
    obj = _obj(raw, "span")
    service = obj.get("service")
    if not isinstance(service, str) or not service:
        raise _invalid("service must be a non-empty string")
    return _make_span(
        _hex_id(obj.get("trace_id"), 32, "trace_id"),
        _hex_id(obj.get("span_id"), 16, "span_id"),
        _parent_id(obj.get("parent_id"), "parent_id"),
        obj.get("name"),
        service,
        _parse_time(obj.get("start"), "start"),
        _parse_time(obj.get("end"), "end"),
        _simple_status(obj.get("status")),
    )


def _parse_simple(data: list[Any], max_spans: int) -> list[Span]:
    if len(data) > max_spans:
        raise _too_many(max_spans)
    return [_simple_span(raw) for raw in data]


def parse_trace(
    data: Any, trace_id: str | None = None, max_spans: int = DEFAULT_MAX_SPANS
) -> list[Span]:
    """Convert decoded JSON into the spans of exactly one trace.

    The format is detected automatically: a dict with ``resourceSpans`` is OTLP/JSON,
    a list of objects is the simple format (``trace_id``, ``span_id``, ``parent_id``,
    ``name``, ``service``, ``start``, ``end`` and an optional ``status``). Ids are hex
    (32 characters for traces, 16 for spans) and are lower-cased. Nanosecond fields
    are Python ints or digit strings; the simple format also accepts ISO 8601 with
    an offset.

    Args:
        data: the decoded JSON document.
        trace_id: select this trace when the document holds several.
        max_spans: maximum number of spans accepted.

    Raises:
        TraceError: with a code from ``ErrorCode`` when the input is not acceptable.
    """
    wanted = None if trace_id is None else _hex_id(trace_id, 32, "trace_id")
    _check_depth(data)
    if isinstance(data, dict) and "resourceSpans" in data:
        spans = _parse_otlp(data, max_spans)
    elif isinstance(data, list):
        spans = _parse_simple(data, max_spans)
    else:
        raise TraceError("unsupported_format", "expected OTLP/JSON or a list of simple spans")
    if wanted is not None:
        spans = [item for item in spans if item.trace_id == wanted]
    check_spans(spans)
    logger.debug("parsed %d spans", len(spans))
    return spans


def load_trace(
    path: Path,
    trace_id: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_spans: int = DEFAULT_MAX_SPANS,
) -> list[Span]:
    """Read a JSON trace file and return its spans (see :func:`parse_trace`).

    At most ``max_bytes + 1`` bytes are ever read; larger files raise
    ``input_too_large``. Unreadable, non UTF-8 or malformed files raise
    ``input_invalid``.
    """
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise _invalid(f"cannot read input file ({type(exc).__name__})") from exc
    if len(raw) > max_bytes:
        raise TraceError("input_too_large", f"input exceeds {max_bytes} bytes")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except RecursionError as exc:
        raise _invalid(f"JSON nesting deeper than {MAX_DEPTH} levels") from exc
    except ValueError as exc:
        raise _invalid("input is not valid UTF-8 JSON") from exc
    return parse_trace(data, trace_id=trace_id, max_spans=max_spans)
