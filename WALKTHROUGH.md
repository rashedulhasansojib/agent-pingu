# Walkthrough — installing Agent Pingu and running it on a new project

Every command and every output below is real, taken from building
`test-agent-pingu` (a small todo CLI) with this plugin. Where something went
wrong, it is left in — that is the part worth reading.

- [1. Install, once per machine](#1-install-once-per-machine)
- [2. Check it works](#2-check-it-works)
- [3. Starting a new project](#3-starting-a-new-project)
- [4. The full flow, phase by phase](#4-the-full-flow-phase-by-phase)
- [5. When something goes wrong mid-run](#5-when-something-goes-wrong-mid-run)
- [6. Command reference](#6-command-reference)
- [7. Gotchas worth knowing before you hit them](#7-gotchas-worth-knowing-before-you-hit-them)

---

## 1. Install, once per machine

```
/plugin marketplace add rashedulhasansojib/agent-pingu
/plugin install agent-pingu@agent-pingu
```

A folder under a skills directory containing `.claude-plugin/plugin.json` is also
discovered in place, which is the route to take if you mean to edit the plugin:

```bash
git clone https://github.com/rashedulhasansojib/agent-pingu.git ~/.claude/skills/agent-pingu
```

Pick one — an installed copy shadows a cloned one of the same name.

Developing the plugin itself? Symlink instead, so your edits apply live:

```bash
ln -s /path/to/agent-pingu ~/.claude/skills/agent-pingu
```

**Restart Claude Code**, then confirm:

```bash
claude plugin list
```

```
❯ agent-pingu@skills-dir
  Version: 0.5.0
  Scope: user
  Path: ~/.claude/skills/agent-pingu
  Status: ✔ loaded
```

`Scope: user` means it loads in **every** project. That is usually what you
want; a project-scope copy under `<repo>/.claude/skills/` is the alternative,
and it only loads when Claude Code starts from that directory.

### What "loaded" gets you

| | |
|---|---|
| Skills | `/agent-pingu:start`, `:talk`, `:plan`, … — the prefix is required |
| Agents | `architect`, `senior-engineer`, `sqa`, `security-reviewer`, two reviewers |
| Commands | `pingu`, `gh-sync`, `vault-init` on the Bash tool's PATH |
| Hook | SessionStart prints `pingu status` — silent in repos with no vault |

**The commands only appear in sessions started *after* the plugin loaded.** If
`pingu: command not found`, that is why. Restart, or call
`~/.claude/skills/agent-pingu/scripts/pingu.py` directly.

The same applies to the agents, and they are namespaced: the dispatch name is
`agent-pingu:reviewer-standards`, not `reviewer-standards`. A session that was
already running when you installed the plugin will not see them at all, which
makes the whole `verify` phase quietly do nothing.

---

## 2. Check it works

Paste this into **bash or zsh** — it runs identically in both. Every command it
runs is read-only; none of them touch your vault.

```bash
check() {
  out=$("$@" 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then
    printf '  ok         %s\n' "$*"
  else
    [ "$rc" -eq 127 ] && rc="not found"
    printf '  %-10s %s\n' "$rc" "$*"
    printf '%s\n' "$out" | sed 's/^/             /'
  fi
}

check pingu status
check pingu doctor
check pingu gate plan
check pingu gate verify
```

In a repo with a filled-in vault you should see:

```
  ok         pingu status
  ok         pingu doctor
  ok         pingu gate plan
  ok         pingu gate verify
```

Anything else prints the reason underneath it, which is the point:

```
  not found  pingu status
             zsh: command not found: pingu
```

### Why the helper is shaped like that

Two mistakes are easy here, and both were made while writing this document.

**Pass the arguments, never a command string.** The obvious version is a loop
over strings:

```bash
for c in "gate plan" "next-id task"; do pingu $c; done   # broken in zsh
```

bash splits `$c` into two words. **zsh does not** — `pingu` receives the single
argument `gate plan` and exits 127, which looks exactly like the tool being
missing. `${=c}` splits in zsh but then mangles quoted arguments, turning
`new task "buy milk"` into four. Forwarding real arguments with `"$@"` is
correct in both shells and needs no `eval`.

**Never discard stderr.** `cmd >/dev/null 2>&1 && echo ok || echo "rc=$?"`
throws away *why* it failed, so `127` (not installed) and `1` (a gate that
legitimately did not pass) look identical. The helper above prints the captured
output on failure, which is what turns a mystery into a one-line diagnosis.

### If a check fails

| Output | Means |
|---|---|
| `not found` | The plugin loaded after this shell started. Restart Claude Code. |
| `rc=1` on `doctor` | Either there is no vault in this repo — run `vault-init` — or the vault has a real problem. The output says which. |
| `rc=1` on `gate …` | The gate genuinely is not met. That is the gate working, not a fault. |
| `ok` on `status`, but it prints `no vault` | Expected. `status` exits 0 even with no vault, because it runs on every session start and a missing vault is not an error. |

---

## 3. Starting a new project

```bash
mkdir my-project && cd my-project && git init
# ... your skeleton: manifest, a source dir, a tests dir ...
git add -A && git commit -m "Skeleton"

vault-init
```

```
vault ready at /path/to/my-project/docs/vault

The seeded notes are still templates. Start Claude Code here and say
"set up the vault" — it will read this repo and draft them for you.
```

Scaffold **after** you have a skeleton, not before. Setup reads your manifest,
test config and CI to draft the standards; pointed at an empty directory it has
nothing to work from.

Now start Claude Code in that directory. The hook reports:

```
[pingu] vault: vault   lane: feature   phase: setup   (vault seeded but not filled in)
[pingu] autonomy: full-loop — runs the whole lane, then stops once for review
[pingu] SETUP NEEDED — still templates: context.md, engineering.md, glossary.md, security.md
[pingu] every phase loads these; run the setup skill to draft them from this repo
```

Say **"set up the vault"** and answer its questions.

### Do not skip setup

Those four files are loaded by every later phase. Left as templates, the loop
falls back to generic defaults and produces generic work — which is the exact
failure the vault exists to prevent. Setup takes a few minutes once per repo.

Two things it cannot read and will ask you:

- **Your definition of done.** The single most load-bearing line in the standards.
- **What the code does that you wish it didn't.** Without this it will faithfully
  encode your regrets as standards.

It marks each line *(inferred)* or *(agreed)*, so you can tell evidence from
assumption when you review it. Read the standards file before you accept it —
getting one rule wrong there propagates into everything afterwards.

### Declare your test command

Setup writes this into `context.md`'s frontmatter:

```yaml
test_command: [".venv/bin/python", "-m", "pytest", "-q"]
lint_command: []
```

This is what `pingu gate verify --execute` runs. **A list, not a string** — a
list goes straight to the process and never touches a shell. Leave it empty and
the gate reports `not-declared`, which is not a pass.

---

## 4. The full flow, phase by phase

Describe the work in plain language. The router picks a lane; you do not name it.

| Lane | Phases |
|---|---|
| feature | talk → research? → adr? → plan → execute → verify → retro |
| bug | talk → diagnose → execute → verify |
| incident | diagnose → execute → verify → retro (**required**) |
| refactor | talk → adr? → plan → execute → verify |
| spike | talk → research → retro |
| chore | execute → verify |

Below is the feature lane as it actually ran.

### talk → `brief.md`

You say *"I want a todo list I can drive from one terminal."* It interviews you
and writes the brief. The gate will not let it leave `draft` without non-goals
and success criteria.

```
$ pingu gate talk
[gate] talk   (planned)
  passed         brief states success criteria and non-goals
[gate] all checks passed
```

**Push hard on non-goals.** In this run they were the highest-value thing
written: "no due dates, no tags, no editing" is what kept the plan at three
tasks instead of eight. The value of a non-goal is invisible — it is the work
that never got proposed.

### adr → `decisions/ADR-0001-….md`

Only for choices that are expensive to reverse. Here: how items are stored.

```
$ pingu gate adr
  manual-review  every decision constraining the plan is accepted
                 Which decisions constrain the plan cannot be read off disk.
```

`manual-review` is the honest answer — no tool can know which decisions
constrain your plan. The gate says so instead of pretending.

The *Alternatives considered* section is what makes an ADR trustworthy. Without
it a reader assumes you only thought of one option.

### plan → `plan/EPIC-NN`, `tasks/T-NNNN`

```bash
pingu next-id task      # T-0004 — allocated, never guessed
```

Never eyeball the next number. Two agents working in parallel both guess the
same one.

The test of a task note is: **could someone finish this cold, without asking a
question?** If you cannot state its acceptance criteria in three bullets, it is
two tasks.

```
$ pingu gate plan
  passed         every task has acceptance criteria and an epic
                 all 3 task(s) have criteria and an epic
```

### execute → code

One task at a time, failing test first. Commit with the task ID:

```bash
git commit -m "T-0001: store read and write, path resolved at call time"
```

Then `status: review` on the note and move on. Resist fixing adjacent things —
write them down as new tasks. Unplanned work is invisible work.

### verify → `review/<date>-<slug>.md`

```
$ pingu gate verify --execute
[gate] verify   (executed)
  passed         test suite passes
                 exit code 0
  manual-review  reviews returned with no blocking findings
[gate] 1 check(s) still outstanding — the gate is not met yet
```

`--execute` is required because running your suite is a side effect. Without it
the gate plans and shows you what it *would* run.

That `manual-review` line never turns green on its own. It means four reviewers
have to run and a human has to read them — so run them, in one message so they
go in parallel, and freeze the tree while they read:

```
agent-pingu:reviewer-standards   craft, blind to the brief
agent-pingu:reviewer-spec        faithfulness, ignoring style
agent-pingu:sqa                  would the suite catch a regression
agent-pingu:security-reviewer    threat model
```

**What that found here is the reason the phase exists.** The todo CLI was
written test-first, passed 18 tests, and had a packet listing four things its
author was unsure about. The reviewers returned two blocking defects:

- A store that is valid JSON of the **wrong shape** raised a traceback, breaking
  a success criterion stated in the brief. `[]` was this project's own store
  format before T-0001 was reopened — an upgrade path, not a hypothetical.
- The suite could not tell whether `done` and `rm` act on the **named** item.
  Every test used a single-item store, so `items[0]` was indistinguishable from
  looking the id up. `sqa` mutated both to ignore the id and all 18 passed.

Neither is exotic, and writing the tests first prevented neither: test-first
guarantees a test fails before the code exists, not that it tests the right
shape of input. What caught them was a reader who had not written the code.

The review packet is one page. Its most valuable section is **what you are
unsure about** — a reviewer who finds one concealed weakness stops trusting the
other nine sections. Hand that list to the reviewers too: here they dismissed two
items with reasons and deepened another from "would hand out a duplicate id" into
"silently deletes the item you were not looking at".

### retro → learnings written back

The step where the loop compounds. A retro that only describes what happened
changes nothing; one that amends a standard changes every future run.

In this run the retro amended the definition of done, after a task got committed
while a test was red:

> Run `pingu gate <phase>` and read what it says — do not assert the suite
> passed, check it. Never chain a commit after a test command; gate the commit
> on the exit code.

### Closed

```
$ pingu status
[pingu] vault: vault   lane: feature   phase: done   (loop closed)
[pingu] autonomy: full-loop — runs the whole lane, then stops once for review
$ pingu doctor
vault ok — 14 notes, no problems found
```

---

## 5. When something goes wrong mid-run

Both of these happened while building the example. Neither is a malfunction —
the first is the loop working, the second is the reason its standards exist.

### The plan turns out to be wrong

T-0002's criterion was *"ids never repeat, including after a removal"*. The
implementation used `max(ids) + 1`, which looks equivalent and is not: remove
the highest item and the next add reuses its id — an id the user may still have
on screen.

A flat list cannot remember its own high-water mark. The **store shape** had to
change, which was T-0001's contract, not T-0002's.

The right move is a backedge: **stop, go back, amend the earlier task, come
forward.** Not improvising inside the current one.

```
- **execute T-0002** — backedge. Reopening T-0001 to change the store shape
  rather than improvising inside T-0002. ADR-0001 is unaffected — it says one
  JSON file, not what shape the JSON is.
```

Record it in the run log. Backedges are normal and cheap; a plan that quietly
stops matching the work is worse than no plan, because people still trust it.

### Something gets committed on red

```bash
pytest -q ; git commit -m "..."     # commits regardless
if pytest -q; then git commit -m "..."; fi   # gates on the result
```

The first form ran here and committed a task with a failing test. Nothing caught
it but reading the output. The fix went into the standards so the next run
inherits it — that is the whole point of retro.

---

## 6. Command reference

```bash
pingu status              # lane, phase, blockers, unsynced tasks
pingu doctor              # validate the vault before a PR
pingu gate [phase]        # evaluate a phase's exit condition
pingu gate verify --execute
pingu next-id task        # allocate an ID safely
pingu new adr "Title"     # scaffold a note, print its path

gh-sync push              # create Issues for new tasks
gh-sync status            # push status changes, close on done
gh-sync pull              # bring Issue comments back into notes

vault-init                # scaffold docs/vault/ (safe to re-run)
```

### Gate verdicts

| | |
|---|---|
| `passed` / `failed` | Actually checked. A `failed` stops the phase. |
| `planned` | A command gate, not run. Add `--execute`. |
| `not-declared` | No command declared. **Not a pass.** |
| `manual-review` | No tool can decide this. **Never auto-passes.** |

Only `talk`, `research` and `plan` can be settled by tooling alone. `adr` and
`diagnose` are entirely human judgement; the other four are part-checked. So
most phases end with checks outstanding — that is the intended answer, not a
shortfall.

---

## 7. Gotchas worth knowing before you hit them

**`pingu: command not found`** — `bin/` joins the PATH only for sessions started
after the plugin loaded. Restart Claude Code.

**Skills need the prefix.** `/agent-pingu:adr`, not `/adr`. Type
`/agent-pingu:` and the picker lists them.

**`doctor` will flag a link before its target exists.** Writing `context.md`
first and the ADR second produces `broken link [[ADR-0001-…]]`. That is correct —
write the target, or drop the link.

**Set `work_type` on everything.** `pingu status` reads it from the most
recently updated note to decide which lane it is reporting. Unset, a chore looks
like a stalled feature to the next session.

**`gh-sync push` refuses on a public repo.** It mirrors whole note bodies. Pass
`--public-ok` only if publishing your internal context is genuinely intended.

**`test_command` must be a list.** `"pytest -q"` is rejected; `["pytest", "-q"]`
works. A string would need a shell, and `context.md` is a file the model writes.

**Setup is not autonomous, deliberately.** Reading a repo tells you what the code
does, never what the team agreed. It drafts the first and asks about the second.

---

## The worked example

`test-agent-pingu` alongside this repo is the output of the run above: a todo
CLI in ~140 lines with 18 tests, and the complete vault behind it — brief, ADR,
epic, three tasks, run log, review packet, retro, and one pattern. It is worth
reading `docs/vault/runs/` and `docs/vault/review/` together: the run log is
what happened, the packet is what someone else needs to know.
