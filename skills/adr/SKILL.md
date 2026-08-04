---
name: adr
description: Writes, supersedes, and looks up Architecture Decision Records in `decisions/` — the durable record of why the system is shaped the way it is, for choices expensive to reverse — a datastore, a queue, an auth model, an API shape, a dependency that will be hard to remove. Dispatched by the `pingu` router as the decision phase; also use directly when someone asks why we do it this way, when reversing an earlier decision, or when project practice contradicts a written standard. When the decision is part of new work with no brief behind it, `pingu` sequences discovery before design.
---

# ADR

An ADR captures a decision and the situation that forced it. Its readers are future teammates, including future you, who need to know whether the reasoning still holds.

## When a decision needs an ADR

Write one when the choice is expensive to reverse, when a reasonable engineer would have chosen differently, or when someone will otherwise ask "why is this like this" within a year. Library version bumps and formatting choices do not qualify — recording everything makes the record worthless.

## Load first

`standards/*`, `patterns/*`, the glossary, `brief.md`, the research notes, and existing ADRs — **especially ones you might be contradicting**.

Search existing ADRs before writing. Re-deciding something the team already settled, without acknowledging it, is the most common way this record loses trust.

## Getting the design right first

For anything spanning more than one component, introducing a datastore or dependency, or changing a contract between systems, delegate to the `architect` agent before writing. It returns options, a recommendation, and the consequences — the raw material an ADR needs. Writing the ADR yourself from a single option you already had in mind produces a record of a preference, not a decision.

When the decision touches auth, secrets, personal data, payments, or input crossing a trust boundary, get `security-reviewer` on the design too. Security problems are far cheaper to fix in an ADR than in a diff.

## Conflicts with a written standard

An ADR may diverge from a standard, but never quietly. Write the divergence into the ADR with the reason and the scope of the exception, and flag it in the run log. If the exception looks like it should become the rule, say so — that is how a standard gets improved rather than eroded.

## Output

`docs/vault/decisions/ADR-NNNN-<slug>.md`:

```markdown
---
type: adr
id: ADR-0003
project: <slug>
title: Token bucket rate limiting at the edge
status: accepted        # proposed | accepted | superseded
work_type: feature
supersedes: null
superseded_by: null
deciders: ["@alice", "@bob"]
created: <date>
updated: <date>
---

## Context
The forces in play: constraints, requirements, what we learned in research.
Write it so someone who wasn't there understands the pressure.

## Decision
Active voice, one paragraph. "We will ..."

## Alternatives considered
Each with the reason it lost. This section is what makes the ADR trustworthy —
without it, readers assume you only thought of one option.

## Consequences
What becomes easy. What becomes hard. What we now have to live with.
Include the bad ones; an ADR with no downsides is not a decision, it's an advert.

## Revisit when
The condition that would make us reconsider.
```

## Superseding

Never edit a decided ADR to change its decision. Write a new one, set `supersedes`, and set the old one's `status: superseded` and `superseded_by`. The chain of reasoning is the value — a record that gets quietly rewritten is a record nobody can rely on.

## Gate

Every decision that constrains the plan exists as an accepted ADR, and each is linked from the brief. Then move to `plan`.
