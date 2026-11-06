# Project record

## Objective

Convert OTLP JSON or simple span JSON traces into Mermaid sequence diagrams of calls and returns between services, with safe label escaping

## Scope

- In scope: the public API documented in [README.md](../README.md), typed and tested.
- Out of scope: anything that needs runtime dependencies or I/O without an accepted ADR.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 451255 / 94719 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.7316 |

## Factory run u040 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2607 | 82365 | 0 | 4246 | 0.4149 |
| fix-1 | claude-sonnet-5-5 | no | 4 | 343 | 5853 | 24543 | 0.0205 |
| fix-2 | claude-sonnet-5-5 | no | 10 | 1309 | 8898 | 72750 | 0.0426 |
| audit | claude-sonnet-5-5 | no | 14 | 3977 | 25600 | 151637 | 0.1190 |
| fix-3 | claude-sonnet-5-5 | no | 6 | 1400 | 7842 | 40577 | 0.0377 |
| fix-4 | claude-sonnet-5-5 | no | 6 | 713 | 6833 | 40618 | 0.0283 |
| docs | claude-haiku-5-5 | no | 114237 | 4612 | 0 | 0 | 0.0686 |

Total: $0.7316. Prices: Anthropic list prices.
