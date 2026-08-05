---
name: verify
description: The quality gate before a human sees the work — runs the full suite, reviews the diff against the brief, the plan, the ADRs and the standards using four independent reviewers, and assembles the one-page review packet and the PR. Dispatched by the `start` router as the verification phase; also use directly when someone asks whether specific finished work is ready to ship, or to audit whether what was built matches what was asked for. Needs implemented tasks to verify against.
---

# Verify

You are the last thing between an autonomous run and a human's time. Assume the reviewer will read one page and trust it, and behave accordingly.

## Load first

`brief.md`, the epic, every task in it, accepted ADRs, the run log, and `standards/*`.

## Checks

**Against the brief** — does this deliver the success criteria, and did it stay out of the non-goals? Drift into a non-goal is a finding even when the extra work is good work.

**Against the plan** — every task's acceptance criteria actually met, not approximately met. Check them one by one against the code, not against the task's own status field.

**Against the ADRs** — the implementation follows the decisions. Where it doesn't, either the code is wrong or the ADR is stale; say which.

**Against the standards** — testing bar, error handling, logging, security. Run `reviewer-standards` and `reviewer-spec` in parallel on the diff. They are split on purpose: a reviewer holding the spec in mind starts excusing sloppy code because it works, and a reviewer holding the standards starts nitpicking code that solves the wrong problem. Separating the axes keeps both honest, and neither runs in the context that wrote the code.

**The coverage** — ask `sqa` whether the suite would actually catch a regression in what was built. Percentage is not the question; whether each acceptance criterion has a test that would fail is.

**The security posture** — run `security-reviewer` whenever the change touches auth, secrets, personal data, payments, file or network access, or input crossing a trust boundary. Do this without being asked.

**The suite** — full run, not the fast subset. Record the actual result. If something is flaky, name it rather than re-running until it passes.

## Dispatching them

Send all four in a **single message** so they run in parallel — they are independent and the slowest one sets the wall clock either way. Dispatch by the plugin-qualified name, `agent-pingu:reviewer-standards` and so on; the bare name does not resolve, and agents are only registered in a session started after the plugin was installed. If they are missing, say so and stop rather than reviewing the diff yourself — a self-review is the thing this phase exists to replace.

**Freeze the tree while they read.** Do not commit, edit, or revert anything between dispatching and collecting. Reviewers read the working tree, so a commit landing mid-review makes their findings describe a state that no longer exists — and the honest ones will spend their turns reporting the drift instead of the code. `sqa` is the exception that proves it: it mutates files by design, so it reverts each one and confirms `git status` is clean.

Give each reviewer the vault paths it needs — the brief for `reviewer-spec`, the standards for `reviewer-standards` — and tell `reviewer-standards` explicitly *not* to read the brief. Tell all of them that "no findings" is a useful answer and that inventing problems to look thorough is worse than silence.

Hand them the previous packet's **uncertainty list** if there is one. Reviewers dismiss some with reasons and deepen others, and that is often worth more than what they find unprompted.

## Findings

Write findings as severities: blocking, should-fix, and noted. Be specific about what and where. "Error handling could be better" is not a finding; "the retry in client.py swallows the 429 and logs nothing" is.

Fix blocking findings before finishing. Turn should-fix items into new task notes rather than doing them now — you are past the plan, and unplanned fixes at this stage are how a reviewable run becomes an unreviewable one.

## Output

The review packet at `docs/vault/review/<date>-<slug>.md`, per the format in the `start` skill. Then the PR, with the packet as its body and every task's Issue referenced so they close on merge.

## Honesty

The uncertainty section is the most valuable part of the packet. If you guessed at something, say where. If a test covers the happy path only, say so. A reviewer who finds one concealed weakness stops trusting the other nine sections, and then the loop has cost more than it saved.

## Gate

Suite green, no blocking findings open, packet written, PR opened. Then `retro`.
