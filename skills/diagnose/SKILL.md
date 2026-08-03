---
name: diagnose
description: Takes a symptom to a proven root cause — reproduce, minimise, hypothesise, instrument, then capture it as a failing test — and records the findings in the task note or `research/R-NNNN`. Dispatched by the `loop` router as the diagnosis phase of the bug and incident lanes; also use directly for a named failing test, a flaky test, a performance regression, or a fix that was attempted and did not hold. A fresh report that something is broken goes to `loop`, which decides between the bug and incident lanes and starts a run log.
---

# Diagnose

The failure mode here is guessing. A plausible-looking fix applied to an unproven cause makes the symptom disappear, gets shipped, and comes back next month wearing a different hat. Every step below exists to stop that.

## Load first

`context.md`, `standards/engineering.md`, the glossary, and any prior notes about this area — including old retros and incident notes. Bugs recur in the same places, and someone has often already paid to learn why.

## The loop

**Reproduce.** Get a reliable, repeatable trigger before changing anything. If you cannot reproduce it, that is the whole task for now — say so rather than fixing something adjacent and hoping. Note the exact conditions: environment, data, timing, sequence.

**Minimise.** Strip the reproduction down until nothing can be removed without the bug disappearing. What remains points at the cause far more precisely than the original report did.

**Hypothesise.** State what you believe is happening, specifically enough to be wrong. "Something with the cache" is not a hypothesis; "the cache key omits the tenant ID, so tenant B reads tenant A's row" is.

**Instrument.** Prove or kill the hypothesis with evidence — a log, a breakpoint, a test, a query. Do not skip to the fix because the hypothesis feels obviously right. Feeling right is exactly the state in which people ship the wrong fix.

**Write the failing test.** Before fixing, capture the bug as a test that fails for the right reason. This is the gate: no root cause is confirmed until a test reproduces it.

**Fix the cause, not the symptom.** If the fix is a guard clause around a value that should never have been in that state, you have found the symptom, not the cause. Keep going, or write down explicitly that you are shipping a mitigation and why.

**Check for siblings.** The same mistake usually appears more than once. Grep for the pattern before closing.

## When it resists

Three failed hypotheses with no new evidence means stop and write up what you have ruled out. Ruling things out is real progress and saves the next person the same hours. A `blocked` note listing five dead hypotheses is worth more than a sixth guess.

## Output

For a tracked bug, write findings into the task note. For anything larger, or any incident, write `research/R-NNNN-<slug>.md` with `work_type: bug` or `incident`:

```markdown
## Symptom
What was observed, by whom, under what conditions.
## Reproduction
The minimal trigger.
## Ruled out
Hypotheses killed, and the evidence that killed them. Do not omit this —
it is the most reusable part of the note.
## Root cause
## Fix
Including whether it addresses the cause or only mitigates.
## Siblings checked
Where else this pattern appears, and what you found.
```

## Gate

Root cause identified and reproduced by a failing test. Then move to `execute`. For an `incident` lane, the retro is not optional.
