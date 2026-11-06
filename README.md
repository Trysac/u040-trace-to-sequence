# trace-to-sequence

[![PyPI version](https://img.shields.io/pypi/v/trysac-trace-to-sequence)](https://pypi.org/project/trysac-trace-to-sequence/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-trace-to-sequence)](LICENSE)
[![CI](https://github.com/Trysac/u040-trace-to-sequence/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u040-trace-to-sequence/actions/workflows/ci.yml)

Convert OTLP JSON or simple span JSON traces into Mermaid sequence diagrams of calls and returns between services, with safe label escaping

## Problem

Trace viewers show waterfalls, but design docs need the service-to-service conversation. Drawing
sequence diagrams by hand drifts from reality. This CLI turns an exported trace into a Mermaid
sequence diagram that can be pasted into Markdown.

## Install

```sh
pip install trysac-trace-to-sequence
# or
uv add trysac-trace-to-sequence
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from trace_to_sequence import DiagramOptions, parse_trace, to_mermaid

spans = parse_trace(
    [
        {
            "trace_id": "ab" * 16,
            "span_id": "01" * 8,
            "parent_id": None,
            "name": "GET /",
            "service": "frontend",
            "start": 0,
            "end": 30_000_000,
        },
        {
            "trace_id": "ab" * 16,
            "span_id": "02" * 8,
            "parent_id": "01" * 8,
            "name": "GET /users",
            "service": "api",
            "start": 1_000_000,
            "end": 13_000_000,
        },
    ]
)
print(to_mermaid(spans, DiagramOptions()))
```

Output:

```text
sequenceDiagram
autonumber
participant Client
participant p1 as frontend
participant p2 as api
Client->>p1: GET /
p1->>p2: GET /users
p2-->>p1: ok 12.0 ms
p1-->>Client: ok 30.0 ms
```

`load_trace(path, trace_id=None, max_bytes=50_000_000, max_spans=10_000)` reads a file instead.

### CLI

```sh
trace2seq FILE [--trace-id ID] [--show-internal] [--no-durations] [-o out.md] [--fenced]
```

Exit codes: `0` success, `2` input or usage error (stderr `error: <code>: <detail>`).
Orphan spans are listed on stderr (at most 20, then `...`).

Error codes (`TraceError.code`): `unsupported_format`, `invalid_id`, `multiple_traces`,
`empty_trace`, `parent_cycle`, `input_too_large`, `input_invalid`.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
