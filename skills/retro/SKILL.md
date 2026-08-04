---
name: retro
description: Closes a run by capturing what was learned and writing the durable parts back into `standards/`, `patterns/`, and `glossary.md` so the next run starts smarter. Dispatched by the `run` router as the closing phase, and required rather than optional on the incident lane; also use directly after a painful debugging session, or when a solution shape has now worked three times and deserves writing down.
---

# Retro

The loop only compounds if learning changes what future runs load. A retro nobody acts on is a diary entry; one that amends a standard changes how every later phase behaves.

## Load first

Run logs, the review packet, blocked notes, the brief as originally written, and the existing `standards/*` and `patterns/*`.

## Look at

**Where estimates broke** — which tasks took far longer than their shape suggested, and what the plan failed to see.

**Where the loop stalled** — blocked notes, backedges, phases redone. Each one is a question the earlier phase should have asked.

**Where the vault failed** — missing standard, stale ADR, a `context.md` that didn't point at the thing that mattered. This is the highest-value category, because it's the one you can directly fix.

**Where a short prompt still produced good work** — worth noticing. That's the equalizer functioning, and knowing which context made it work tells you what to write more of.

## Promote

A retro that only describes what happened changes nothing. Every learning worth keeping lands in one of three places:

- **The retro note** — narrative and one-offs.
- **`patterns/<slug>.md`** — a solution shape that has now worked three times, written with a real example from this repo.
- **`standards/*` or `glossary.md`** — when it should constrain future work. Do this sparingly, and only when you can name the specific pain that justifies the constraint. A standards file that grows every sprint stops being read.

The standards files are what every future phase loads, so this step is where the loop actually compounds. Skipping it means the next person pays the same tuition.

## Output

```markdown
---
type: retro
id: RETRO-0002
project: <slug>
title: <epic or period>
status: done
created: <date>
updated: <date>
---

## What shipped
## What went well
Specific, not morale-boosting. "The ADR on token buckets meant execution never
had to relitigate the design" is useful; "good collaboration" is not.
## What cost us time
## Vault gaps found
## Written back
Links to the standards, patterns, or glossary entries this changed.
## Still open
```

## Gate

Learnings written back into standards, patterns, or the glossary; vault gaps either fixed or filed as tasks. The loop is closed.
