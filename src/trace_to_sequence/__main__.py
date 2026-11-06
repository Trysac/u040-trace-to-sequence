"""Command line interface: ``python -m trace_to_sequence FILE``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .diagram import DiagramOptions, to_mermaid
from .errors import TraceError
from .model import find_orphans
from .parser import load_trace

MAX_ORPHAN_LINES = 20


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trace2seq",
        description="Convert a JSON trace into a Mermaid sequence diagram.",
    )
    parser.add_argument("file", metavar="FILE", help="OTLP/JSON or simple span JSON file")
    parser.add_argument("--trace-id", help="select one trace when the file holds several")
    parser.add_argument("--show-internal", action="store_true", help="render same-service spans")
    parser.add_argument("--no-durations", action="store_true", help="omit durations on returns")
    parser.add_argument("-o", "--output", metavar="OUT", help="write the diagram to OUT")
    parser.add_argument("--fenced", action="store_true", help="wrap the output in a mermaid fence")
    return parser


def _fail(code: str, detail: str) -> int:
    print(f"error: {code}: {detail}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit status (0 ok, 2 input or usage error)."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        status = exc.code
        if status is None:
            return 0
        return status if isinstance(status, int) else 2
    try:
        spans = load_trace(Path(args.file), trace_id=args.trace_id)
        options = DiagramOptions(
            show_internal=args.show_internal, show_durations=not args.no_durations
        )
        diagram = to_mermaid(spans, options)
    except TraceError as exc:
        return _fail(exc.code, exc.detail)
    orphans = find_orphans(spans)
    for span_id in orphans[:MAX_ORPHAN_LINES]:
        print(f"orphan span: {span_id}", file=sys.stderr)
    if len(orphans) > MAX_ORPHAN_LINES:
        print("...", file=sys.stderr)
    text = f"```mermaid\n{diagram}```\n" if args.fenced else diagram
    if args.output is None:
        sys.stdout.write(text)
        return 0
    try:
        with Path(args.output).open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        return _fail("input_invalid", f"cannot write output file ({type(exc).__name__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
