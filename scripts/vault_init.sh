#!/usr/bin/env bash
# Scaffold the project vault inside this repo.
#
#   ./vault_init.sh              # creates docs/vault/
#   VAULT_DIR=docs/knowledge ./vault_init.sh
#
# VAULT_DIR only tells *this run* where to scaffold. It is a shell variable, so
# nothing remembers it: `pingu` reads `vault_dir` from the settings files, and
# without a matching entry there it will keep looking in docs/vault. This script
# says so rather than leaving you to find out.
#
# Safe to re-run: it never overwrites a file that already exists.

set -euo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PINGU="$(dirname "$0")/pingu.py"

# Always ask pingu, which is the one place that knows how a plugin option is
# actually resolved. An explicit VAULT_DIR is *handed to* it rather than expanded
# here — the previous `VAULT="$REPO/$VAULT_DIR"` branch was a second resolver in
# the very file whose comment forbids one, and it showed: `pingu.py` never read
# `VAULT_DIR`, so the documented usage on line 5 scaffolded a vault the tooling
# then could not find. That failure presents as an empty vault, not an error.
#
# Routing it through `vault_path()` also picks up the containment check, so
# `VAULT_DIR=../../etc` is now refused instead of scaffolding outside the repo.
#
# The `|| true` this used to carry collapsed two different outcomes into one
# empty string: "pingu answered, and there is no configured vault_dir" and
# "pingu never ran". The second is the one that matters — a configured
# `vault_dir` then goes unread and the vault is scaffolded at the default, which
# is a directory the tooling will not look in. Silent, and it presents as an
# empty vault rather than as an error. Keep the fallback, lose the silence.
PROBE_FAILED=""
CONFIGURED="$(python3 "$PINGU" vault-path 2>/dev/null)" || PROBE_FAILED=1
if [ -n "${VAULT_DIR:-}" ]; then
  # stderr deliberately *not* swallowed here, unlike the `CONFIGURED` probe
  # above. That is where `vault_path()` says it is ignoring a `vault_dir` that
  # resolves outside the repo — and refusing an explicit request while printing
  # nothing is the same silent degradation this change exists to remove.
  VAULT="$(CLAUDE_PLUGIN_OPTION_VAULT_DIR="$VAULT_DIR" python3 "$PINGU" vault-path || true)"
  # Asymmetric with the branch below, on purpose. With no VAULT_DIR the default
  # is documented and almost certainly right, so degrading to it is fine. Here
  # the caller asked for somewhere specific, and scaffolding somewhere else
  # silently is the failure this whole change is about.
  if [ -z "$VAULT" ]; then
    echo "cannot resolve VAULT_DIR=$VAULT_DIR: could not run $PINGU" >&2
    echo "(needs python3 on PATH; refusing to guess where the vault goes)" >&2
    exit 1
  fi
else
  VAULT="$CONFIGURED"
  if [ -z "$VAULT" ]; then
    # Defaulting is right when pingu ran and said there is nothing configured.
    # It is a guess when pingu never ran, so say which one this is.
    if [ -n "$PROBE_FAILED" ]; then
      echo "warning: could not run $PINGU (needs python3 on PATH)" >&2
      echo "warning: any configured vault_dir has NOT been read; scaffolding at" >&2
      echo "warning: the default docs/vault, which may not be where pingu looks" >&2
    fi
    VAULT="$REPO/docs/vault"
  fi
fi
NAME="$(basename "$REPO")"
TODAY="$(date +%F)"

mkdir -p "$VAULT"/{standards,patterns,research,decisions,plan,tasks,runs,retro,review,dashboards}

seed() { [ -f "$1" ] || cat > "$1"; }

seed "$VAULT/context.md" <<CTX
---
type: context
title: $NAME
status: template
test_command: []
lint_command: []
updated: $TODAY
---

# $NAME — context index

Every phase of the loop reads this first. Keep it as pointers, not prose: a
phase that has to read forty notes has failed before it started.

## What this system is
One paragraph. What it does, for whom.

## How it is built
Stack, runtime, where it deploys. Two or three lines.

## Where things are
- Brief: \`brief.md\`
- Language: \`glossary.md\`
- Standards: \`standards/\`
- Decisions: \`decisions/\`
- Plan and tasks: \`plan/\`, \`tasks/\`

## How to run it
The commands to install, test, and start locally. Agents will use these.

Put the test and lint commands in this note's frontmatter as well, as JSON
lists: \`test_command: ["pytest", "-q"]\`. That is what \`pingu gate verify\`
runs. A list, not a string — it never goes near a shell.

## Landmines
What surprises newcomers. This section pays for itself.
CTX

seed "$VAULT/glossary.md" <<GLO
---
type: glossary
title: Glossary
status: template
updated: $TODAY
---

# Glossary

One definition per term, in the words the people who own the problem use.
The loop uses these instead of inventing synonyms, which is what keeps naming
consistent across code, commits, and conversation.

| Term | Means |
|---|---|
|  |  |
GLO

seed "$VAULT/standards/engineering.md" <<ENG
---
type: standard
title: Engineering standards
status: template
updated: $TODAY
---

# Engineering standards

Every phase loads this, which is what lets a short prompt from anyone produce
work that matches the team's bar. Fill it in with what you actually enforce,
not what you aspire to — a standard nobody applies teaches agents to ignore
the file.

## Language and style
Formatter, linter, and the conventions those tools do not catch.

## Testing
What must have a test, at which level, and what "done" means for coverage.

## Error handling
How failures surface, what gets retried, what fails closed.

## Logging and observability
What gets logged, at what level, and what must never appear in a log.

## Git and review
Branch naming, commit format, what a PR needs before review.

## Definition of done
The checklist a task must satisfy before its status becomes done.
ENG

seed "$VAULT/standards/security.md" <<SEC
---
type: standard
title: Security standards
status: template
updated: $TODAY
---

# Security standards

## Trust boundaries
Where untrusted input enters the system.

## Authentication and authorization
How identity is established, and where access checks must live.

## Secrets
Where they live, how they are injected, what must never be committed.

## Data handling
What counts as personal data here, retention, and what may leave the system.

## Dependencies
Policy on adding one, and how versions are pinned.
SEC

seed "$VAULT/dashboards/board.md" <<BRD
# Board

## Blocked

\`\`\`dataview
TABLE title, owner, gh_issue
WHERE type = "task" AND status = "blocked"
\`\`\`

## In flight

\`\`\`dataview
TABLE status, title, work_type, owner, gh_issue
WHERE type = "task" AND status != "done" AND status != "blocked"
SORT status ASC, updated DESC
\`\`\`

## Decisions

\`\`\`dataview
TABLE status, title, updated
WHERE type = "adr"
SORT updated DESC
\`\`\`
BRD

echo "vault ready at $VAULT"

# The scaffolder and the tooling now resolve through one function, but VAULT_DIR
# is still a shell variable that dies with this process — so they can agree today
# and disagree in the next session. Same trade as the warnings `pingu status`
# already prints: degrade, but say so.
if [ -n "$CONFIGURED" ] && [ "$VAULT" != "$CONFIGURED" ]; then
  echo
  echo "NOTE: pingu resolves the vault to $CONFIGURED, not the directory just"
  echo "scaffolded. VAULT_DIR applies to this run only. To make it stick, set"
  # `:-` because `set -u` is on and this block must not be the thing that
  # crashes the scaffolder if a later edit lets it reach here unset.
  echo "  pluginConfigs.agent-pingu.options.vault_dir = \"${VAULT_DIR:-}\""
  echo "in .claude/settings.json — otherwise the loop will not find these notes."
fi

echo
echo "The seeded notes are still templates. Start Claude Code here and say"
echo "\"set up the vault\" — it will read this repo and draft them for you."
