# Security

## Reporting a vulnerability

Use GitHub's [private vulnerability
reporting](https://github.com/rashedulhasansojib/agent-pingu/security/advisories/new)
rather than opening an Issue. Issues are public the moment they are filed.

Expect a first reply within a week. If nothing comes back, open a public Issue
saying only that you sent a private report and heard nothing — no details.

## What this plugin actually touches

Worth stating plainly, because the risk is not where it usually is. This plugin
ships no server, stores no credentials, and makes no network calls of its own.
What it does is **read files that a pull request can change, and put what it
finds in front of an agent that acts on them.**

Two things follow.

**The SessionStart hook runs unprompted.** Checking out a branch is enough to
execute `pingu status` against whatever that branch's `.claude/settings.json`
says. No click, no prompt.

**The asset is not data at rest.** It is what the agent can be induced to
believe. A settings file that redirects the vault, or an Issue body that gets
appended into a task note, is not stealing anything — it is changing what the
loop reads as authoritative project state, and therefore what it does next.

`docs/vault/decisions/ADR-0004-untrusted-settings-are-a-trust-boundary.md` is the
threat model, written after a security review found three ways a committed
settings file could steer the tooling. It also documents the two protections that
are **best-effort rather than guaranteed**, and says so on purpose:

- the `O_NOFOLLOW` on the one file written at a steerable path is POSIX-only, so
  a platform without the flag keeps a working allocator and loses that guard;
- the autonomy floor cannot fire when the personal settings file cannot be read
  at the path home resolution names.

## Known, unfixed, and disclosed here on purpose

**The personal settings path is assumed trustworthy and nothing establishes that
it is.** ADR-0004 rule 2 lets `~/.claude/settings.json` set an autonomy floor
that a repo-committed file may not loosen. But `HOME=""` makes `Path.home()`
return `Path(".")` on Python 3.9 and `/` on 3.13 — both are in the CI matrix and
they disagree. If the `env` key in a committed `.claude/settings.json` reaches
hook subprocesses, the floor is bypassable by exactly the file it defends
against.

**This is unverified.** It needs one live session to settle: put
`{"env": {"HOME": "/nonexistent"}}` in a project's settings and see whether
`pingu status` still finds the personal file. It is written here rather than left
in a private note because the severity is low — it needs a hostile branch and a
specific key — and because a security file that lists only solved problems is
worth very little.

The autonomy level is **advisory in any case**: it is a string the model reads,
not an enforced permission. Do not rely on it as a control. The `PreToolUse`
setup guard is likewise a quality gate, not a security boundary, and
`docs/vault/standards/security.md` says so outright.

## What is out of scope

- Anything requiring an attacker to already have write access to your machine or
  your `~/.claude`.
- Claude Code itself, its permission system, or the `gh` CLI. Report those
  upstream.
- The autonomy level or the setup guard failing to stop a *cooperative* agent —
  neither is designed to.

## If you run this on someone else's branch

The realistic precaution, and the one this plugin cannot take for you: treat
`.claude/settings.json` in a pull request the way you would treat a change to
`Makefile` or a CI workflow. Read it before you check the branch out.
