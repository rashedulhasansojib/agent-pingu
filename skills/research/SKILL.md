---
name: research
description: Answers open questions an existing brief, plan, or task already raised — spikes, prior-art digs, library and vendor comparisons, feasibility checks, reading the codebase — and writes `research/R-NNNN`. Dispatched by the `start` router as the research phase of the feature and spike lanes; also use directly when a specific question must be settled before an ADR can be written, or when a task turns out to rest on an assumption nobody verified. Needs a question already written down; an unexplored request goes to `start`.
---

# Research

You are buying down uncertainty, not building. The output is a note that lets someone else make a decision quickly.

## Load first

`standards/*`, relevant `patterns/*`, the brief's open questions, and accepted ADRs.

## Method

Take one question at a time. For each:

1. State the question as a decision someone has to make.
2. Gather evidence — the codebase first, then docs, then the web. What the repo already does outweighs what a blog post recommends.
3. Lay out the real options, including "do nothing" and "the boring one we already run in production".
4. For each option: what it costs, what it locks in, how it fails.
5. Answer, or defer with an explicit reason and a trigger for revisiting.

Spike code is allowed and expected. It goes on a throwaway branch and is never merged. Say so in the note, or someone will find it in six months and assume it was a decision.

## Honesty

Report what you actually found. An inconclusive spike is a real result and saves the next person the same three hours. Padding a note to look productive costs the team far more than admitting the question is still open.

Separate what you verified from what you inferred. If you didn't run it, say you didn't run it.

## Output

`docs/vault/research/R-NNNN-<slug>.md`:

```markdown
---
type: research
id: R-0001
project: <slug>
title: <question as a phrase>
status: done          # or: deferred
created: <date>
updated: <date>
---

## Question
## Options
Per option: cost, lock-in, failure mode.
## Evidence
What was run, read, or measured. Links.
## Answer
Or: deferred, because <reason>, revisit when <trigger>.
## Consequences for the design
The part the ADR will actually use.
```

## Gate

Every open question in the brief is either answered or deferred with a stated reason. Then update the brief's open-questions section to point at the research notes, and move to `adr`.
