"""Convert OTLP/JSON or simple span JSON traces into Mermaid sequence diagrams."""

from __future__ import annotations

import logging

from .diagram import DiagramOptions, to_mermaid
from .errors import ErrorCode, TraceError
from .model import Span, find_orphans
from .parser import load_trace, parse_trace

__all__ = [
    "DiagramOptions",
    "ErrorCode",
    "Span",
    "TraceError",
    "__version__",
    "find_orphans",
    "load_trace",
    "parse_trace",
    "to_mermaid",
]

__version__ = "0.1.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())
