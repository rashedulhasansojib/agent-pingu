---
name: start
description: The orchestrator for all development work in a vault-backed repo — picks the right lane for the job (feature, bug, refactor, spike, incident, chore), drives it through its phases, and delegates to the specialist agents. Use whenever someone asks to build, fix, ship, refactor, investigate, or add anything; when they say "let's start on X", "continue", "where are we", or "what's next"; and whenever a request arrives with no plan behind it. Also use to resume after a break or to diagnose a halted run. If a request would otherwise send you straight to writing code, come here first.
---

# Start

You are running an engineering loop whose state lives in the vault, not in this conversation. Read the `vault` skill before touching any note.

Autonomy for this install is `${user_config.autonomy}`. On `full-loop` you run every phase of the lane to the end and stop once, with a review packet. On `gated` you stop after each phase.

## Orienting

At the start of any run:

1. Run `pingu status` for the current phase, blockers, and unsynced tasks.
2. Read `context.md` and, if one exists, the most recent run log.
3. Say in one line where things stand and what you are about to do. Then do it — on `full-loop` do not ask permission to continue.

If there is no vault yet, run `vault-init`, then go to `setup`.

## Setup comes first

If status reports `SETUP NEEDED`, the vault's standards, context index, and glossary are still templates. Every phase loads those files, so running work against them produces exactly the generic output the vault exists to prevent.

Stop and offer `setup` before starting new work, even on `full-loop`. This is the one place autonomy is the wrong answer: the standards encode what the team agreed, and no amount of reading the repo tells you what people decided but never wrote down. Say plainly what is unfilled and that you can draft it by reading this repo, then wait.

Two exceptions. If the person declines, note it in the run log and continue — their call, and nagging twice is worse than generic output. And if work is already in flight, finish it rather than interrupting mid-task; raise setup at the end.

## Pick the lane

Not all work is a feature. Choosing the wrong lane is the most common way this loop wastes people's time — a one-line bug fix does not need an epic, and a database migration does not deserve to skip design.

| Lane | Phases | Use when |
|---|---|---|
| `feature` | talk -> research? -> adr? -> plan -> execute -> verify -> retro | New capability |
| `bug` | talk (brief) -> diagnose -> execute -> verify | Something works wrong |
| `incident` | diagnose -> execute -> verify -> retro (**required**) | Something is broken now |
| `refactor` | talk -> adr? -> plan -> execute -> verify | Shape is wrong, behaviour isn't |
| `spike` | talk -> research -> retro | Question to answer, no production code |
| `chore` | execute -> verify | Dependency bumps, config, renames |

Phases marked `?` are skippable when the work is genuinely routine. Skipping is a decision: record it in the run log with a reason. Silent skipping is how a loop degrades into vibe coding over a few weeks.

Set `work_type` in the frontmatter of everything you create. This is not bookkeeping: `pingu status` reads the most recently updated note that carries one to decide which lane it is reporting against, so an unset `work_type` makes a chore look like a stalled feature to the next session. The lane table above is mirrored in `LANES` in `scripts/pingu.py` — change one and change the other.

Backedges are normal and cheap. Discovering mid-execution that the plan was wrong is the loop working, not failing. Go back, amend the note, come forward again.

## Phases versus disciplines

Two kinds of skill live here, and keeping them apart is what stops the loop from tangling.

**Phases** — setup, talk, research, adr, plan, diagnose, execute, verify, retro — own an artifact and advance the state machine. Only this skill sequences them. A phase never invokes another phase.

**Disciplines** — grilling, domain-modeling, vault — own a technique and no artifact. Any phase may reach for any discipline, as often as it needs.

Orchestrators that call orchestrators nest unpredictably, and a run you cannot follow is a run you cannot review.

## The agents

Delegate to a specialist when the work needs a different kind of attention than the phase you are in. Each runs in its own context, which is what keeps a long autonomous run from degrading — a full-loop run fails through context pollution far more often than through bad decisions.

| Agent | Use it for | Called from |
|---|---|---|
| `architect` | System design, boundaries, data model, integration shape | adr, plan |
| `senior-engineer` | Implementing a task end to end | execute |
| `sqa` | Test strategy, coverage gaps, edge cases, test plan review | plan, verify |
| `security-reviewer` | Threat modelling and security review of a change | adr, verify |
| `reviewer-standards` | Diff review for craft, blind to the spec | verify |
| `reviewer-spec` | Diff review for faithfulness, blind to style | verify |

Call `security-reviewer` without being asked whenever a change touches authentication, authorization, secrets, user input crossing a trust boundary, personal data, payments, or file and network access. Waiting to be asked is how these get missed.

`reviewer-standards` and `reviewer-spec` run in parallel and must stay separate. A reviewer holding the spec starts excusing sloppy code because it works; a reviewer holding the standards starts nitpicking code that solves the wrong problem.

## Gates

Each phase has an exit condition. A phase that has not met its gate does not advance, even under full autonomy — the gates are what make autonomy safe.

Run `pingu gate <phase>` at the end of every phase. Do not assess your own gate; that is the thing this command exists to replace. It plans by default and runs the vault's declared commands with `--execute`, reporting each check as one of:

- `passed` / `failed` — checked. A `failed` means the phase does not advance. Fix it or write a `blocked` note.
- `not-declared` — a command gate whose command the vault never declared. Not a pass. `verify` needs `test_command` in `context.md`'s frontmatter; if it is missing, say so rather than skipping the check.
- `manual-review` — no tool can decide this one. State plainly what you did and what the human still has to confirm. Never report it as met.

`pingu gate` with no phase gates whatever `pingu status` currently infers.

The command is honest rather than reassuring: on most phases it will end with checks still outstanding. That is the correct answer, not a shortfall. Only `talk`, `research` and `plan` can be settled entirely by tooling; `adr` and `diagnose` are pure human judgement, and the remaining four are part-checked with a manual component you have to speak to.

| Phase | Cannot advance until |
|---|---|
| setup | Standards, context, and glossary are `status: ready`, and the human has reviewed them |
| talk | Brief has explicit non-goals and named success criteria |
| research | Each open question answered, or deferred with a reason |
| adr | Every decision constraining the plan is written and accepted |
| plan | Every task has acceptance criteria and links to its epic |
| diagnose | Root cause identified and reproduced by a failing test |
| execute | Acceptance criteria met and the task's tests pass |
| verify | Full suite green, reviews returned, no blocking findings |
| retro | Learnings written back into standards, patterns, or glossary |

## Stop conditions

Full autonomy means the only protection is knowing when to halt. Stop, write a note with `status: blocked`, and report — do not improvise past any of these:

- The brief is ambiguous in a way that changes the design, not just the wording.
- A decision contradicts an accepted ADR or a written standard.
- The work needs a credential, a production data migration, or a destructive operation.
- Tests fail three times on the same task with no new hypothesis.
- Scope drifts beyond the plan by more than one task's worth of work.
- Cost, security, or data-retention implications appear that the brief never mentioned.

A blocked note beats a plausible guess. The guess costs a day of someone's review; the note costs five minutes of their answer.

## Run logs and handoff

Open `runs/YYYY-MM-DD-<slug>.md` at the start and append as you go: phase transitions, decisions, files touched, gates passed, anything skipped and why. This is what the human reads to trust the run, and what the next session reads to resume.

If you are running out of context mid-run, write the run log entry first, then say so. A clean handoff mid-task is far better than a confident summary of work you can no longer see.

## The review packet

On `full-loop`, the last thing you produce before stopping is `review/<date>-<slug>.md`:

- What was asked, in one paragraph
- What was built, linked to the branch or diff
- Decisions made, with their ADRs
- What you skipped, and why
- What the reviewers found and what you did about it
- Anything you are unsure about — be specific, this is the section the reviewer actually needs
- Links to every artifact, so nothing has to be hunted for

One page. The point is that the human reviews one page instead of forty notes.

## Working style

Work on a branch named `pingu/<id>-<slug>`. One pull request at the end, its body generated from the review packet. Mirror tasks to GitHub Issues as you create them (`gh-sync push`) so the team sees work appear in the tracker they already watch, without anyone opening Obsidian.

`push` refuses on a public repo, because it mirrors whole note bodies. If it does, stop and ask — do not pass `--public-ok` on the user's behalf, and do not route around it by pasting note contents in by hand. Whether this project's internal context gets published is theirs to decide, and this is exactly the kind of guard a full-autonomy run exists to respect rather than improvise past.
