# Working on agent-pingu

Instructions for changing **this plugin**. Not for repos that use it — those get
their standards from their own `docs/vault/`.

## What this is

A Claude Code plugin discovered under a skills directory. Nothing installs it;
`.claude-plugin/plugin.json` makes the folder load in place. So there is no build
step, and a broken file is live the moment it is saved.

```bash
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/python -m pytest tests/ -q
claude plugin validate ./.claude-plugin/plugin.json
claude plugin validate ./.claude-plugin/marketplace.json --strict
```

All must pass before a commit. CI runs pytest on 3.9 and 3.13, `bash -n` over
`bin/` and `vault_init.sh`, and both validates.

**Name the manifest you mean.** `claude plugin validate .` used to validate the
plugin; since `marketplace.json` exists it validates *only the marketplace* and
silently stops checking the plugin. Adding the marketplace therefore retired
CI's real check without failing anything — found by running it, which is the only
way it could have been found.

`validate` warns that this file "is not loaded as project context." That warning
is about shipping context to repos that *install* the plugin, which is not what
this file is for — it is read when you open Claude Code here, in the plugin's own
repo, and it does load. Exit code is 0, so CI stays green (hence `--strict` on
the marketplace only). Don't delete it to silence the warning.

## Docs and code are coupled, and tests enforce it

Seven pairs must move together. `tests/test_skills.py` fails if any of the first
five drifts; the sixth is pinned in `tests/test_setup_guard.py`, next to the
guard it protects, and the seventh in `tests/test_marketplace.py`, next to the
manifest it protects:

| Change this | Also change this |
|---|---|
| `LANES` / `OPTIONAL` in `scripts/pingu.py` | the lane table in `skills/start/SKILL.md` |
| `GATES` in `scripts/pingu.py` | the gate table in `skills/start/SKILL.md` |
| a directory that ships | the layout block in `README.md` |
| a `mkdir` in `scripts/vault_init.sh` | the vault tree in `MANUAL.md` |
| the CI matrix in `.github/workflows/test.yml` | the `**Platforms.**` paragraph in `README.md` |
| `EDITING_TOOLS` in `scripts/pingu.py` | the `PreToolUse` matcher in `hooks/hooks.json` |
| `.claude-plugin/marketplace.json` | the `## Install` section in `README.md` |

This is the project's main quality mechanism. When you add a guard like these,
**mutation-test it** — break the thing it watches and confirm it goes red. Two
guards here were vacuous when first written: one whose `-k` filter matched an
assertion message instead of a test name and so ran zero tests, and one whose
regex matched a heading elsewhere in the file and asserted against an unrelated
block. A guard you did not watch fail is not a guard.

The platform pair was mutation-tested three ways before it was trusted: dropping
the Windows cell, dropping the 3.9 cell, and weakening the README sentence each
turn it red.

The matcher pair is the newest, and is the third guard here to have been vacuous
when written. The assertion it replaces was `"Write" in m and "Edit" in m`, which
looks like it checks the list and does not — `"Edit" in "MultiEdit"` is true, so
a matcher naming only `MultiEdit` passed and neither `MultiEdit` nor
`NotebookEdit` was ever checked. Set equality, and mutation-tested three ways:
dropping `NotebookEdit` from the matcher, adding a tool to `EDITING_TOOLS` alone,
and the exact matcher the old assertion waved through.

## The hooks must fail closed, and only exit 2 does that

Claude Code treats **only exit 2** as blocking. Exit 1 — the conventional Unix
failure — is a *non-blocking* error, and the tool call proceeds. So any way
`pingu guard` can fail without exiting 2 is a silent permission grant on the
machines the gate exists to protect. Measured: with no Python on PATH the old
`python3 …` command exited 127 and a real `claude -p` session let the Write
through, with an exit-2 hook as the control proving the probe could see a block.

Hence the resolver in `hooks/hooks.json`: it picks an interpreter *before*
invoking anything and exits 2 when it cannot. Two rules follow.

- **Never chain `||` onto the guard invocation.** `guard` returns 2 to mean
  *blocked*, so a retry-on-failure turns every block into an allow while the
  happy path stays green. The `||` belongs inside the `$( )` that chooses the
  interpreter, and nowhere else.
- **Keep both hooks' resolvers byte-identical.** SessionStart is visible and
  PreToolUse is silent when it allows, so a present `[pingu]` line is the only
  signal that the guard is running. That inference holds only while they match.

This is why the hooks stay in shell form against the docs' own preference: exec
form cannot fail closed, because a failure to spawn is not exit 2.

## Frontmatter is fragile in a way nothing warns you about

An unquoted `key: value` inside a YAML string silently breaks the block, and
Claude Code then drops the **entire** frontmatter — the skill loads nameless and
never triggers at runtime. No error appears. Use em dashes in descriptions, or
quote the string. `test_frontmatter_has_no_unquoted_colon_space` and
`claude plugin validate` are what catch this.

## The lenient frontmatter reader hides its own bugs

`parse_frontmatter` partitions on the first colon and never raises, which is
right for a SessionStart hook — but it also read back notes that no real YAML
parser accepts, so nothing noticed that `pingu new task "Fix: login bug"`
produced a note Obsidian drops from the board, or that `#caching` in a title was
silently truncated away. PyYAML is a test dependency for exactly this: anything
that writes frontmatter needs a test that parses it strictly. Free-text values
are always quoted on write, never conditionally.

## Verify against the real CLI, not just the suite

Green tests have missed three real bugs here: the `ready` semantics on gates,
a `gh issue list --search` rate-limit trap, and install instructions that
referenced a zip nothing built. After the suite passes, run the actual commands.

Two habits that follow from that:

- **Never chain `git commit` after `pytest`.** Gate on the exit code, or you
  will commit on red — this happened.
- **Never build a shell command as a string.** zsh does not word-split unquoted
  `$var`, so `for c in "gate talk"; do pingu $c; done` passes one argument and
  reports 127. Pass real arguments to a helper and forward with `"$@"`. Capture
  stderr rather than discarding it, so 127 and 1 stay distinguishable.

## Only the router claims a raw request

`start` picks the lane and checks the setup gate. If `talk` or `plan` wins a
request the router should have taken, the run gets no lane, no run log, and no
`SETUP NEEDED` check. The invariant lives entirely in the `description` fields —
nothing arbitrates dispatch at runtime — so a phase description names the
artifact it owns and the precondition it needs, then defers anything vaguer to
`start`. Write phase descriptions modest and `start`'s pushy.

## Adding a phase

Folder in `skills/`, entry in the lane table **and** `LANES`, gate in the gate
table **and** `GATES`, note type in `skills/vault/SKILL.md`. Reach for a
`manual` check rather than approximating one — a gate that pretends to check
something it cannot is worse than one that says a human has to look.

Keep each `SKILL.md` under ~500 lines; push detail into `references/`, which
loads only when needed.

## Plugin options do not resolve themselves

Two mechanisms that look like they work, and do not — both verified against a
real session, not assumed:

- `${user_config.KEY}` does **not** interpolate in a SKILL.md or agent body. It
  arrives at the model as that literal string.
- `CLAUDE_PLUGIN_OPTION_KEY` is **not** exported to the Bash tool.

All three of this plugin's `userConfig` options were no-ops for that reason.
They are now resolved by `plugin_option()` in `scripts/pingu.py`, which reads
`pluginConfigs` out of the settings files directly, and surfaced to the model
through `pingu status` — whose SessionStart output does reach context (also
verified). `test_no_skill_relies_on_user_config_interpolation` stops the
placeholder coming back.

Anything that resolves an option must go through `plugin_option`. `gh_sync.py`
imports it and `vault_init.sh` shells out to `pingu vault-path` for exactly that
reason: a second resolver is how an option ends up half-implemented.
