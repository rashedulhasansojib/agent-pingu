---
name: Bug report
about: Something in the plugin behaves wrong
labels: bug
---

## What happened

## What you expected

## The two lines from session start

Paste the `[pingu]` lines Claude Code prints when a session opens. They carry the
vault, lane, phase and autonomy, and they are the fastest way to tell a
misconfiguration from a real bug.

```
[pingu] vault: ...   lane: ...   phase: ...
[pingu] autonomy: ...
```

**If those lines do not appear at all**, say so — that is itself the symptom, and
it usually means the SessionStart hook is not running rather than that the loop
is confused.

## Environment

- OS:
- `python3 --version`:
- Installed for yourself (`~/.claude/skills/`) or carried by the repo?
- Output of `claude plugin list`:

## Anything you already ruled out

Optional, and genuinely useful — it stops two people checking the same thing.
