# Manual

Brief instructions for daily use. Read once; keep the lane table handy.

---

## 1. Install

```bash
unzip agentic-loop.zip -d ~/.claude/skills/     # personal
# or: unzip into <repo>/.claude/skills/         # shared with the team via git
```

Restart Claude Code. Confirm with `claude plugin list` — you should see `agentic-loop@skills-dir`.

## 2. Set up a repo

From the repo root:

```bash
~/.claude/skills/agentic-loop/scripts/vault_init.sh
```

This creates `docs/vault/` and never overwrites anything that already exists, so it's safe to re-run.

The seeded notes start as templates. **Start Claude Code in the repo and say "set up the vault"** — or just start any work, and the loop will stop and offer it, because session start reports:

```
[loop] phase: setup   (vault seeded but not filled in)
[loop] SETUP NEEDED — still templates: context.md, engineering.md, glossary.md, security.md
```

Setup reads your repo — package manifest, test config, linter and CI rules, directory layout, commit history — drafts the standards, context index, and glossary from what the code actually does, then asks you about the parts it cannot infer: your definition of done, your testing bar, what counts as sensitive data here, and which existing patterns you would rather people stopped copying.

It marks inferred lines as inferred and agreed lines as agreed, so you can tell evidence from assumption when you review it. It takes a few minutes and it is the difference between the loop producing your team's work and producing generic work.

You can decline. The loop notes it and carries on, and won't nag twice.

Requirements: Python 3, git, and an authenticated `gh` CLI if you want Issue mirroring. Obsidian needs the Dataview plugin for the board.

## 3. Daily use

Just describe the work. The loop picks the lane.

| You say | What happens |
|---|---|
| "set up the vault" | reads the repo, drafts standards, context, and glossary |
| "we need rate limiting on search" | feature lane: brief → decisions → tasks → build → review |
| "search returns duplicates for tenant B" | bug lane: reproduce → root cause → failing test → fix |
| "the API is down" | incident lane, with a mandatory retro |
| "this module is a mess" | refactor lane |
| "can we even do X?" | spike lane: research note, no production code |
| "bump the deps" | chore lane: straight to execute |
| "continue" / "where are we?" | resumes from vault state |
| "implement T-0042" | runs one task |
| "is this ready?" | verification and the review packet |

You can also call any piece directly — `/agentic-loop:adr`, `/agentic-loop:diagnose`, `/agentic-loop:grilling`, `/agentic-loop:domain-modeling` — without running the whole loop. Plugin skills are namespaced by plugin name, so the prefix is required; type `/agentic-loop:` and the picker will list them. Nothing here requires anything else.

## 4. What a full run does

On `full-loop` autonomy it works from your request to a pull request and stops **once**, handing back a one-page review packet in `docs/vault/review/`. Read that, not the forty notes behind it.

It halts early and writes a `blocked` note if: the request is ambiguous in a way that changes the design, a decision contradicts an accepted ADR or a standard, it needs a credential or a production migration, tests fail three times with no new hypothesis, or scope drifts past the plan.

Switch to stopping at every phase by setting `autonomy` to `gated` in the
`/plugin` interface, under this plugin's configuration.

There is no CLI equivalent. `--config` is a flag on `claude plugin install`, and
a plugin discovered under a skills directory is never installed — it is loaded in
place, so there is nothing for `install` to act on. If you would rather edit the
file, the value lives in `~/.claude/settings.json`:

```json
{ "pluginConfigs": { "agentic-loop@skills-dir": { "options": { "autonomy": "gated" } } } }
```

## 5. The agents

Delegated automatically; you can also ask for one by name.

| Agent | Does |
|---|---|
| `architect` | System design, boundaries, data model, integration shape |
| `senior-engineer` | Implements one task end to end |
| `sqa` | Test strategy, coverage gaps, edge cases |
| `security-reviewer` | Threat model and security review |
| `reviewer-standards` | Diff review for craft, blind to the spec |
| `reviewer-spec` | Diff review for faithfulness, blind to style |

`security-reviewer` runs unprompted on anything touching auth, secrets, personal data, payments, or file and network access.

## 6. Tooling

```bash
loop status              # lane, phase, blockers, unsynced tasks
loop doctor              # validate the vault before a PR
loop next-id task        # allocate an ID safely
loop new adr "Title"     # scaffold a note, print its path

gh-sync push             # create Issues for new tasks
gh-sync status           # push status changes, close on done
gh-sync pull             # bring Issue comments back into notes
```

These are on the PATH while the plugin is enabled. The implementations live in `scripts/` if you need to call them from outside Claude Code.

`doctor` catches duplicate IDs, unknown statuses, broken wikilinks, and tasks pointing at epics that don't exist. Run it before opening a PR; these are the failures that silently break the board.

`status` reads the `work_type` on the most recently updated note to decide which lane it is reporting against, so a chore stays a chore across sessions instead of looking like a stalled feature.

### Pushing to a public repo

`push` mirrors each task's **full note body** to its Issue. Setup deliberately fills the vault with trust boundaries, retention rules, and landmines, so on a public repo that is publication. It therefore refuses by default, and also refuses when it cannot establish the repo's visibility — guessing wrong is not undoable:

```bash
gh-sync push                # refuses on a public repo, and on an unknown one
gh-sync push --public-ok    # yes, this repo is meant to be public
```

`push` also looks for an Issue already titled with the task's ID before creating one, and adopts it. That covers the window where a previous run created the Issue but died before writing `gh_issue` back into the note.

## 7. Working as a team

The vault is committed with the code, so documentation is reviewed in the same PR that changes the behaviour it describes.

One task is one file — deliberately. Several people running agents in parallel each touch different files, so git merges cleanly. Never collapse tasks into a shared checklist.

Tasks mirror to GitHub Issues, so teammates who never open Obsidian still see work appear where they already look. The vault note stays the source of truth for content; `gh-sync pull` brings Issue discussion back.

## 8. Keeping it useful

The retro phase writes learnings back into `standards/`, `patterns/`, and `glossary.md`. That is the step where the loop compounds — skip it and the next person pays the same tuition.

If output quality drifts, the cause is almost always a thin standards file or a stale `context.md`, not the skills. Fix the vault first.

## 9. Troubleshooting

| Symptom | Cause |
|---|---|
| Skills don't appear | `skills/` must be at the plugin root, not inside `.claude-plugin/`. Run `claude --debug`. |
| "Duplicate hooks file detected" | Something added a `hooks` field back to `plugin.json`. Claude Code auto-loads `hooks/hooks.json`; declaring it is the bug. |
| Session start says "no vault" | Run `vault-init` from the repo root. |
| `gh-sync` fails | `gh auth status`, and set `gh_repo` if the git remote is ambiguous. |
| `loop: command not found` | `bin/` only joins the PATH while the plugin is enabled. Check `claude plugin list`, or call `scripts/loop.py` directly. |
| Loop feels heavyweight | It picked the wrong lane. Say "this is a chore" or "this is a bug" and it will shorten. |
| Generic-sounding output | Setup was skipped. Run `loop status`; if it says SETUP NEEDED, say "set up the vault". |
| Setup keeps prompting | A file still has `status: template` in its frontmatter. Setup flips these to `ready` as it fills each one. |
