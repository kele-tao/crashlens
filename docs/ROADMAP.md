# Roadmap and deliberately dropped scope

This page is the honest backlog. Anything in the first list did **not** ship in
v1.0.0, with the reason. Anything in the second list is a planned next step.

## Dropped from v1.0.0

**Minified-JavaScript source-map resolution.**
A Node production stack points at `dist/app.min.js:1:48213`. Resolving that to
the original module needs a source-map parser and a virtual filesystem; it is a
multi-day feature on its own and half-solving it would produce confidently wrong
line numbers. v1.0.0 annotates the path as printed. Workaround: run the Node
service with `--enable-source-maps` (Node 12.12+) so the printed stack already
carries original paths, then crashlens works unchanged.

**Cross-process trace-id stitching.**
The brief's differentiating features are all single-log features. Stitching one
request across services requires an agreed id field and per-service log
locations, i.e. a deployment convention rather than a parser. Every crash does
carry its source file and line in the JSON output so an external joiner can be
built on top.

**A `--watch` tail mode.**
Tailing is easy; deciding when a partially written traceback is complete is not,
and a half-parsed crash that appears in a cluster for two seconds is worse than
no output. v1.0.0 stays batch-only. The workaround is to re-run `crashlens
cluster` from a loop; the tool costs one second per 10k records.

**Automatic baseline suppression.**
Ignoring known clusters sounds simple but needs a persisted baseline file, a
merge policy and a decision about what "new" means after a refactor. The
`--min-count` flag and `blame-since` cover the immediate need (separating
"deployed now" from "known noise"), so a baseline file is post-1.0.

**Per-language timezone inference.**
Timestamps are parsed as written (ISO 8601 with optional offset). Logs without
a timezone are treated as naive local time, which is right for a single-host log
and wrong when merging hosts in different zones. Documented rather than guessed.

## Next up

1. `--baseline known.json` support so CI can fail only on clusters that were not
   present in the previous run.
2. Request-id correlation: a `--trace-id` selector that keeps only the crashes
   whose surrounding log lines mention one id.
3. Additional parsers, in order of demand: .NET `System.Exception`, Ruby
   `NameError` backtraces, PHP `PHP Fatal error`.
4. A `crashlens explain <fingerprint>` command that prints the full rule table
   hit for one cluster, including the evidence substring that matched.
5. Optional `--diff <since>` mode that reports clusters which are new in the
   current log compared with a previous one, not just compared with a deploy.
