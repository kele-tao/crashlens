# Security policy

## Scope

crashlens reads files that were produced by a crashed process and renders them
to a terminal, JSON or HTML. The relevant security properties are:

- **No network access.** The tool never opens a socket. Its only subprocess is
  `git`, used for blame and deploy correlation, and it is invoked with an
  explicit argument list (never a shell) so a crafted path cannot inject a
  command.
- **No code execution from input.** Tracebacks are parsed with regular
  expressions and state machines; nothing from the log is evaluated, imported or
  executed.
- **HTML output is escaped.** Every value interpolated into the HTML report
  passes through `html.escape`, so a hostile exception message such as
  `<script>alert(1)</script>` is rendered as text. A regression test covers this.
- **No secret exfiltration.** crashlens prints whatever the log contains; it
  never reads environment variables, key files or credentials. The benchmark
  script writes only inside the repository.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | yes |

## Reporting a vulnerability

Open a private security advisory on GitHub
(https://github.com/kele-tao/crashlens/security/advisories/new) rather than a
public issue. Include the version, the command, a minimal input file and what
you observed. Expect an acknowledgement within seven days.

## Hardening notes for users

- Logs often contain personal data. Redact before pasting a report into an
  issue; crashlens prints exception messages verbatim by design.
- `crashlens annotate` runs `git blame` in the repository you point it at. Point
  `--repo` at a checkout you trust, exactly as you would for `git` itself.
- The HTML report is self-contained and safe to attach to a ticket; it contains
  no scripts and no external requests.
