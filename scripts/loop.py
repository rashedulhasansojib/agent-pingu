#!/usr/bin/env python3
"""Vault tooling for the agentic engineering loop.

Invoked as `loop <command>` — bin/loop puts this on the Bash tool's PATH.

  loop status              current lane and phase, blockers, unsynced tasks
  loop next-id <type>      allocate the next free ID (task|adr|epic|research|retro)
  loop new <type> <title>  scaffold a note with correct frontmatter, print its path
  loop doctor              validate the vault: duplicate IDs, bad status,
                           broken wikilinks, orphaned tasks

Config, read from the environment:
  CLAUDE_PROJECT_DIR              repo root. Exported to hook processes only, so
                                  this falls back to `git rev-parse --show-toplevel`
  CLAUDE_PLUGIN_OPTION_VAULT_DIR  vault path relative to the repo, defaults to docs/vault
  LOOP_STATE_MAX_BLOCKED          cap on blocked lines printed by status (default 5)

No third-party dependencies, so it runs wherever Python 3 does. The tests need
pytest; the tooling itself does not.
"""

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

SCALAR_KEYS = (
    "type", "id", "status", "title", "epic", "gh_issue",
    "owner", "updated", "created", "work_type",
)

TASKISH = {"todo", "doing", "blocked", "review", "done"}
ADR_STATUS = {"proposed", "accepted", "superseded"}
NOTE_STATUS = {"draft", "locked", "blocked", "done", "deferred", "template", "ready"}

# lane -> the phases it runs, in order. This mirrors the lane table in
# skills/loop/SKILL.md; change one and change the other.
LANES = {
    "feature": ("talk", "research", "adr", "plan", "execute", "verify", "retro"),
    "bug": ("talk", "diagnose", "execute", "verify"),
    "incident": ("diagnose", "execute", "verify", "retro"),
    "refactor": ("talk", "adr", "plan", "execute", "verify"),
    "spike": ("talk", "research", "retro"),
    "chore": ("execute", "verify"),
}

# Phases the lane table marks `?`. Skipping one is a decision the router records
# in the run log — not a reason for status to report it forever.
OPTIONAL = {
    "feature": frozenset({"research", "adr"}),
    "refactor": frozenset({"adr"}),
}

# What a vault with nothing in it yet is assumed to be running.
DEFAULT_LANE = "feature"

# type -> (id prefix, subdirectory, zero padding)
TYPES = {
    "task": ("T", "tasks", 4),
    "adr": ("ADR", "decisions", 4),
    "epic": ("EPIC", "plan", 2),
    "research": ("R", "research", 4),
    "retro": ("RETRO", "retro", 4),
}


# --------------------------------------------------------------------------- io

def repo_root():
    """Where the repo starts.

    CLAUDE_PROJECT_DIR is exported to hook processes, not to every Bash call the
    agent makes, so it is absent for most invocations of this script. Falling
    back to the cwd silently picks the wrong vault when the agent has changed
    directory; ask git the way vault_init.sh already does.
    """
    explicit = os.environ.get("CLAUDE_PROJECT_DIR")
    if explicit:
        return Path(explicit).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(".").resolve()


def vault_path():
    rel = os.environ.get("CLAUDE_PLUGIN_OPTION_VAULT_DIR") or "docs/vault"
    return repo_root() / rel


def parse_frontmatter(path):
    """Minimal YAML frontmatter reader for the flat scalar keys we define.

    Deliberately lenient: a malformed note should degrade to 'unknown' rather
    than crash a SessionStart hook and block the whole session.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta = {}
    for line in text[3:end].splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key not in SCALAR_KEYS:
            continue
        value = value.strip().strip('"').strip("'")
        meta[key] = None if value in ("", "null", "~") else value
    return meta


def load_notes(vault):
    notes = []
    for path in sorted(vault.rglob("*.md")):
        meta = parse_frontmatter(path)
        if meta.get("type"):
            meta["path"] = path
            notes.append(meta)
    return notes


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:48] or "untitled"


FENCE = re.compile(r"^(?:```|~~~).*?^(?:```|~~~)", re.MULTILINE | re.DOTALL)


def wikilinks(body):
    """The links Obsidian would actually follow.

    Fenced code is stripped first: this vault documents its own frontmatter
    schema in ```yaml blocks and its board in ```dataview blocks, so a link
    inside a fence is an example of a link, not one.
    """
    return {m.strip() for m in re.findall(r"\[\[([^\]|#]+)", FENCE.sub("", body)) if m.strip()}


# ----------------------------------------------------------------------- status

def unfilled(notes):
    """Seeded notes nobody has filled in yet.

    These are the files every phase loads, so leaving them as templates is the
    single biggest cause of generic output. Worth surfacing loudly.
    """
    return [n for n in notes if n.get("status") == "template"]


def newest(notes):
    """The note most recently touched. Ties break on path so it stays stable."""
    return max(notes, key=lambda n: (n.get("updated") or "", str(n["path"])))


def lane_of(notes):
    """Which lane this vault is running.

    `work_type` is set by every phase precisely so the lane survives a lost
    context. Read the most recently updated note that carries one: a vault
    accumulates lanes over time, and it is the current work that decides what
    phase comes next.
    """
    tagged = [n for n in notes if n.get("work_type") in LANES]
    return newest(tagged)["work_type"] if tagged else DEFAULT_LANE


def phase_state(phase, by_type, tasks, statuses):
    """Whether a phase's artifact exists yet, and why not if it doesn't."""
    if phase == "talk":
        briefs = by_type.get("brief", [])
        if not briefs:
            return False, "no brief yet"
        status = newest(briefs).get("status")
        if status == "draft":
            return False, "brief still in draft"
        if status == "blocked":
            return False, "brief blocked on an unanswered question"
        return True, ""
    if phase == "research":
        settled = [r for r in by_type.get("research", [])
                   if r.get("status") in ("done", "deferred")]
        return bool(settled), "open questions not yet researched"
    if phase == "adr":
        return bool(by_type.get("adr")), "no decisions recorded"
    if phase == "diagnose":
        # A tracked bug's findings go in the task note; anything larger gets a
        # research note. Either one means the symptom has been traced.
        traced = [r for r in by_type.get("research", []) if r.get("status") == "done"]
        return bool(traced or tasks), "symptom not yet traced to a root cause"
    if phase == "plan":
        return bool(tasks), "no tasks yet"
    if phase == "execute":
        # Met only when every task has positively reached review or done. Asking
        # instead whether any task is still todo/doing would let a task with no
        # status — or one doctor would reject — pass for implemented, and the
        # loop would wave unfinished work through to verify.
        past = tasks and all(s in ("review", "done") for s in statuses)
        return bool(past), "tasks remaining"
    if phase == "verify":
        done = tasks and all(s == "done" for s in statuses)
        return bool(done), "all tasks implemented, awaiting verification"
    if phase == "retro":
        return bool(by_type.get("retro")), "work verified, learnings not captured"
    return True, ""


def infer_phase(notes, lane=None):
    """Derive the phase from what exists on disk, so state survives lost context.

    Walk the lane's own phase list rather than assuming the feature pipeline —
    a chore has no brief to write and a bug lane has no retro to demand.

    The rule is "the first unmet phase *after* the last met one", not simply the
    first unmet one. Phases get skipped legitimately: a bug that never got a
    written brief has still moved past `talk` once its tasks are done, and
    reporting `talk` there would send the loop backwards.
    """
    by_type = {}
    for n in notes:
        by_type.setdefault(n["type"], []).append(n)
    tasks = by_type.get("task", [])
    statuses = [t.get("status") for t in tasks]
    lane = lane or lane_of(notes)

    # A blocked task outranks lane order — nothing downstream of it can proceed.
    if any(s == "blocked" for s in statuses):
        return "execute", "blocked task needs attention"

    phases = LANES.get(lane, LANES[DEFAULT_LANE])
    optional = OPTIONAL.get(lane, frozenset())
    state = [(p, *phase_state(p, by_type, tasks, statuses)) for p in phases]

    reached = max((i for i, (_, met, _) in enumerate(state) if met), default=-1)
    for i, (phase, met, why) in enumerate(state):
        # Phases the lane table marks `?` are the router's call to skip, recorded
        # in the run log. Their absence must not wedge the state machine.
        if i > reached and not met and phase not in optional:
            return phase, why
    return "done", "loop closed"


def cmd_status(vault):
    if not vault.is_dir():
        print(f"[loop] no vault at {vault}")
        print("[loop] phase: talk — run vault-init to start")
        return 0

    notes = load_notes(vault)
    todo = unfilled(notes)
    lane = lane_of(notes)
    if todo and not [n for n in notes if n["type"] in ("task", "brief")]:
        phase, why = "setup", "vault seeded but not filled in"
    else:
        phase, why = infer_phase(notes, lane)
    print(f"[loop] vault: {vault.name}   lane: {lane}   phase: {phase}   ({why})")

    if todo:
        names = ", ".join(sorted(n["path"].name for n in todo))
        print(f"[loop] SETUP NEEDED — still templates: {names}")
        print("[loop] every phase loads these; run the setup skill to draft them from this repo")

    tasks = [n for n in notes if n["type"] == "task"]
    if tasks:
        counts = {}
        for t in tasks:
            counts[t.get("status") or "unknown"] = counts.get(t.get("status") or "unknown", 0) + 1
        print("[loop] tasks: " + "  ".join(f"{k}:{v}" for k, v in sorted(counts.items())))

    # Everything printed here is injected into every session's context, so an
    # unbounded list would quietly tax the whole run. A junk value falls back to
    # the default rather than raising: this runs in the SessionStart hook, where
    # an exception costs the user their whole session over a cosmetic setting.
    try:
        cap = int(os.environ.get("LOOP_STATE_MAX_BLOCKED", "5"))
    except ValueError:
        cap = 5
    blocked = [t for t in tasks if t.get("status") == "blocked"]
    for t in blocked[:cap]:
        print(f"[loop] BLOCKED {t.get('id')} {t.get('title')}")
    if len(blocked) > cap:
        print(f"[loop] ...and {len(blocked) - cap} more blocked")

    unsynced = [t for t in tasks if not t.get("gh_issue") and t.get("status") != "done"]
    if unsynced:
        ids = ", ".join(str(t.get("id")) for t in unsynced[:8])
        more = f" (+{len(unsynced) - 8} more)" if len(unsynced) > 8 else ""
        print(f"[loop] not mirrored to GitHub: {ids}{more}")
    return 0


# ---------------------------------------------------------------------- next-id

def next_id(vault, kind):
    prefix, _, pad = TYPES[kind]
    highest = 0
    for note in load_notes(vault):
        nid = note.get("id") or ""
        match = re.fullmatch(rf"{prefix}-(\d+)", nid)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:0{pad}d}"


def cmd_next_id(vault, kind):
    print(next_id(vault, kind))
    return 0


# -------------------------------------------------------------------------- new

TEMPLATE = """---
type: {kind}
id: {nid}
title: {title}
status: {status}
work_type: feature
owner: unassigned
{extra}created: {today}
updated: {today}
---

# {title}

"""

EXTRA = {
    "task": 'epic: \ngh_issue: null\nadrs: []\ndepends_on: []\n',
    "adr": 'supersedes: null\nsuperseded_by: null\ndeciders: []\n',
    "epic": 'adrs: []\n',
}

INITIAL_STATUS = {"adr": "proposed", "research": "todo", "retro": "done"}


def cmd_new(vault, kind, title):
    prefix, subdir, _ = TYPES[kind]
    nid = next_id(vault, kind)
    target_dir = vault / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{nid}-{slugify(title)}.md"
    if path.exists():
        print(f"refusing to overwrite {path}", file=sys.stderr)
        return 1
    path.write_text(
        TEMPLATE.format(
            kind=kind, nid=nid, title=title,
            status=INITIAL_STATUS.get(kind, "todo"),
            extra=EXTRA.get(kind, ""), today=date.today().isoformat(),
        ),
        encoding="utf-8",
    )
    print(path)
    return 0


# ----------------------------------------------------------------------- doctor

def cmd_doctor(vault):
    if not vault.is_dir():
        print(f"no vault at {vault}")
        return 1

    notes = load_notes(vault)
    problems = []

    # Index notes (context, glossary, standards) are addressed by filename and
    # legitimately carry no ID. Only the numbered types need one.
    seen = {}
    for n in notes:
        nid = n.get("id")
        if not nid:
            if n["type"] in TYPES or n["type"] == "brief":
                problems.append(f"missing id: {n['path'].relative_to(vault)}")
            continue
        if nid in seen:
            problems.append(
                f"duplicate id {nid}: {seen[nid].relative_to(vault)} and "
                f"{n['path'].relative_to(vault)}")
        seen[nid] = n["path"]

    for n in notes:
        status, kind = n.get("status"), n["type"]
        allowed = ADR_STATUS if kind == "adr" else TASKISH | NOTE_STATUS
        if status and status not in allowed:
            problems.append(f"{n.get('id')}: unknown status '{status}'")

    # Obsidian resolves both the bare filename and a path relative to the vault,
    # so accept either. Flagging [[standards/engineering]] as broken fails a
    # perfectly valid vault, which teaches people to stop running doctor.
    targets = set()
    for p in vault.rglob("*.md"):
        targets.add(p.stem)
        targets.add(p.relative_to(vault).with_suffix("").as_posix())

    for n in notes:
        body = n["path"].read_text(encoding="utf-8", errors="replace")
        for link in wikilinks(body):
            if link not in targets:
                where = n.get("id") or n["path"].relative_to(vault)
                problems.append(f"{where}: broken link [[{link}]]")

    epics = {n.get("id") for n in notes if n["type"] == "epic"}
    for n in notes:
        if n["type"] == "task" and n.get("epic") and n["epic"] not in epics:
            problems.append(f"{n.get('id')}: epic {n['epic']} does not exist")

    if not problems:
        print(f"vault ok — {len(notes)} notes, no problems found")
        return 0
    for p in problems:
        print(f"  {p}")
    print(f"\n{len(problems)} problem(s) across {len(notes)} notes")
    return 1


# ------------------------------------------------------------------------- main

def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd, vault = argv[1], vault_path()

    if cmd == "status":
        return cmd_status(vault)
    if cmd == "doctor":
        return cmd_doctor(vault)
    if cmd == "next-id":
        if len(argv) < 3 or argv[2] not in TYPES:
            print(f"usage: loop.py next-id <{'|'.join(TYPES)}>", file=sys.stderr)
            return 1
        return cmd_next_id(vault, argv[2])
    if cmd == "new":
        if len(argv) < 4 or argv[2] not in TYPES:
            print(f"usage: loop.py new <{'|'.join(TYPES)}> <title>", file=sys.stderr)
            return 1
        return cmd_new(vault, argv[2], " ".join(argv[3:]))

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
