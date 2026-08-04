# Manual

Brief instructions for daily use. Read once; keep the lane table handy.

---

## 1. Install

A folder under a skills directory containing `.claude-plugin/plugin.json` is
discovered in place — there is nothing to install:

```bash
git clone <this repo> ~/.claude/skills/agent-pingu          # personal
git clone <this repo> <repo>/.claude/skills/agent-pingu     # shared via git
```

Restart Claude Code. Confirm with `claude plugin list` — you should see `agent-pingu@skills-dir`.

Developing the plugin itself? Symlink instead — discovery follows the link, and edits then apply in place:

```bash
ln -s /path/to/agent-pingu ~/.claude/skills/agent-pingu
```

A project-scope copy under `<repo>/.claude/skills/` loads only when Claude Code starts from that directory — it does not walk up to the repo root the way plain skills do. Start from the repo root, or run `/reload-plugins` after changing directories.

## 2. Set up a repo

From the repo root:

```bash
~/.claude/skills/agent-pingu/scripts/vault_init.sh
```

This creates `docs/vault/` and never overwrites anything that already exists, so it's safe to re-run.

The seeded notes start as templates. **Start Claude Code in the repo and say "set up the vault"** — or just start any work, and the loop will stop and offer it, because session start reports:

```
[pingu] phase: setup   (vault seeded but not filled in)
[pingu] SETUP NEEDED — still templates: context.md, engineering.md, glossary.md, security.md
```

Setup reads your repo — package manifest, test config, linter and CI rules, directory layout, commit history — drafts the standards, context index, and glossary from what the code actually does, then asks you about the parts it cannot infer: your definition of done, your testing bar, what counts as sensitive data here, and which existing patterns you would rather people stopped copying.

It marks inferred lines as inferred and agreed lines as agreed, so you can tell evidence from assumption when you review it. It takes a few minutes and it is the difference between the loop producing your team's work and producing generic work.

You can decline. The loop notes it and carries on, and won't nag twice.

Requirements: Python 3, git, and an authenticated `gh` CLI if you want Issue mirroring. Obsidian needs the Dataview plugin for the board.

## 3. Vault layout

`vault-init` creates this inside your repo, and commits with it — so the notes
are reviewed in the same PR as the behaviour they describe:

```
docs/vault/
  context.md          INDEX — read first. Also declares test_command for the gates
  glossary.md         the project's shared language, one definition per term
  brief.md            written by talk; absent until then
  standards/
    engineering.md    style, testing bar, definition of done
    security.md       trust boundaries, secrets, data handling
  patterns/           solution shapes that have worked here, added by retro
  research/           R-0001-<slug>.md      spikes and option analysis
  decisions/          ADR-0001-<slug>.md    why the system is shaped this way
  plan/               EPIC-01-<slug>.md
  tasks/              T-0001-<slug>.md      one file per task, never a list
  runs/               YYYY-MM-DD-<slug>.md  append-only log of what happened
  retro/              RETRO-0001-<slug>.md
  review/             <date>-<slug>.md      the one page you actually read
  dashboards/
    board.md          Dataview board over this project
```

Everything but `context.md`, `glossary.md`, `board.md` and the two standards
starts empty — the phases fill them as work moves. Point Obsidian at the repo
root or at `docs/vault` directly; wikilinks resolve either way.

Set `vault_dir` in the plugin's configuration to put it somewhere other than
`docs/vault`.

## 4. Daily use

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

You can also call any piece directly — `/agent-pingu:adr`, `/agent-pingu:diagnose`, `/agent-pingu:grilling`, `/agent-pingu:domain-modeling` — without running the whole loop. Plugin skills are namespaced by plugin name, so the prefix is required; type `/agent-pingu:` and the picker will list them. Nothing here requires anything else.

## 5. What a full run does

On `full-loop` autonomy it works from your request to a pull request and stops **once**, handing back a one-page review packet in `docs/vault/review/`. Read that, not the forty notes behind it.

It halts early and writes a `blocked` note if: the request is ambiguous in a way that changes the design, a decision contradicts an accepted ADR or a standard, it needs a credential or a production migration, tests fail three times with no new hypothesis, or scope drifts past the plan.

Switch to stopping at every phase by setting `autonomy` to `gated` in the
`/plugin` interface, under this plugin's configuration.

There is no CLI equivalent. `--config` is a flag on `claude plugin install`, and
a plugin discovered under a skills directory is never installed — it is loaded in
place, so there is nothing for `install` to act on. If you would rather edit the
file, the value lives in `~/.claude/settings.json`:

```json
{ "pluginConfigs": { "agent-pingu@skills-dir": { "options": { "autonomy": "gated" } } } }
```

## 6. The agents

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

`architect` and the three reviewers are restricted to `Read, Grep, Glob, Bash` (plus web access for the first two) — they cannot write files at all. That also means they see no MCP tools, since an allowlist strips those too. `senior-engineer` and `sqa` keep the full inherited pool for exactly that reason.

`architect` and `senior-engineer` start with the `vault` skill already in context, so they know the note schema and ID rules without going to look; `architect` also gets `domain-modeling`, because naming boundaries is most of what it does.

## 7. Tooling

```bash
pingu status              # lane, phase, blockers, unsynced tasks
pingu doctor              # validate the vault before a PR
pingu gate [phase]        # evaluate a phase's exit condition
pingu next-id task        # allocate an ID safely
pingu new adr "Title"     # scaffold a note, print its path

gh-sync push             # create Issues for new tasks
gh-sync status           # push status changes, close on done
gh-sync pull             # bring Issue comments back into notes
```

These are on the PATH while the plugin is enabled. The implementations live in `scripts/` if you need to call them from outside Claude Code.

`doctor` catches duplicate IDs, unknown statuses, broken wikilinks, and tasks pointing at epics that don't exist. Run it before opening a PR; these are the failures that silently break the board.

`status` reads the `work_type` on the most recently updated note to decide which lane it is reporting against, so a chore stays a chore across sessions instead of looking like a stalled feature.

### Gates

`pingu gate <phase>` evaluates a phase's exit condition instead of asking the model whether it met its own. Every check comes back as one of:

| | |
|---|---|
| `passed` / `failed` | Actually checked. A `failed` stops the phase. |
| `planned` | A command gate, not run. This is the default — running your test suite is a side effect, so you ask for it with `--execute`. |
| `not-declared` | A command gate whose command the vault never declared. **Not a pass.** |
| `manual-review` | No tool can decide this. Never auto-passes. |

```bash
pingu gate                # gate whatever phase status infers
pingu gate verify         # show what would run
pingu gate verify --execute
```

Only three of the nine gates — `talk`, `research`, `plan` — can be settled by tooling alone. `adr` and `diagnose` are entirely human judgement; the other four are part-checked and part-manual. So most phases end with checks still outstanding, and that is the intended answer — a green tick that meant "the model said so" is what this replaces.

For the command gates, declare the commands in `context.md`'s frontmatter:

```yaml
test_command: ["pytest", "-q"]
lint_command: ["ruff", "check", "."]
```

Setup fills these in from your test config and CI. **JSON lists, not strings** — a list is passed straight to the process and never reaches a shell, so nothing in your vault can turn into `&& rm -rf`. A string is rejected with a message telling you to use a list.

### Pushing to a public repo

`push` mirrors each task's **full note body** to its Issue, so it refuses on a public repo by default — and also when it cannot establish the repo's visibility, since guessing wrong is not undoable.

Worth knowing what that actually protects, because the obvious version of the argument is weaker than it sounds. The vault lives inside the repo, so on a public repo those notes are public once committed and the Issue exposes nothing new. What the guard catches is the two cases where it isn't already true: `gh_repo` pointing at a repo other than the one holding the vault, and notes that push publishes before anyone has committed or reviewed them. `INTERNAL` repos are allowed through, on the grounds that everyone the Issue reaches can already read the vault in the repo.

```bash
gh-sync push                # refuses on a public repo, and on an unknown one
gh-sync push --public-ok    # yes, this repo is meant to be public
```

`push` also looks for an Issue already titled with the task's ID before creating one, and adopts it. That covers the window where a previous run created the Issue but died before writing `gh_issue` back into the note.

## 8. Working as a team

The vault is committed with the code, so documentation is reviewed in the same PR that changes the behaviour it describes.

One task is one file — deliberately. Several people running agents in parallel each touch different files, so git merges cleanly. Never collapse tasks into a shared checklist.

Tasks mirror to GitHub Issues, so teammates who never open Obsidian still see work appear where they already look. The vault note stays the source of truth for content; `gh-sync pull` brings Issue discussion back.

## 9. Keeping it useful

The retro phase writes learnings back into `standards/`, `patterns/`, and `glossary.md`. That is the step where the loop compounds — skip it and the next person pays the same tuition.

If output quality drifts, the cause is almost always a thin standards file or a stale `context.md`, not the skills. Fix the vault first.

## 10. Troubleshooting

| Symptom | Cause |
|---|---|
| Skills don't appear | `skills/` must be at the plugin root, not inside `.claude-plugin/`. Run `claude --debug`. |
| "Duplicate hooks file detected" | Something added a `hooks` field back to `plugin.json`. Claude Code auto-loads `hooks/hooks.json`; declaring it is the bug. |
| Session start says "no vault" | Run `vault-init` from the repo root. |
| `gh-sync` fails | `gh auth status`, and set `gh_repo` if the git remote is ambiguous. |
| `pingu: command not found` | `bin/` only joins the PATH while the plugin is enabled. Check `claude plugin list`, or call `scripts/pingu.py` directly. |
| The loop feels heavyweight | It picked the wrong lane. Say "this is a chore" or "this is a bug" and it will shorten. |
| Generic-sounding output | Setup was skipped. Run `pingu status`; if it says SETUP NEEDED, say "set up the vault". |
| Setup keeps prompting | A file still has `status: template` in its frontmatter. Setup flips these to `ready` as it fills each one. |
