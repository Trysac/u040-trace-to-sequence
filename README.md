# trace-to-sequence

[![PyPI version](https://img.shields.io/pypi/v/trysac-trace-to-sequence)](https://pypi.org/project/trysac-trace-to-sequence/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-trace-to-sequence)](LICENSE)
[![CI](https://github.com/Trysac/u040-trace-to-sequence/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u040-trace-to-sequence/actions/workflows/ci.yml)

Convert OTLP JSON or simple span JSON traces into Mermaid sequence diagrams of calls and returns between services, with safe label escaping

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-trace-to-sequence
# or
uv add trysac-trace-to-sequence
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import trace_to_sequence

# normalize() trims surrounding whitespace and lower-cases the text.
print(trace_to_sequence.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    trace_to_sequence.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
