# Contributing

## The short version

```bash
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/python -m pytest tests/ -q
claude plugin validate .
```

Both must pass before a commit. Then **run the actual commands you changed** —
see below, because that is not a formality here.

## Read CLAUDE.md first

`CLAUDE.md` at the repo root is the real contributor guide. It is not a summary
of this file; this file is a pointer to it. It documents the traps that have
already cost someone a day:

- **Frontmatter is fragile in a way nothing warns you about.** An unquoted
  `key: value` inside a YAML string silently breaks the block, Claude Code drops
  the *entire* frontmatter, and the skill loads nameless and never triggers. No
  error appears anywhere.
- **Docs and code are coupled**, and five pairs must move together. The tests
  fail if any drifts.
- **Plugin options do not resolve themselves.** Two mechanisms that look like
  they work do not, and all three options were no-ops for eleven commits because
  of it.

## Three rules that exist because they were broken

**Verify against the real CLI, not just the suite.** A green suite here has
shipped alongside five real bugs — the `ready` semantics on gates, a `gh issue
list --search` rate-limit trap, install instructions pointing at a zip nothing
built, an `AttributeError` on Windows, and a documented team install that gave
teammates an empty directory. Run the commands after the tests pass.

**Never chain `git commit` after `pytest`.** Gate on the exit code. Committing on
red has happened here.

**Never build a shell command as a string.** zsh does not word-split unquoted
`$var`, so `for c in "gate talk"; do pingu $c; done` passes one argument and
reports 127. Pass real arguments and forward with `"$@"`. Capture stderr rather
than discarding it, so 127 and 1 stay distinguishable — a fixture that discarded
it turned one Windows failure into 250 identical unreadable ones.

## If you add a guard, mutation-test it

This is the project's main quality mechanism and its most-repeated failure.
**Break the thing your guard watches and confirm it goes red.** Three guards here
were vacuous when first written — one whose `-k` filter matched an assertion
message instead of a test name and so ran zero tests, one whose regex matched an
unrelated heading, and one whose `"Edit" in m` check passed on a matcher naming
only `MultiEdit`.

A guard you did not watch fail is not a guard. Say in the commit message which
mutations you tried.

## What good looks like here

Comments and prose explain **why**, not what, and are written for a colleague who
will disagree — state the counter-argument where one exists. Prefer saying a
thing is unverified over implying it is settled; several notes in this repo are
more useful for admitting their limits than for their conclusions.

There is no formatter or linter. Match the surrounding code.

## Pull requests

Branch, then one PR. In the body: what changed, what you verified and how, and
what you did *not* verify. That last part is the one reviewers here actually use.

CI runs pytest on Linux (3.9 and 3.13), macOS and Windows, plus `bash -n` over
`bin/` and `vault_init.sh`, and `claude plugin validate`.

## Reporting a security issue

Not here — see [SECURITY.md](SECURITY.md). Issues are public when filed.
