#!/usr/bin/env bash
# Scaffold the project vault inside this repo.
#
#   ./vault_init.sh              # creates docs/vault/
#   VAULT_DIR=docs/knowledge ./vault_init.sh
#
# Safe to re-run: it never overwrites a file that already exists.

set -euo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
VAULT="$REPO/${VAULT_DIR:-${CLAUDE_PLUGIN_OPTION_VAULT_DIR:-docs/vault}}"
NAME="$(basename "$REPO")"
TODAY="$(date +%F)"

mkdir -p "$VAULT"/{standards,patterns,research,decisions,plan,tasks,runs,retro,review,dashboards}

seed() { [ -f "$1" ] || cat > "$1"; }

seed "$VAULT/context.md" <<CTX
---
type: context
title: $NAME
status: template
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
echo
echo "The seeded notes are still templates. Start Claude Code here and say"
echo "\"set up the vault\" — it will read this repo and draft them for you."
