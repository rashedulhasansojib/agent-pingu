---
name: execute
description: Implements one already-planned task end to end — reads its task note and linked ADRs, writes tests and code, keeps the vault and GitHub Issue in step, and stops cleanly when blocked. Dispatched by the `loop` router as the execution phase; also use directly when someone names a task by ID ("implement T-0042") or resumes a half-finished one from a previous session. Requires a task note with acceptance criteria — a request to start building with no plan behind it goes to `loop`.
---

# Execute

One task at a time, start to finish, then the next. Resist the urge to fix adjacent things you notice — write them down as new tasks instead. Unplanned work is invisible work, and invisible work is what makes a full-loop run impossible to review.

## Load first

`standards/engineering.md`, `standards/security.md`, relevant `patterns/*`, `glossary.md`, the task note, its epic, every ADR it links, and `context.md`.

Load the task's ADRs specifically. Implementing against a decision you haven't read is how a codebase drifts away from its own architecture record.

## Loop per task

1. Set `status: doing`, assign yourself, sync the Issue.
2. Re-read the acceptance criteria. If any is ambiguous *now* that you're in the code, that ambiguity is a stop condition, not something to interpret.
3. Write the failing test first where the codebase supports it. Tests written after the fact tend to describe what the code does rather than what was asked for.
4. Implement the smallest thing that satisfies the criteria.
5. Run the task's tests, then the fast suite around what you touched.
6. Self-check against the standards you loaded — not a full review, that's `verify`'s job.
7. Commit with the task ID in the message: `T-0042: token bucket middleware`.
8. Append to the run log: what changed, what you learned, anything surprising.
9. Set `status: review`, sync, move on.

## Delegating

For a task with a large or noisy implementation surface, hand it to the `senior-engineer` agent with the task note and its ADRs. Isolating that work keeps the planning context clean, which matters because a long full-loop run degrades mainly through context pollution, not through bad decisions.

## When you get stuck

Three failed attempts on the same problem with no new hypothesis means stop. Set `status: blocked`, write what you tried and what you now believe is wrong, sync the Issue, and continue with an unblocked task if one exists.

A blocked note with a clear hypothesis is a genuinely useful artifact. A task marked done that half works is the most expensive thing this loop can produce.

## Never do quietly

- Widen scope beyond the task's acceptance criteria
- Change a public interface that isn't named in the task
- Delete or rewrite tests to make a suite pass
- Add a dependency that no ADR sanctions
- Touch migrations, credentials, or production data

Each of these is a stop-and-report, even at full autonomy. Especially at full autonomy — nobody is watching the intermediate steps, so the boundary has to hold on its own.

## Gate

Acceptance criteria met, tests pass, run log updated, Issue in step. When every task in the epic reaches `review`, move to `verify`.
