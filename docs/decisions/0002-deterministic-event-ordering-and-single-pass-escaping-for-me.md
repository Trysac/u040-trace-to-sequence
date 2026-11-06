# Deterministic event ordering and single-pass escaping for Mermaid sequence diagrams

Status: accepted (generated, pending human review)

## Context

A trace is a tree of spans with nanosecond timestamps, while a Mermaid sequence diagram is a flat, ordered list of arrows. Equal timestamps, zero-duration spans, same-service children, orphan spans and hostile span names (Mermaid treats '#', ';', ':', '<' and '>' specially) must still yield a stable, valid diagram. Untrusted JSON also needs hard limits: input size, span count, nesting depth and error message length.

## Decision

Every cross-service parent-child pair becomes a request at the child start and a return at the child end, ordered by the key (time, returns before requests, deeper returns first, shallower requests first, span id). A zero-duration span gets a return rank after requests of the same instant so a return never precedes its own request. Participants are named p1, p2, ... by first appearance after a synthetic Client. Labels are cut to max_label characters with an ellipsis and then escaped with one str.translate table, so escapes are never escaped twice. Parsing is strict: hex ids of 32/16 chars, nanosecond fields only as int or digit strings (never float or bool), iterative depth check (64) after json.loads, byte and span limits, and a single TraceError with stable codes whose messages quote at most 200 characters. Cycle, duplicate-id and multi-trace checks live in one shared function used by the parser and the renderer.

## Consequences

Output is deterministic and independent of input order, and hostile names cannot inject Mermaid syntax or extra lines. Strict numeric parsing never loses nanosecond precision, at the cost of rejecting float timestamps that lenient tools would accept. Zero-duration spans can appear slightly after a same-instant sibling request, and a child that starts exactly when its parent ends is drawn after the parent's return, as the ordering key demands. Protobuf OTLP, span events, links and attributes are out of scope.
