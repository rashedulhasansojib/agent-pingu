---
name: talk
description: Writes `docs/vault/brief.md` — problem, named users, success criteria, non-goals, constraints — through structured discovery. Dispatched by the `loop` router as the discovery phase of the feature, refactor, bug and spike lanes; also use directly when someone asks for a brief by name, or when an existing brief needs revisiting because the goal moved. A loose request with nothing agreed yet belongs to `loop` first — it picks the lane, and a chore or an incident should never reach this phase at all.
---

# Talk

Your job is to ask the questions the requester didn't know to ask, and to end with a brief that someone else could build from.

This phase carries most of the loop's value. The person prompting may be new, may be non-technical, may be a strong engineer in a hurry. None of them should have to already know what a good brief contains — that knowledge lives here, not in their prompt.

## Load first

`glossary.md` (use their words, not synonyms) and relevant `standards/*`. If the project already exists: `context.md`, prior briefs, accepted ADRs.

Arriving with context is what makes discovery feel like a conversation with a colleague rather than a form. If a term in the request is already in the glossary, use its definition rather than asking what it means.

## Interview

Use the `grilling` discipline for the interview itself. Work through:

**Who and why** — Which users, doing what today, and what does it cost them? A request with no named user is a preference, and preferences change under pressure.

**The observable change** — When this ships, what is measurably different? "Search is better" is not an answer; "p95 search latency under 400ms" is.

**Non-goals** — What are we explicitly *not* doing? Push here even when it feels pedantic. Unstated non-goals are where scope creep enters, and by the time it enters, it looks like a reasonable request.

**Constraints** — Deadline, budget, compliance, existing systems that must keep working, data that cannot move.

**Prior art** — Has this been tried? Is there an ADR, a dead branch, a retro? Someone has usually already thought about this.

**Failure** — What happens when it breaks, and who notices first? Answers here tend to expose requirements nobody thought to state.

Stop asking when new answers stop changing the shape of the work.

## Push back

If the request describes a solution rather than a problem ("add a Redis cache"), find the problem underneath before writing it down. Record the stated solution as a candidate, not as the goal. Solutions written into briefs become requirements nobody can question later.

If two answers conflict, say so plainly and resolve it now. A brief that contains a contradiction produces a plan that contains two plans.

## Output

Set the lane before writing anything — a bug or a chore does not need this full treatment. For anything with a `feature`, `refactor`, or `spike` lane, write `docs/vault/brief.md` (new projects also get `context.md`; see the `vault` skill):

```markdown
---
type: brief
id: BRIEF-001
project: <slug>
title: <one line>
status: draft
work_type: feature
owner: "@<who asked>"
created: <date>
updated: <date>
---

# <Title>

## Problem
Who hurts, how, and what it costs. Two paragraphs at most.

## Users
Named roles, with the job each is trying to finish.

## Success criteria
Observable and checkable. Each one either happens or doesn't.

## Non-goals
Explicit. This section earns its keep every time.

## Constraints
Technical, legal, temporal, budgetary.

## Open questions
Anything unresolved, each tagged for `research` or for a human to answer.

## Prior art
Wikilinks to ADRs, retros, previous attempts.
```

## Gate

The brief cannot leave `draft` until non-goals and success criteria are both populated with real content. If the requester won't answer, write the open question down and mark the brief `blocked` rather than inventing an answer — a plausible invention here propagates through every later phase.

Next: `research` if open questions remain, otherwise `adr`.
