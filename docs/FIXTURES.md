# What the bundled fixtures are

Every file under `examples/` was produced by actually running the program or
by copying the exact text a real runtime prints. Nothing here is invented
output: the traceback shapes follow the format strings in CPython 3.12, Node 22,
OpenJDK 17, Go 1.x and Rust 1.7x.

## Crash logs

| File | Runtime | What it demonstrates |
| --- | --- | --- |
| `python_error.log` | Python | A two-segment cause chain: `KeyError: 'items'` wrapped by `RuntimeError("order enrichment failed for checkout")` via `raise ... from exc`, inside a timestamped log. Two occurrences, 3m48s apart. |
| `node_async_error.log` | Node.js | `TypeError: Cannot read properties of undefined` thrown from `Array.map` inside an async handler; includes a `node:internal/process/task_queues` frame and a bare `at Array.map (<anonymous>)` frame. |
| `java_npe.log` | Java | `NullPointerException` with a `Caused by: IllegalStateException`, a Spring framework frame and `... 24 more` elision. Two occurrences. |
| `go_panic.log` | Go | `panic: runtime error: invalid memory address or nil pointer dereference` with `[signal SIGSEGV...]`, a goroutine header, three frames and a `created by` line. |
| `rust_panic.log` | Rust | `thread 'main' panicked at 'called Option::unwrap() on a None value', src/parser.rs:44:13` plus the `RUST_BACKTRACE` note. Two occurrences. |

## Demo repository

`examples/demo_repo/` is a small, real checkout with a real two-commit history:

| Commit | Date | Author | Subject |
| --- | --- | --- | --- |
| `3ab7b0b` | 2025-01-06 | Alice Chen | feat: order enrichment pipeline with JSON decoding |
| `61444e8` | 2025-02-11 | Priya Nair | refactor: trust partner payload in pick_sku |

The regression is in `pipeline.py`: commit one guards `document.get("items") or []`,
commit two replaces it with `document["items"]`. The crash logs are timestamped
2025-02-14, three days after the second commit — which is exactly what
`crashlens annotate` reports.

The commit hashes above change whenever the fixture is regenerated (the commit
date is fixed, but the tree hash is not), so treat them as illustrative: run
`python examples/init_demo_repo.py --force` and then `git -C examples/demo_repo log`
for the authoritative values. The README transcript shows the hashes from the
build of this release.

The other source files in the demo repository exist so that the non-Python
examples have somewhere to resolve: `handlers/checkout.js`,
`lib/orders.js`, `com/acme/OrderService.java`, `internal/queue/worker.go` and
`src/parser.rs`. Only `pipeline.py` is part of the regression story.

## Reproducing the screenshots

```bash
# terminal render of annotate (docs/screenshot.png)
python ../.tools/term_screenshot.py --cmd "python -m crashlens annotate examples/python_error.log --repo examples/demo_repo" --out docs/screenshot.png --title "crashlens annotate" --cwd .

# terminal render of cluster (docs/cluster.png)
python ../.tools/term_screenshot.py --cmd "python -m crashlens cluster examples --repo examples/demo_repo --top 4" --out docs/cluster.png --title "crashlens cluster" --cwd .

# HTML report rendered by crashlens itself (docs/report.html -> docs/report.png)
python -m crashlens cluster examples --repo examples/demo_repo --html docs/report.html --json > /dev/null
python ../.tools/screenshot.py --html docs/report.html --out docs/report.png --full-page
```

`term_screenshot.py` and `screenshot.py` are the workspace helpers described in
`PROJECT_SPEC.md`; they render the real stdout of the real command. They live
outside this repository and are not required to use crashlens.
