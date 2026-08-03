# Agentic Loop Engineering

A vault-backed engineering loop for Claude Code that handles **any** development work — features, bugs, incidents, refactors, spikes, chores — with state in a project-local Obsidian vault and tasks mirrored to GitHub Issues.

See [MANUAL.md](MANUAL.md) for practical instructions.

## Why

Context windows die between sessions. Vaults don't. Every phase reads the previous note and writes the next, so a run is resumable, auditable, and shareable.

The second reason matters more: **prompting skill varies across a team, and it shouldn't decide output quality.** Someone types "add rate limiting" and the loop still loads your standards, your accepted decisions, and your task format — because the skills carry the questions and the vault carries the context. Nobody has to already know what a good brief contains.

## Install

```bash
unzip agentic-loop.zip -d ~/.claude/skills/
cd <your repo> && ~/.claude/skills/agentic-loop/scripts/vault_init.sh
```

Restart Claude Code, then say **"set up the vault"**. The loop reads your repo and drafts the standards, context index, and glossary, asking you only about what it cannot infer. Until that is done, session start reports `SETUP NEEDED` and the loop will offer setup before starting new work — those files are loaded by every phase, so leaving them as templates is what produces generic output.

Needs Python 3, git, and `gh` for Issue mirroring. Obsidian needs Dataview for the board.

## Lanes

The loop picks one from the request rather than forcing everything through a feature pipeline.

| Lane | Phases |
|---|---|
| setup | reads the repo → standards, context, glossary (once per repo) |
| feature | talk → research? → adr? → plan → execute → verify → retro |
| bug | talk → diagnose → execute → verify |
| incident | diagnose → execute → verify → retro (required) |
| refactor | talk → adr? → plan → execute → verify |
| spike | talk → research → retro |
| chore | execute → verify |

## Layout

```
skills/
  loop            router — picks the lane, sequences phases, delegates
  vault           spine: layout, schema, IDs, context resolution
  setup           drafts standards and context by reading the repo
  talk            discovery → brief.md
  research        spikes and option analysis
  adr             decisions, via the architect agent
  plan            epics and tasks with acceptance criteria → GitHub Issues
  diagnose        reproduce → root cause → failing test
  execute         one task at a time, tests first
  verify          suite, four reviewers, one-page review packet, PR
  retro           write learnings back into standards and patterns
  grilling        reusable interview discipline
  domain-modeling keeps the shared language sharp

agents/
  architect  senior-engineer  sqa  security-reviewer
  reviewer-standards  reviewer-spec

bin/              on the Bash tool's PATH, so skills call these by name
  loop           status | doctor | next-id | new
  gh-sync        push | status | pull
  vault-init     scaffolds docs/vault/

scripts/          the implementations behind bin/
  loop.py  gh_sync.py  vault_init.sh

tests/            pytest suite over the vault tooling
```

## Design decisions worth knowing

**Phases versus disciplines.** Phases own artifacts and only `loop` sequences them; disciplines own techniques and anyone can call them. Orchestrators calling orchestrators nest unpredictably, and a run you can't follow is a run you can't review.

**Only the router claims a raw request.** That invariant lives entirely in the `description` fields, because dispatch is a judgement call and nothing arbitrates it at runtime. So each phase description names the artifact it owns and the precondition it needs, and points anything vaguer at `loop`. When `talk` or `plan` wins a request the router should have taken, the run gets no lane, no run log, and — the expensive one — no `SETUP NEEDED` gate. `tests/test_skills.py` guards this; it is the only thing that does.

**Two reviewers, deliberately blind to each other.** A reviewer holding the spec excuses sloppy code because it works; a reviewer holding the standards nitpicks code that solves the wrong problem. Be clear-eyed about how far this goes: `reviewer-standards` is *asked* not to read the brief, and it has `Read`, so the separation is a convention its prompt maintains, not a sandbox. It holds because the agent has no reason to defect, not because it can't.

**One task, one file.** A concurrency decision. Parallel agents touch different files, so git merges cleanly.

**IDs are allocated, not guessed.** Two agents eyeballing "the next number" pick the same one.

**No `hooks` field in `plugin.json`.** Claude Code auto-loads `hooks/hooks.json`; declaring it causes duplicate-load errors.

**Setup is not autonomous.** Reading a repo tells you what the code does, never what the team agreed. Setup drafts the first from evidence, marks it as inferred, and asks about the second.

**Nothing requires anything else.** Every skill works standalone — `/agentic-loop:adr` without a plan, `/agentic-loop:diagnose` without the loop. The loop is a convenience, not a cage. (Plugin skills are namespaced by plugin name; that prefix is not optional.)

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

The suite scaffolds a real vault with `vault_init.sh` in a temp directory and
drives the tooling against it, so it covers the two scripts agreeing on where
the vault is and on how frontmatter parses — the places they have drifted apart
before. `gh` is the only thing stubbed.

## Extending

Add a phase: drop a folder in `skills/`, add it to the lane table in `skills/loop/SKILL.md` **and to `LANES` in `scripts/loop.py`**, and add its note type to the schema in `skills/vault/SKILL.md`.

Write the description to name the artifact it owns and the precondition it needs, then defer anything vaguer to `loop`. The instinct is to write it pushy, because a single skill in isolation does tend to under-trigger — but every phase you make pushier competes with the router for the same request, and the router is the one that picks the lane and checks the setup gate. Pushiness belongs in `loop` alone.

Keep each `SKILL.md` under ~500 lines and push detail into `references/`, which loads only when needed.
