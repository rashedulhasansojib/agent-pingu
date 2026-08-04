---
name: vault
description: The shared spine for the engineering loop — vault layout, frontmatter schema, note naming, ID allocation, wikilinks, and the standards that every phase loads. Read this before writing or reading ANY note in the vault, and whenever you need to know where a brief, decision, epic, task, run log, or retro belongs. Every other loop skill depends on the conventions defined here, so consult it even if the user only mentions "the vault", "our docs", "project context", or "the standards".
---

# Vault

The vault is where the loop keeps its state. Context windows die between sessions; the vault does not. If a fact matters after this session ends, it belongs in a note — not in your reply.

The vault is also the reason a short prompt from a new teammate produces the same quality of work as a long prompt from a senior. They don't have to know the standards, because you load the standards for them. Treat that as the point of the system, not a side effect.

## Layout

The vault lives inside the repo it describes, so documentation travels with the code and gets reviewed in the same pull request that changes it. Docs kept somewhere else rot.

```
docs/vault/
├── context.md                    # INDEX — read this first, always
├── glossary.md                   # the project's shared language
├── standards/
│   ├── engineering.md            # style, testing bar, definition of done
│   └── security.md
├── patterns/                     # solution shapes that have worked here
├── brief.md                      # or briefs/ for long-lived projects
├── research/R-0001-<slug>.md
├── decisions/ADR-0001-<slug>.md
├── plan/EPIC-01-<slug>.md
├── tasks/T-0042-<slug>.md        # one file per task, never a list
├── runs/YYYY-MM-DD-<slug>.md
├── retro/RETRO-0001-<slug>.md
├── review/<date>-<slug>.md
└── dashboards/board.md           # Dataview board over this project
```

Point Obsidian at the repo root, or at `docs/vault` directly. Either works — wikilinks resolve within the vault.

## Context resolution

Every phase loads context in this order, later tiers winning on conflict:

1. **Standards** — `standards/*`, relevant `patterns/*`, `glossary.md`
2. **Project** — `context.md`, `brief.md`, accepted ADRs
3. **Task** — the specific task note and its linked ADRs

Do not read the whole vault. `context.md` is an index with pointers; follow only the pointers the current phase needs, and grep for the rest. A phase that reads forty notes has failed before it started.

When practice contradicts a written standard, that is not a conflict to resolve silently — it is an ADR waiting to be written, or a standard waiting to be corrected. Surface it.

## Frontmatter schema

Every note carries frontmatter. Dataview queries and the tooling both depend on these exact keys, so keep them stable:

```yaml
---
type: task              # brief | research | adr | epic | task | run | retro | review
id: T-0042              # stable, never reused
title: Rate limit the public search endpoint
status: todo            # todo | doing | blocked | review | done
                        # ADRs use: proposed | accepted | superseded
work_type: feature      # feature | bug | refactor | spike | incident | chore
owner: "@alice"
epic: EPIC-01
gh_issue: null          # the Issue number once mirrored; write `null`, never a bare key
adrs: ["[[ADR-0003-token-bucket]]"]
depends_on: []
tags: [api, reliability]
created: 2026-08-03
updated: 2026-08-03
---
```

Run `pingu doctor` after any batch of note writing. It catches duplicate IDs, unknown statuses, broken wikilinks, and tasks orphaned from their epic — the failures that quietly break the board.

## Naming, IDs, and linking

- Allocate IDs with `pingu next-id <type>`. Never guess the next number by eye. Two agents working in parallel will both guess the same one.
- IDs are zero-padded and monotonic per type: `ADR-0007`, `T-0042`, `EPIC-03`.
- Filenames are `<ID>-<kebab-slug>.md`. The ID prefix keeps links stable when titles change.
- Link with wikilinks, always: `[[ADR-0003-token-bucket]]`. Never paste content from another note — link to it. Duplicated context is context that will drift.
- Every task links up to its epic and to any ADR it implements. Every ADR links to the research that informed it. The graph *is* the audit trail.

## One file per unit

One task = one file. One decision = one file. Never a checklist inside a shared note.

This is a concurrency decision, not an aesthetic one. Several developers running agents in parallel will each touch different files, so git merges cleanly. A single `tasks.md` guarantees conflicts every day.

## Writing notes

- Write the note before reporting to the user, so the artifact survives a dead session.
- Update `updated:` on every edit.
- Append to run logs; never rewrite history. Corrections go in a new entry that links back.
- Keep notes short enough that a human will actually read them. A brief running over two screens has failed to decide something.
