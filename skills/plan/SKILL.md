---
name: plan
description: Decomposes an existing brief and its accepted ADRs into epics and individually executable task notes with acceptance criteria, then mirrors them to GitHub Issues. Dispatched by the `run` router as the planning phase; also use directly to re-cut a plan when execution proved the tasks were wrong, or when someone points at a written brief and asks for it to be sliced. Requires that brief — an undifferentiated request with nothing decided yet goes to `run`, which runs discovery first.
---

# Plan

You are producing tasks that an agent or a human can pick up cold and finish without asking a question. That standard — *finishable without a follow-up question* — is the only real test of a task note.

## Load first

`standards/engineering.md` (testing bar, definition of done), `patterns/*`, `glossary.md`, `brief.md`, accepted ADRs, research notes, and existing tasks.

## Slicing

Cut vertically. A task should move the product, not a layer: "search endpoint returns paginated results" beats "add repository method". Horizontal slices produce a pile of work that demos nothing until the last one lands, which is exactly when problems surface.

Size each task so it fits in one focused session. If you can't state its acceptance criteria in three bullets, it's two tasks.

Order by dependency and by risk. Pull the risky and uncertain work early — a plan that saves the hard part for last is a plan that discovers its own failure at the deadline.

State the dependencies explicitly. Anything not blocked is fair game to run in parallel, and with one file per task, parallel agents won't collide.

## Get the test strategy in early

Before finalising acceptance criteria, hand the draft plan to the `sqa` agent. It decides what each criterion needs in order to be provable and at which level. Acceptance criteria written without that input tend to be untestable in ways nobody notices until verification, which is the most expensive moment to find out.

If the slicing depends on a system boundary you are unsure about, ask `architect` before cutting tasks along it.

## Output

An epic per coherent chunk of the brief:

```markdown
---
type: epic
id: EPIC-01
title: Public search rate limiting
status: todo
work_type: feature
adrs: ["[[ADR-0003-token-bucket]]"]
created: <date>
updated: <date>
---

## Goal
The slice of the brief this delivers.

## Tasks
- [[T-0042-token-bucket-middleware]]
- [[T-0043-limit-headers]]

## Done when
Observable condition for the whole epic.
```

Then a file per task, with IDs allocated by `pingu next-id task` rather than guessed:

```markdown
---
type: task
id: T-0042
title: Token bucket middleware on /search
status: todo
work_type: feature
owner: unassigned
epic: EPIC-01
gh_issue: null
adrs: ["[[ADR-0003-token-bucket]]"]
depends_on: []
created: <date>
updated: <date>
---

## Context
Two sentences. Why this exists, linked to the epic.

## Acceptance criteria
- [ ] Checkable, observable statements
- [ ] Each one either passes or fails, no judgement call

## Approach
The intended shape, and the files likely touched. A hint, not a script —
whoever executes may find a better route and should be free to take it.

## Out of scope
What a reasonable person might add here, and shouldn't.

## Test notes
What proves it works, including the failure cases worth covering.
```

## Mirror to GitHub

Once tasks are written, run `gh-sync push`. It opens an Issue per task, writes the number back into `gh_issue`, and labels by epic. The vault note stays the source of truth for content; the Issue is the surface the rest of the team already watches. Never let the two diverge silently — if someone edits the Issue body, `gh-sync pull` brings the discussion back into the note as a thread.

It mirrors the whole note body, so it refuses on a public repo. If it does, stop and ask — do not reach for `--public-ok` on the user's behalf. Whether this project's internal context can be published is their call, not a blocker to route around.

## Gate

Every task has acceptance criteria, links to its epic, and an Issue number. Then move to `execute`.

## Re-planning

When execution proves the plan wrong, come back and change it rather than improvising inside a task. Amend the task, note the change in the run log, and continue. A plan that quietly stops matching the work is worse than no plan, because people still trust it.
