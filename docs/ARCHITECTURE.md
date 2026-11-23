# Architecture notes

The codebase is one package, eleven small modules, no runtime dependencies.

```
src/crashlens/
  models.py       Frame, Segment, Crash  (dataclasses, no logic beyond properties)
  parsers.py      one state machine per runtime -> list[Crash]
  repo.py         Repo: path index + frame -> file resolution + normalise_path
  fingerprint.py  normalisation and sha256 fingerprint, actionable-frame choice
  cluster.py      Cluster, grouping, recency ranking, blame attachment
  heuristics.py   12 rules, each with evidence and a concrete next step
  gitinfo.py      defensive git wrapper: blame, log, changed files, revisions
  annotate.py     source context window + blame rendering
  report.py       terminal table, deterministic JSON, self-contained HTML
  engine.py       the operations the CLI calls (analyse, annotate_first, blame_since)
  cli.py          argparse wiring, exit codes, friendly errors
```

## Data flow

`parse_paths` reads files (or walks a directory for `.log/.txt/.out/.err/.trace`),
`parse_text` normalises newlines and ANSI escapes, attaches the inherited
timestamp to each line, then scans for a recognised crash header. A header opens
a block whose end is found by the runtime-specific `_*_end` scanners; the block
is handed to the matching `_parse_*_lines` function. The result is a `Crash`
with a primary-first list of `Segment`s, each holding outermost-first `Frame`s.

`cluster_crashes` fingerprints every crash and buckets them; `rank` sorts by
`count * (1 + recency)` where recency is the cluster's last-seen position inside
the log's time window.

`Repo` indexes the checkout once (60k file cap) and resolves frame paths by exact
relative path, then suffix, then basename, skipping vendor directories.
`actionable_frame` walks the cause chain root-first and returns the innermost
frame that resolves and is not vendored; with no repository it returns the
innermost frame of the primary exception.

`annotate_crash` resolves that frame, reads the file, and slices a context window
(0-6 lines) around the target. `git blame --porcelain -L n,n` supplies the
attribution; the number of days between that commit and the crash's first
occurrence is computed in `days_between`.

## Invariants worth knowing

- **Frames are outermost-first, always.** Each parser reverses where its runtime
  prints innermost-first (Java, Node, Go). `Crash.site_frame` therefore returns
  the last frame that has a source location.
- **`segments[0]` is the exception the user saw; `chain` is root-cause-first.**
  `relation` lives on a segment and says why it is in the chain ("cause" /
  "context"), so `segments[1].relation == "cause"` means the second segment is
  the cause of the first.
- **Determinism.** No `datetime.now()` in reports except the explicit HTML footer
  stamp (which the API accepts as an argument for tests), no set iteration in
  output, JSON keys sorted.
- **Failure is a message, not a traceback.** `engine` raises `UserError`; the CLI
  catches it, prints one line and exits 2.
