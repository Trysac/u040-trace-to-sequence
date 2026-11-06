# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add `trace_to_sequence`: convert OTLP/JSON or simple span JSON traces into Mermaid sequence diagrams (`parse_trace`, `load_trace`, `to_mermaid`, `python -m trace_to_sequence`) with strict parsing, size and depth limits, and safe label escaping.
- Initial project structure from the factory utility template.
