# Agent Pingu

A vault-backed engineering loop for Claude Code that handles **any** development work — features, bugs, incidents, refactors, spikes, chores — with state in a project-local Obsidian vault and tasks mirrored to GitHub Issues.

See [MANUAL.md](MANUAL.md) for practical instructions, and
[WALKTHROUGH.md](WALKTHROUGH.md) for an end-to-end run on a real project —
install, setup, every phase, and the two things that went wrong.

## Why

Context windows die between sessions. Vaults don't. Every phase reads the previous note and writes the next, so a run is resumable, auditable, and shareable.

The second reason matters more: **prompting skill varies across a team, and it shouldn't decide output quality.** Someone types "add rate limiting" and the loop still loads your standards, your accepted decisions, and your task format — because the skills carry the questions and the vault carries the context. Nobody has to already know what a good brief contains.

## Install

Any folder under a skills directory that contains `.claude-plugin/plugin.json`
loads as a plugin — no marketplace, no install step. So put this there:

```bash
git clone <this repo> ~/.claude/skills/agent-pingu        # personal
# or, into a repo, to share it with the team through git:
git clone <this repo> <your repo>/.claude/skills/agent-pingu
```

Restart Claude Code and confirm with `claude plugin list` — you should see
`agent-pingu@skills-dir`. Then scaffold a repo:

```bash
cd <your repo> && ~/.claude/skills/agent-pingu/scripts/vault_init.sh
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

## Gates

Every phase has an exit condition. `pingu gate <phase>` evaluates it, so the model
isn't asked whether it met its own gate — the one party that can't answer that.

```bash
pingu gate                     # gate whatever phase `pingu status` infers
pingu gate verify              # show what would run
pingu gate verify --execute    # actually run the declared commands
```

Each check comes back as one of five verdicts, and the last two are the reason
this is worth having:

| Verdict | Means |
|---|---|
| `passed` / `failed` | Genuinely checked. A `failed` stops the phase. |
| `planned` | A command gate, not run. Running your suite is a side effect, so you opt in with `--execute`. |
| `not-declared` | A command gate whose command the vault never declared. **Not a pass.** |
| `manual-review` | No tool can decide this. **Never auto-passes.** |

Checks come in three kinds — `vault` (computed from the notes), `command` (runs
what `context.md` declares), and `manual`. Only three gates are settleable by
tooling alone:

| Gate | What the runner can do |
|---|---|
| `talk` `research` `plan` | Fully checked |
| `setup` `execute` `verify` `retro` | Part checked, part manual |
| `adr` `diagnose` | Entirely human judgement |

So most phases end with checks still outstanding. **That is the intended answer.**
Forcing every gate into something machine-checkable is exactly how a green tick
stops meaning anything, and an honest "two checks passed, one needs your eyes"
is worth more than a confident tick that meant "the model said so."

### Declaring the commands

`verify` and `execute` run whatever `context.md` declares in its frontmatter:

```yaml
test_command: ["pytest", "-q"]
lint_command: ["ruff", "check", "."]
```

`setup` fills these in from your test config and CI. Leave them empty and the
gate reports `not-declared` rather than passing.

**Lists, never strings.** A list goes straight to the process; a string would
need a shell to interpret, and `context.md` is a file the model writes. A string
is rejected with a message telling you to use a list.

## Layout

```
.claude-plugin/
  plugin.json     manifest, and the userConfig prompted at enable time
                  (vault_dir, gh_repo, autonomy)

skills/           phases advance the state machine; disciplines are techniques
  start           router — picks the lane, sequences phases, delegates
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

agents/           each runs in its own context, which is the point of them
  architect  senior-engineer  sqa  security-reviewer
  reviewer-standards  reviewer-spec

bin/              on the Bash tool's PATH, so skills call these by name
  pingu           status | doctor | gate | next-id | new | vault-path
  gh-sync         push | status | pull
  vault-init      scaffolds docs/vault/

scripts/          the implementations behind bin/
  pingu.py        vault state, lane inference, doctor, the gate runner
  gh_sync.py      GitHub Issue mirroring
  vault_init.sh   scaffolds the vault; never overwrites an existing file

hooks/
  hooks.json      SessionStart — puts `pingu status` in front of every session

templates/        Obsidian templates, for writing a note by hand
  brief.md  task.md  adr.md

tests/            pytest; the tooling itself has no third-party dependencies
  test_pingu.py   lanes, phase inference, doctor, vault paths
  test_gates.py   the gate runner: vault, command and manual checks
  test_gh_sync.py frontmatter parsing, the push guard, idempotency
  test_skills.py  docs and code agreeing — lane table vs LANES, gate table vs
                  GATES, frontmatter validity, plugin identity, this diagram

.github/workflows/
  test.yml        pytest on 3.9 and 3.13, shell syntax, claude plugin validate
```

That is what ships. What it *creates* is `docs/vault/` inside your repo — see
the `vault` skill for that tree.

## Design decisions worth knowing

**Phases versus disciplines.** Phases own artifacts and only `start` sequences them; disciplines own techniques and anyone can call them. Orchestrators calling orchestrators nest unpredictably, and a run you can't follow is a run you can't review.

**Only the router claims a raw request.** That invariant lives entirely in the `description` fields, because dispatch is a judgement call and nothing arbitrates it at runtime. So each phase description names the artifact it owns and the precondition it needs, and points anything vaguer at `start`. When `talk` or `plan` wins a request the router should have taken, the run gets no lane, no run log, and — the expensive one — no `SETUP NEEDED` gate. `tests/test_skills.py` guards this; it is the only thing that does.

**Two reviewers, deliberately blind to each other.** A reviewer holding the spec excuses sloppy code because it works; a reviewer holding the standards nitpicks code that solves the wrong problem. Be clear-eyed about how far this goes: `reviewer-standards` is *asked* not to read the brief, and it has `Read`, so the separation is a convention its prompt maintains, not a sandbox. It holds because the agent has no reason to defect, not because it can't.

**One task, one file.** A concurrency decision. Parallel agents touch different files, so git merges cleanly.

**IDs are allocated, not guessed.** Two agents eyeballing "the next number" pick the same one — and so did `pingu next-id`, which read the highest ID and returned max+1. Sixteen concurrent `pingu new task` calls produced duplicates. It now *reserves* the ID it hands out, claiming it with `O_EXCL` so the loser of a race walks forward to the next number. That is a mutex within one working tree, which is the case parallel agents create; two people in separate clones can still collide, and `doctor` reports it.

**Gates are executed, not self-assessed.** The gate table used to be prose asking the model to confirm it had met its own exit condition, which is the one party that cannot be trusted to answer. `pingu gate <phase>` runs the checks. Crucially it has a `manual-review` verdict for the checks no tool can decide — because forcing every gate into something checkable is how a green tick stops meaning anything. `not-declared` exists for the same reason: an undeclared test command is not a passing one.

**Declared commands are lists.** `test_command: ["pytest", "-q"]` in `context.md` goes straight to the process. A string would need a shell to interpret, and the vault is a file the model writes.

**Read-only agents get a `tools:` allowlist; the two open-ended ones don't.** `architect` and the three reviewers deny by default, which is the honest shape for a role whose whole output is a report. `senior-engineer` and `sqa` stay on inheritance on purpose: an allowlist strips every MCP tool as well as built-ins, and those two work in someone else's repo where a project's MCP server may be exactly what they need.

**Phases delegate to agents rather than forking.** A skill can run in its own subagent with `context: fork`, but a fork receives only the SKILL.md text — not the conversation, so not which task, which epic, or which run. Every phase here needs that. The `skills:` field on an agent is the shape that fits: the agent's body is the system prompt and the caller's handoff is the task.

**No `hooks` field in `plugin.json`.** Claude Code auto-loads `hooks/hooks.json`; declaring it causes duplicate-load errors.

**Plugin options are read from the settings file, not substituted.** The two mechanisms that look right both fail silently: `${user_config.KEY}` does not interpolate in a skill body — it reaches the model as that literal string — and `CLAUDE_PLUGIN_OPTION_*` is not exported to the Bash tool. All three options here were no-ops until this was checked against a real session. They now resolve through one function that reads `pluginConfigs` directly, and `pingu status` states the autonomy level every session so it is visible rather than assumed. Put the setting in `<repo>/.claude/settings.json` and commit it if a team should share it.

**Setup is not autonomous.** Reading a repo tells you what the code does, never what the team agreed. Setup drafts the first from evidence, marks it as inferred, and asks about the second.

**Nothing requires anything else.** Every skill works standalone — `/agent-pingu:adr` without a plan, `/agent-pingu:diagnose` without the loop. The loop is a convenience, not a cage. (Plugin skills are namespaced by plugin name; that prefix is not optional.)

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

Add a phase: drop a folder in `skills/`, add it to the lane table in `skills/start/SKILL.md` **and to `LANES` in `scripts/pingu.py`**, add its gate to the gate table **and to `GATES`**, and add its note type to the schema in `skills/vault/SKILL.md`. `tests/test_skills.py` fails if any of those pairs drift apart, which is the point of it.

When you write the gate, reach for a `manual` check rather than approximating one. A gate that pretends to check something it can't is worse than one that says a human has to look.

Write the description to name the artifact it owns and the precondition it needs, then defer anything vaguer to `start`. The instinct is to write it pushy, because a single skill in isolation does tend to under-trigger — but every phase you make pushier competes with the router for the same request, and the router is the one that picks the lane and checks the setup gate. Pushiness belongs in `start` alone.

Keep each `SKILL.md` under ~500 lines and push detail into `references/`, which loads only when needed.
