#!/usr/bin/env python3
"""Vault tooling for Agent Pingu.

Invoked as `pingu <command>` — bin/pingu puts this on the Bash tool's PATH.

  pingu status              current lane and phase, blockers, unsynced tasks
  pingu next-id <type>      allocate the next free ID (task|adr|epic|research|retro)
  pingu new <type> <title>  scaffold a note with correct frontmatter, print its path
  pingu doctor              validate the vault: duplicate IDs, bad status,
                           broken wikilinks, orphaned tasks, missing fields
  pingu gate [<phase>]      evaluate a phase's exit condition. Plans by default;
                           --execute runs the commands context.md declares.
                           Defaults to the phase status infers.

Config, read from the environment:
  CLAUDE_PROJECT_DIR              repo root. Exported to hook processes only, so
                                  this falls back to `git rev-parse --show-toplevel`
  CLAUDE_PLUGIN_OPTION_VAULT_DIR  vault path relative to the repo, defaults to docs/vault
  PINGU_STATE_MAX_BLOCKED          cap on blocked lines printed by status (default 5)

No third-party dependencies, so it runs wherever Python 3 does. The tests need
pytest; the tooling itself does not.
"""

import json
import os
import re
import subprocess
import sys
from collections import namedtuple
from datetime import date
from pathlib import Path

SCALAR_KEYS = (
    "type", "id", "status", "title", "epic", "gh_issue",
    "owner", "updated", "created", "work_type",
    "test_command", "lint_command",
)

# Where parse_frontmatter records every key a note declared, including the list
# ones it does not parse. Presence and value are different questions: a
# scaffolded ADR carries `deciders: []`, which is empty but not missing.
DECLARED = "_declared"

# What each note type must declare, from the schema in skills/vault/SKILL.md.
# Presence only — an empty `epic:` on a freshly scaffolded task is a workflow
# state, but a task with no epic key at all is a note somebody hand-wrote and
# the board will silently drop.
REQUIRED_FIELDS = {
    "brief": ("id", "title", "status", "work_type"),
    "epic": ("id", "title", "status", "work_type"),
    "task": ("id", "title", "status", "work_type", "epic"),
    "adr": ("id", "title", "status", "deciders"),
    "research": ("id", "title", "status"),
    "retro": ("id", "title", "status"),
}

TASKISH = {"todo", "doing", "blocked", "review", "done"}
ADR_STATUS = {"proposed", "accepted", "superseded"}
NOTE_STATUS = {"draft", "locked", "blocked", "done", "deferred", "template", "ready"}

# lane -> the phases it runs, in order. This mirrors the lane table in
# skills/start/SKILL.md; change one and change the other.
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
    meta = {DECLARED: set()}
    for line in text[3:end].splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        meta[DECLARED].add(key)
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
        print(f"[pingu] no vault at {vault}")
        print("[pingu] phase: talk — run vault-init to start")
        return 0

    notes = load_notes(vault)
    todo = unfilled(notes)
    lane = lane_of(notes)
    if todo and not [n for n in notes if n["type"] in ("task", "brief")]:
        phase, why = "setup", "vault seeded but not filled in"
    else:
        phase, why = infer_phase(notes, lane)
    print(f"[pingu] vault: {vault.name}   lane: {lane}   phase: {phase}   ({why})")

    if todo:
        names = ", ".join(sorted(n["path"].name for n in todo))
        print(f"[pingu] SETUP NEEDED — still templates: {names}")
        print("[pingu] every phase loads these; run the setup skill to draft them from this repo")

    tasks = [n for n in notes if n["type"] == "task"]
    if tasks:
        counts = {}
        for t in tasks:
            counts[t.get("status") or "unknown"] = counts.get(t.get("status") or "unknown", 0) + 1
        print("[pingu] tasks: " + "  ".join(f"{k}:{v}" for k, v in sorted(counts.items())))

    # Everything printed here is injected into every session's context, so an
    # unbounded list would quietly tax the whole run. A junk value falls back to
    # the default rather than raising: this runs in the SessionStart hook, where
    # an exception costs the user their whole session over a cosmetic setting.
    try:
        cap = int(os.environ.get("PINGU_STATE_MAX_BLOCKED", "5"))
    except ValueError:
        cap = 5
    blocked = [t for t in tasks if t.get("status") == "blocked"]
    for t in blocked[:cap]:
        print(f"[pingu] BLOCKED {t.get('id')} {t.get('title')}")
    if len(blocked) > cap:
        print(f"[pingu] ...and {len(blocked) - cap} more blocked")

    unsynced = [t for t in tasks if not t.get("gh_issue") and t.get("status") != "done"]
    if unsynced:
        ids = ", ".join(str(t.get("id")) for t in unsynced[:8])
        more = f" (+{len(unsynced) - 8} more)" if len(unsynced) > 8 else ""
        print(f"[pingu] not mirrored to GitHub: {ids}{more}")
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
    # legitimately carry no ID or work_type. Only the types in REQUIRED_FIELDS
    # are held to a schema.
    seen = {}
    for n in notes:
        where = n.get("id") or n["path"].relative_to(vault)
        for field in REQUIRED_FIELDS.get(n["type"], ()):
            if field not in n[DECLARED]:
                problems.append(f"{where}: missing required field '{field}'")

        nid = n.get("id")
        if not nid:
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


# ------------------------------------------------------------------------ gates

# A gate is a list of checks, each of one of three kinds:
#
#   vault   — computed from the notes on disk. Deterministic and always runnable.
#   command — runs a command the vault declares in context.md's frontmatter.
#   manual  — a judgement no tool can make. Never auto-passes, ever.
#
# The third kind is the one that makes the other two trustworthy. Without it
# every gate has to be forced into something checkable, and "the model said the
# acceptance criteria were met" quietly becomes a green tick.
Check = namedtuple("Check", "kind name detail")


def note_body(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def section(body, heading):
    """The text under a `## heading`, or None when absent. Empty means None too —
    a heading with nothing under it is the failure this is looking for."""
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", body, re.MULTILINE | re.DOTALL)
    return (match.group(1).strip() or None) if match else None


def _gate_setup(notes, vault):
    todo = unfilled(notes)
    if todo:
        return False, "still templates: " + ", ".join(sorted(n["path"].name for n in todo))
    return True, "no note is still a template"


def _gate_brief(notes, vault):
    briefs = [n for n in notes if n["type"] == "brief"]
    if not briefs:
        return False, "no brief exists yet"
    body = note_body(newest(briefs)["path"])
    missing = [h for h in ("Success criteria", "Non-goals") if not section(body, h)]
    if missing:
        return False, "empty or absent: " + ", ".join(missing)
    # Deliberately only checks that the sections have content. Whether that
    # content is any good is a manual judgement, and pretending otherwise would
    # be the exact self-certification these gates exist to remove.
    return True, "success criteria and non-goals both have content"


def _gate_research(notes, vault):
    open_questions = [n for n in notes if n["type"] == "research"
                      and n.get("status") not in ("done", "deferred")]
    if open_questions:
        return False, "still open: " + ", ".join(str(n.get("id")) for n in open_questions)
    return True, "every research note is answered or deferred"


def _gate_plan(notes, vault):
    tasks = [n for n in notes if n["type"] == "task"]
    if not tasks:
        return False, "no tasks have been cut yet"
    problems = []
    for task in tasks:
        if not task.get("epic"):
            problems.append(f"{task.get('id')} links to no epic")
        criteria = section(note_body(task["path"]), "Acceptance criteria")
        if not criteria or "- [" not in criteria:
            problems.append(f"{task.get('id')} has no acceptance criteria")
    if problems:
        return False, "; ".join(problems)
    return True, f"all {len(tasks)} task(s) have criteria and an epic"


def _gate_execute(notes, vault):
    tasks = [n for n in notes if n["type"] == "task"]
    if not tasks:
        return False, "no tasks to execute"
    remaining = [t for t in tasks if t.get("status") not in ("review", "done")]
    if remaining:
        return False, "not yet at review: " + ", ".join(str(t.get("id")) for t in remaining)
    return True, f"all {len(tasks)} task(s) reached review or done"


def _gate_retro(notes, vault):
    if not [n for n in notes if n["type"] == "retro"]:
        return False, "no retro note written"
    return True, "a retro note exists"


# Mirrors the gate table in skills/start/SKILL.md. tests/test_skills.py holds the
# two in step, the same way it does for LANES.
GATES = {
    "setup": (
        Check("vault", "standards, context and glossary are filled in", _gate_setup),
        Check("manual", "a human has reviewed what setup inferred",
              "Setup marks lines inferred vs agreed. Someone has to read them."),
    ),
    "talk": (
        Check("vault", "brief states success criteria and non-goals", _gate_brief),
    ),
    "research": (
        Check("vault", "every open question is answered or deferred", _gate_research),
    ),
    "adr": (
        Check("manual", "every decision constraining the plan is accepted",
              "Which decisions constrain the plan cannot be read off disk."),
    ),
    "plan": (
        Check("vault", "every task has acceptance criteria and an epic", _gate_plan),
    ),
    "diagnose": (
        Check("manual", "root cause identified and reproduced by a failing test",
              "A test that fails for the right reason. Only a human can say."),
    ),
    "execute": (
        Check("vault", "every task has reached review or done", _gate_execute),
        Check("command", "test suite passes", "test_command"),
        Check("manual", "acceptance criteria genuinely met, not approximately",
              "Check each criterion against the code, not the task's status field."),
    ),
    "verify": (
        Check("command", "test suite passes", "test_command"),
        Check("manual", "reviews returned with no blocking findings",
              "The four reviewers ran and their blocking findings are closed."),
    ),
    "retro": (
        Check("vault", "a retro note exists", _gate_retro),
        Check("manual", "learnings written back into standards, patterns or glossary",
              "A retro nobody acted on is a diary entry."),
    ),
}


def declared_command(vault, key):
    """(argv, error) for a command the vault declares in context.md frontmatter.

    Declared as a JSON list, never a string. A string would invite
    `npm test && deploy` and the only way to honour that is a shell, which is
    the one thing a gate runner must not hand someone else's file.
    """
    raw = parse_frontmatter(vault / "context.md").get(key)
    if not raw:
        return None, f"no {key} declared in context.md frontmatter"
    example = '["pytest", "-q"]'
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, f"{key} must be a JSON list of arguments, e.g. {example}"
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        return None, f"{key} must be a non-empty JSON list of strings, e.g. {example}"
    return value, None


def run_command_check(vault, key, timeout=900):
    argv, error = declared_command(vault, key)
    if error:
        return {"status": "not-declared", "detail": error}
    try:
        completed = subprocess.run(
            argv, cwd=repo_root(), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "command": argv,
                "detail": f"timed out after {timeout}s"}
    except OSError as exc:
        return {"status": "failed", "command": argv, "detail": str(exc)}
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": argv,
        "detail": f"exit code {completed.returncode}",
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def run_gate(vault, phase, execute=False):
    """Evaluate one phase's gate. Plans command checks unless execute is set."""
    notes = load_notes(vault)
    checks = []
    for check in GATES[phase]:
        if check.kind == "manual":
            checks.append({"name": check.name, "kind": "manual",
                           "status": "manual-review", "detail": check.detail})
        elif check.kind == "vault":
            met, detail = check.detail(notes, vault)
            checks.append({"name": check.name, "kind": "vault",
                           "status": "passed" if met else "failed", "detail": detail})
        elif execute:
            checks.append({"name": check.name, "kind": "command",
                           **run_command_check(vault, check.detail)})
        else:
            argv, error = declared_command(vault, check.detail)
            checks.append({"name": check.name, "kind": "command",
                           "status": "not-declared" if error else "planned",
                           "detail": error or "would run: " + " ".join(argv)})

    failed = [c["name"] for c in checks if c["status"] == "failed"]
    pending = [c["name"] for c in checks
               if c["status"] in ("manual-review", "planned", "not-declared")]
    return {
        "phase": phase,
        "executed": execute,
        "checks": checks,
        "failed": failed,
        "pending": pending,
        # ok: nothing this run could check is broken.
        # ready: everything was actually checked and nothing is outstanding.
        # Keeping them apart is the point — "not yet verified" is not "fine".
        #
        # `ready` does not also require execute=True: an unrun command already
        # lands in `pending` as "planned". Requiring the flag would report a
        # gate that declares no commands at all — talk, plan, research — as
        # unmet no matter what, which is a lie in the safe direction but still
        # a lie.
        "ok": not failed,
        "ready": not failed and not pending,
    }


def cmd_gate(vault, phase, execute):
    if not vault.is_dir():
        print(f"[gate] no vault at {vault}")
        return 1
    if phase is None:
        phase, why = infer_phase(load_notes(vault))
        if phase not in GATES:
            print(f"[gate] phase is '{phase}' ({why}) — nothing left to gate")
            return 0
    if phase not in GATES:
        print(f"unknown phase '{phase}' — one of: {', '.join(GATES)}", file=sys.stderr)
        return 1

    result = run_gate(vault, phase, execute=execute)
    print(f"[gate] {phase}   ({'executed' if execute else 'planned'})")
    for check in result["checks"]:
        print(f"  {check['status']:<14} {check['name']}")
        if check.get("detail"):
            print(f"  {'':<14} {check['detail']}")
        tail = (check.get("stderr_tail") or check.get("stdout_tail") or "").strip()
        if check["status"] == "failed" and tail:
            for line in tail.splitlines()[-5:]:
                print(f"  {'':<14} | {line}")

    if result["failed"]:
        print(f"[gate] BLOCKED — {len(result['failed'])} check(s) failed; the phase does not advance")
    elif result["ready"]:
        print("[gate] all checks passed")
    else:
        print(f"[gate] {len(result['pending'])} check(s) still outstanding — the gate is not met yet")
        print("[gate] manual-review means not verified by tooling; a human confirms those")
        if not execute:
            print("[gate] re-run with --execute to run the declared commands")
    return 1 if result["failed"] else 0


# ------------------------------------------------------------------------- main

def main(argv):
    execute = "--execute" in argv
    argv = [a for a in argv if a != "--execute"]
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd, vault = argv[1], vault_path()

    if cmd == "gate":
        return cmd_gate(vault, argv[2] if len(argv) > 2 else None, execute)
    if cmd == "status":
        return cmd_status(vault)
    if cmd == "doctor":
        return cmd_doctor(vault)
    if cmd == "next-id":
        if len(argv) < 3 or argv[2] not in TYPES:
            print(f"usage: pingu.py next-id <{'|'.join(TYPES)}>", file=sys.stderr)
            return 1
        return cmd_next_id(vault, argv[2])
    if cmd == "new":
        if len(argv) < 4 or argv[2] not in TYPES:
            print(f"usage: pingu.py new <{'|'.join(TYPES)}> <title>", file=sys.stderr)
            return 1
        return cmd_new(vault, argv[2], " ".join(argv[3:]))

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
