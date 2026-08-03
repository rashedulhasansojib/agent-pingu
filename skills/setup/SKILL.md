---
name: setup
description: Fills in a newly seeded vault by reading the repository and drafting its context index, glossary, and engineering and security standards from what the code actually does. Use whenever the vault's notes are still templates, when session start reports SETUP NEEDED, when someone says "set up the vault", "onboard this repo", or "get the loop working here", and before the first real run in any repo. Also use to refresh standards that have drifted from current practice.
---

# Setup

Every phase of the loop loads `standards/engineering.md`, `context.md`, and `glossary.md`. While those are still templates, the loop falls back to generic defaults and produces generic work — which is precisely the failure the vault exists to prevent. This phase is what turns the vault from scaffolding into the thing that makes a two-word prompt produce work matching the team's bar.

Do not start feature work in a repo whose vault is unfilled. Offer this first.

## The core distinction

You are documenting two different things, and conflating them is the main way this phase produces a file nobody trusts:

- **Observed** — what the code demonstrably does today. You can read this.
- **Agreed** — what the team has decided should happen. You cannot read this, and must not invent it.

Draft the observed parts from evidence, mark them as inferred, and ask about the agreed parts. A standards file full of confident rules nobody agreed to is worse than an empty one, because people follow it for a week and then stop trusting the whole vault.

## Read the repo first

Arrive with a draft, not a questionnaire. Gather in roughly this order, stopping when the picture is clear:

**What it is** — README, `package.json` / `pyproject.toml` / `go.mod` / `Cargo.toml` / `pom.xml`, the entry point, the deploy config. Language, framework, runtime, where it ships.

**How it is tested** — test runner and config, where tests live, their naming convention, roughly how many there are and at which levels. Whether coverage is measured or enforced.

**What is already enforced** — linter and formatter config, type checker strictness, pre-commit hooks, CI workflows. These are the strongest signal available: a rule in CI is a rule the team already agreed to, so promote it to the standards file with confidence.

**How the code is organised** — top-level directories, module boundaries, where the seams are. This becomes the "how it is built" section of `context.md`.

**How people work** — `git log --oneline -50` for commit conventions, PR template, CONTRIBUTING.md, branch names. Existing docs, ADRs, or design notes anywhere in the repo.

**The language people use** — recurring domain nouns in module names, table names, and type names. These are glossary candidates, and the ones that appear in both code and commit messages are the real ones.

## Then interview

Use the `grilling` discipline for the gaps. Keep it short — a handful of questions, informed by what you already found. Ask about:

- **Definition of done.** What must be true before a task is done? This is the single most load-bearing line in the standards file.
- **The testing bar.** What must have a test, and at what level? If CI already enforces something, confirm rather than ask.
- **Anything the code does that the team dislikes.** Patterns that exist but shouldn't be copied. Without this, you will faithfully encode the team's regrets as standards.
- **Trust boundaries and sensitive data.** What counts as personal data here, where untrusted input enters, what must never be logged.
- **Landmines.** What surprises newcomers. Ask directly — this section pays for itself faster than any other.

When someone doesn't know, write the open question into the file rather than filling the gap. An honest gap invites someone to close it; an invented rule does not.

## Write

Fill in the seeded files in place, keeping their headings so the structure stays predictable. Change `status: template` to `status: ready` on each one as you complete it — that flag is what stops the loop nagging about setup, and what `loop status` reads.

Mark inferred items so a reader can tell evidence from agreement:

```markdown
## Testing
- Tests live in `tests/`, run with `pytest`. *(inferred from CI)*
- Every bug fix ships with a regression test. *(agreed)*
- Coverage is measured but not gated. *(inferred — should it be gated?)*
```

Write only what you have grounds for. A short standards file that is entirely true beats a comprehensive one that is half guessed. The file will grow through retros, which is the right way for it to grow.

Keep `context.md` to pointers and orientation, not prose. Its job is to let a phase find the three notes it needs, and to tell an agent how to run the tests.

## Finish

Run `loop doctor`, then show the person what you wrote — the standards file especially, since it will shape every future run. Ask them to correct anything you inferred wrongly. Getting one rule wrong here propagates into everything the loop produces afterwards, so this review is worth the interruption.

Then say what the loop is now ready to do, and let them start the real work.
