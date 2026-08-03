---
name: grilling
description: The reusable interview loop that closes the gap between what someone asked for and what they meant — relentless questioning until every branch of the decision is resolved. Reached for automatically whenever a request is underspecified, whenever a plan has an unexamined assumption, or before any expensive or hard-to-reverse piece of work. The talk and plan phases both run on this; it also works standalone on any decision, technical or not.
---

# Grilling

Misalignment is the most common failure in software, and it survives contact with agents. Someone describes what they want, you build something fluent and confident, and only then does everyone discover you understood a different problem. Grilling front-loads that discovery, when it is still cheap.

This is a discipline, not a phase. Any skill may reach for it.

## The loop

Ask two or three questions. Listen. Let the answers generate the next questions. Repeat until answers stop changing the shape of the work.

Do not present a numbered questionnaire — it invites shallow answers to all of it. A real interview follows the thread that is producing surprise.

## Where to push

**The unexamined noun.** Any term doing heavy lifting in the request. "Users", "sync", "reporting", "real time" — each hides a decision. Ask what it means here, then check it against the project's glossary.

**The implied solution.** When the request names a mechanism ("add a cache"), find the problem underneath before writing anything down. Solutions written into requirements become constraints nobody can question later.

**The boundary.** What is explicitly not being built? Push here even when it feels pedantic. Unstated non-goals are where scope creep gets in, and it always arrives looking reasonable.

**The failure case.** What happens when this breaks, who notices, and what do they do? Answers here routinely surface requirements nobody thought to state.

**The contradiction.** When two answers conflict, say so immediately and resolve it. A brief containing a contradiction produces a plan containing two plans.

## Tone

Be direct and keep moving. This should feel like a sharp colleague who has seen this go wrong before, not an intake form. When the person says "I don't know", that is a finding — write it down as an open question rather than filling the gap yourself.

Know when to stop. Grilling past the point of diminishing returns wastes goodwill and trains people to avoid the loop entirely.

## Output

Grilling doesn't own an artifact. It feeds one — a brief, an ADR, a task, a spec. The calling skill writes the note. What grilling guarantees is that the note has no invented answers in it.
