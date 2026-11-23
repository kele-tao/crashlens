# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-02-14

### Added

- Parsers for Python (including chained exceptions with cause and context
  markers), Node.js (including `node:internal` and bare `at <fn>` frames),
  Java (`Caused by:`, `... N more`, native frames), Go `panic:` with goroutine
  frames and `created by`, and Rust panics with or without a backtrace.
- Deterministic fingerprinting of crashes: language, normalised exception chain
  and up to six call sites per segment, with line numbers, addresses, temp paths
  and numeric message values removed.
- Crash clustering with first/last seen, per-cluster sample traceback, language
  mix and a frequency-times-recency ranking.
- Root-cause heuristics: twelve exception patterns mapped to a concrete next
  step, with the matched rule exposed in terminal, JSON and HTML output.
- Actionable frame selection: the deepest frame inside the checkout that is not
  vendored.
- `annotate` command: context window with arrows around the failing line and
  `git blame` attribution, including the number of days between the blamed
  commit and the first crash.
- `blame-since` command: correlates crash clusters with the files and commits
  that changed in a deploy window.
- Terminal, JSON and self-contained HTML renderers; the HTML report contains
  inline SVG bars and no external assets.
- Documented exit codes: 0 report produced, 1 nothing matched, 2 usage error.
- Benchmark harness (`benchmarks/run.py`) that writes `results.json` and
  `RESULTS.md`; 10k crash records parse and cluster in about one second.
- 114 pytest tests covering all five parsers, clustering, heuristics, repository
  matching, CLI contract and renderers.

[Unreleased]: https://github.com/kele-tao/crashlens/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/kele-tao/crashlens/releases/tag/v1.0.0
