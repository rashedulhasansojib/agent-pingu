---
name: domain-modeling
description: Builds and sharpens the project's shared language so that everyone — people and agents — names the same thing the same way. Reached for whenever a new term appears in discussion, when a name feels vague or overloaded, when two people use different words for one concept, or when code naming has drifted from how the team actually talks. Keeps the glossary and context index current, and feeds naming decisions into ADRs.
---

# Domain modeling

A project without a shared language forces everyone to describe concepts from scratch, every time. "There is a problem when a lesson inside a section of a course is given a spot in the file system" is the same sentence as "there is a problem with the materialization cascade" — but one of them costs twenty words and the other costs two.

The savings compound. Consistent names mean variables, functions, and files line up with how people talk, which makes the codebase navigable, which means less searching to find the right file. For an agent working from a short prompt, that shared vocabulary is often the difference between finding the right code and guessing.

## Working the model

**Challenge new terms.** When a word appears that isn't in the glossary, stop and pin it down. Is it genuinely new, or a synonym for something already named? Synonyms are the main way a domain model rots — two names for one concept, and every reader has to hold both.

**Stress-test with edge cases.** Take the definition and push a hard scenario through it. If the definition needs an exception to survive, either the definition is wrong or you have found a second concept that needs its own name.

**Prefer the domain's word.** Use what the people who own the problem actually say. Inventing a cleaner term than the one the business uses guarantees permanent translation overhead.

**Name the thing, not the mechanism.** "MaterializationCascade" outlives an implementation; "PostgresLessonSyncJob" doesn't.

## Where it lands

Update `glossary.md` for terms, and `context.md` when the language change affects how someone navigates the project. Keep one definition per term — a glossary with two entries for the same word is worse than none.

When a naming choice is contested or expensive to reverse, it is a decision: write it into an ADR with the alternatives you rejected. Naming arguments recur endlessly unless the reasoning is written down once.

Then use the words. A glossary nobody applies in code review and commit messages is documentation theatre.
