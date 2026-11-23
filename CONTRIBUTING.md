# Contributing

Thanks for looking. crashlens is deliberately small: stdlib only, no runtime
dependencies, no network. That constraint is the feature, so please keep it.

## Setup

```bash
git clone https://github.com/kele-tao/crashlens
cd crashlens
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
ruff check .
```

The bundled example repository is materialised automatically by
`tests/conftest.py` for a fresh clone. To rebuild it by hand:

```bash
python examples/init_demo_repo.py --force
```

## Ground rules

- **No new runtime dependency** without a discussion in an issue first.
- **Every parser change needs a fixture.** Add the log excerpt to an existing
  test module or a new one under `tests/`; the fixture should be a real shape
  copied from a real traceback, not a simplified invention.
- **Determinism is a test.** Output must be byte identical for identical input.
  No wall-clock values in reports, no unordered dict iteration, no locale
  dependent formatting.
- **Errors are copy.** A user-facing failure prints one line starting with
  `crashlens: error:` and exits 2. Never a raw traceback.
- **If you quote a number in the README, produce it.** Re-run
  `python benchmarks/run.py` and commit both `results.json` and `RESULTS.md`.

## Pull requests

1. One concern per pull request.
2. `pytest -q` and `ruff check .` must be clean.
3. Add or update the changelog entry under `## [Unreleased]`.
4. Describe the bug or format you hit in the pull request body; a screenshot of
   the actual command output helps reviewers more than prose.

## Reporting bugs

Open an issue with the bug template. Paste the traceback **with the values you
care about redacted** and the exact `crashlens` command. If the parser produced
the wrong result, include what it printed and what you expected.

## Code of conduct

Be direct, be kind, assume good faith. Review comments target the code.
