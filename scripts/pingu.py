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
  pingu vault-path          print the resolved vault directory

Plugin options (vault_dir, gh_repo, autonomy) come from `pluginConfigs` in the
settings files, read most specific first:

  <repo>/.claude/settings.local.json   personal override for this repo
  <repo>/.claude/settings.json         the team's setting, committed
  ~/.claude/settings.json              personal default

Read directly because neither route that looks like it should work does:
`${user_config.KEY}` never interpolates in a skill body, and
`CLAUDE_PLUGIN_OPTION_*` is not exported to the Bash tool. The env vars are still
honoured first if anything ever does export them.

From the environment:
  CLAUDE_PROJECT_DIR        repo root. Exported to hook processes only, so this
                            falls back to `git rev-parse --show-toplevel`
  PINGU_STATE_MAX_BLOCKED   cap on blocked lines printed by status (default 5)

No third-party dependencies, so it runs wherever Python 3 does — POSIX-only
calls are guarded rather than assumed. The tests need pytest and PyYAML; the
tooling itself needs neither.
"""

import json
import os
import re
import shutil
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


PLUGIN_NAME = "agent-pingu"
# Keyed by level rather than written as an if/else, so adding a third one has to
# say what it does instead of silently inheriting whichever branch came last.
# Same reasoning as LANES and GATES, and the same drift test guards it.
AUTONOMY_LEVELS = {
    "full-loop": "runs the whole lane, then stops once for review",
    "gated": "stops after every phase for your approval",
}
DEFAULT_AUTONOMY = "full-loop"


HOOKS_JSON = Path(__file__).resolve().parent.parent / "hooks" / "hooks.json"

# Why the personal settings file could not be used, and whether that reason is
# something only a hostile repo produces.
#
# The distinction earns its keep in `autonomy`. "No home on this machine" is
# ordinary — containers, CI, minimal images — and ADR-0004 deliberately degrades
# rather than fails there. "Home is a relative path" and "home is inside the
# checkout" are not ordinary: neither has a legitimate cause, and both were
# measured as working forgeries of the user's own settings. Refusing to let the
# repo loosen autonomy in those two cases costs a real user nothing, because no
# real user is in them.
SettingsProblem = namedtuple("SettingsProblem", "reason tampering")


def hook_interpreter_names(hooks_json=None):
    """The interpreter names the hooks try, in order, read out of hooks.json.

    Read rather than restated. `doctor` has to answer "will the hooks find a
    Python", and the only honest way to answer it is to ask the same file the
    hooks are declared in — a hard-coded ("python3", "python") here would be a
    second resolver that agrees with the hooks right up until someone edits one
    of them, which is the failure ADR-0001 is named for.
    """
    path = Path(hooks_json) if hooks_json else HOOKS_JSON
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ()
    names, seen = [], set()
    # `isinstance` rather than `data.get`: valid JSON that is not an object at
    # the top level (`[]`) would raise AttributeError straight out of a function
    # whose whole contract is to answer or return empty.
    events = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(events, dict):
        return ()
    for groups in events.values():
        for group in groups or ():
            for hook in group.get("hooks") or ():
                for name in re.findall(r"command -v ([\w.-]+)",
                                       str(hook.get("command", ""))):
                    if name not in seen:
                        seen.add(name)
                        names.append(name)
    return tuple(names)


def hook_interpreter(hooks_json=None):
    """(name, absolute path) of the first hook interpreter that resolves."""
    for name in hook_interpreter_names(hooks_json):
        found = shutil.which(name)
        if found:
            return name, found
    return None, None


def _is_inside(path, root):
    """Whether `path` lies within `root`, on filesystems that lie about case.

    Two comparisons, because neither alone is enough and this one guards a
    security boundary:

      - **String**, over `realpath`. Answers for a path that does not exist yet,
        which the settings file often does not.
      - **`os.path.samefile`**, walking `path`'s ancestors. `realpath` resolves
        symlinks but does **not** canonicalise case, and this ships on APFS and
        NTFS — both case-insensitive, both in the CI matrix. So a `HOME` differing
        from the checkout only in case pointed at the very same directory and
        compared unequal as a string, which slipped the whole forgery through on
        the two commonest desktop platforms. `samefile` compares device and inode,
        so it is immune to case and to symlinks alike.

    Found by a reviewer, not by the tests — the other two forgery vectors were
    mutation-tested and this third one sat between them.
    """
    try:
        real_path = os.path.realpath(str(path))
        real_root = os.path.realpath(str(root))
    except (OSError, ValueError):
        return False

    try:
        if os.path.commonpath((real_path, real_root)) == real_root:
            return True
    except (OSError, ValueError):
        # Different drives on Windows raise rather than compare. Not inside, then.
        pass

    current = Path(real_path)
    for ancestor in (current,) + tuple(current.parents):
        try:
            if os.path.samefile(str(ancestor), real_root):
                return True
        except (OSError, ValueError):
            continue
    return False


def personal_settings_file():
    """(path, problem) for `~/.claude/settings.json`. Exactly one is None.

    The single place that decides whether a personal settings file exists and may
    be trusted. `settings_files` and `status` both ask it rather than each
    deciding — a second answer to "where is the personal file" is the shape
    ADR-0001 exists to forbid.

    `HOME` is not a fact about the machine. Claude Code applies the `env` key of
    a repo-committed `.claude/settings.json` to hook subprocesses — measured
    2026-08-08 with a sentinel variable, not assumed — so `HOME` is an input the
    *less* trusted source controls. ADR-0004 rule 2 lets the personal file set a
    floor the repo may not loosen, and three ways to forge or erase that floor
    were measured on this machine, all from a committed file:

        HOME=""             -> Path.home() is `.` on 3.9, so the "personal" file
                               resolves to <cwd>/.claude/settings.json — the
                               checkout. The repo is read as the user's own
                               choice. It does not remove the floor, it *forges*
                               one. (3.13 gives `/` instead; absent, not forged.)
        HOME=<the checkout> -> same forgery, absolute path, and so on every
                               Python version rather than only 3.9.
        HOME=/nonexistent   -> unreadable, floor absent.

    So two rules, and they are about the path rather than about readability:
    a personal file must be **absolute**, and must lie **outside the repo**. A
    path failing either is refused rather than read.

    Refusing downgrades a forgery to an absence. It cannot do better: there is no
    way to recover the real home once `HOME` has been overwritten. Absence is
    already the documented degradation and `status` already announces it, which
    is why this returns the reason rather than just dropping the file — an
    unreported bypass is the thing being fixed, not the dropped setting.

    Never raises; this runs inside the SessionStart hook.
    """
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        return None, SettingsProblem("no home directory resolves", tampering=False)

    if not home.is_absolute():
        return None, SettingsProblem(
            f"the home directory resolves to a relative path ({str(home)!r})",
            tampering=True)

    candidate = home / ".claude" / "settings.json"
    if _is_inside(candidate, repo_root()):
        return None, SettingsProblem(
            f"the home directory resolves inside the repo ({str(home)!r})",
            tampering=True)

    # A home that is not there at all is the third measured bypass, and it was
    # the quiet one: absolute, outside the repo, and so indistinguishable from a
    # user who simply never wrote a settings file. It is distinguishable one
    # level up — a real home exists. A *missing settings.json inside an existing
    # home* stays silent, because that is the ordinary state of most machines and
    # ADR-0004 deliberately degrades rather than fails there.
    if not home.is_dir():
        return None, SettingsProblem(
            f"the home directory does not exist ({str(home)!r})", tampering=False)

    return candidate, None


def home_resolves():
    """Whether a personal settings file exists and may be trusted.

    Kept as the predicate `status` and the tests read. It now means "the personal
    file is usable", which is strictly wider than the original "`Path.home()` did
    not raise" — the widening is the fix, see `personal_settings_file`.
    """
    return personal_settings_file()[0] is not None


def settings_files(scope="all"):
    """Where a plugin option can be declared, most specific first.

    Mirrors Claude Code's own settings precedence, minus the enterprise policy
    file — that one is for administrators pinning behaviour, and this plugin has
    no business reading it.

    `scope="user"` returns only the personal file, for the one setting where the
    repo is the less trusted source rather than the more specific one.
    """
    root = repo_root()
    found, _ = personal_settings_file()
    if found is not None:
        personal = (found,)
    else:
        # No trustworthy personal file — see `personal_settings_file` for the
        # three ways a committed `.claude/settings.json` can produce that, two of
        # which used to *forge* the personal file rather than remove it. The
        # repo-scoped files below can still answer, and dropping the personal one
        # loses a setting rather than the session.
        #
        # `status` announces the reason. Silence here is what made the bypass
        # invisible; do not make this branch quiet again.
        #
        # Bigger than it looks: `main()` resolves `vault_path()` for *every*
        # command, `guard` included, so before this the PreToolUse hook died with
        # a traceback and exit 1 on such a machine — which the hook protocol reads
        # as a non-blocking error, so the edit proceeded. Fail-open by crash.
        #
        # Two consequences to know before touching this. ADR-0004's autonomy floor
        # cannot fire while `personal` is empty, which that ADR now documents. And
        # several tests in `test_setup_guard.py`, `test_ids.py` and
        # `test_frontmatter_yaml.py` build a subprocess env by hand; if anyone
        # revisits the fail-closed trade ADR-0004 rejected, those go red for a
        # reason that looks nothing like the change that broke them.
        personal = ()
    if scope == "user":
        return personal
    return (
        root / ".claude" / "settings.local.json",
        root / ".claude" / "settings.json",
    ) + personal


def plugin_option(key, default=None, scope="all"):
    """Resolve one of plugin.json's userConfig options.

    The two obvious routes both turn out to be fiction, verified against a real
    session rather than assumed:

      - `${user_config.KEY}` does not interpolate in a SKILL.md body. It arrives
        at the model as that literal string.
      - `CLAUDE_PLUGIN_OPTION_KEY` is not exported to the Bash tool.

    So an option is only real if we read the settings file ourselves. The env var
    is still honoured first in case some other context does export it; nothing
    breaks if it stays absent forever.

    Never raises. This runs inside the SessionStart hook, where an exception over
    a stray comma in a file this plugin does not own would cost the whole session.
    """
    # The env var is honoured for ordinary lookups — `vault_init.sh` passes
    # `CLAUDE_PLUGIN_OPTION_VAULT_DIR` deliberately — but **never** for the
    # personal scope. That scope exists precisely because the repo is the *less*
    # trusted source, and the environment is something a repo-committed
    # `.claude/settings.json` sets via its `env` key (measured, see
    # `personal_settings_file`).
    #
    # Without this, `{"env": {"CLAUDE_PLUGIN_OPTION_AUTONOMY": "full-loop"}}` made
    # `autonomy()`'s floor read return the attacker's own string, so the floor
    # compared full-loop against full-loop and never fired. A total bypass of
    # ADR-0004 rule 2 that walked straight past every check added for it — found
    # by the security reviewer, with a repro, after the rest of this was done.
    if scope != "user":
        env = os.environ.get("CLAUDE_PLUGIN_OPTION_" + key.upper())
        if env:
            return env

    for path in settings_files(scope):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        configs = data.get("pluginConfigs")
        if not isinstance(configs, dict):
            continue
        for name, entry in configs.items():
            # The suffix records how the plugin was discovered — @skills-dir, or
            # a marketplace name. Matching on it would make the setting silently
            # stop working when someone installs it a different way.
            if name.split("@", 1)[0] != PLUGIN_NAME or not isinstance(entry, dict):
                continue
            options = entry.get("options")
            if isinstance(options, dict) and options.get(key):
                return str(options[key])
    return default


def autonomy():
    """(level, unrecognised_raw_value).

    An unknown value falls back rather than failing, but reports itself, because
    silently treating `Gated ` as the default is how somebody runs unattended for
    a week believing they had asked to be stopped at every phase.
    """
    raw = plugin_option("autonomy", DEFAULT_AUTONOMY)
    if raw not in AUTONOMY_LEVELS:
        return DEFAULT_AUTONOMY, raw

    # A repo may tighten autonomy; it may not loosen it. Repo-local settings
    # outrank the user's own, and MANUAL tells teams to commit that file — so
    # without this a PR branch could return someone who chose `gated` to
    # `full-loop`, removing the per-phase stop they asked for. Advisory rather
    # than enforced (the level is a string the model reads), but a
    # security-relevant setting whose least-trusted source wins is backwards.
    # Refusing to *read* a forged personal file is only half the fix. Measured:
    # with the forgery blocked, the personal floor is merely absent, so the
    # repo's own `full-loop` still wins — the repo cannot impersonate the user,
    # but it can still silently remove the stop the user asked for, which is the
    # outcome the attack wanted anyway.
    #
    # So where the evidence of tampering is unambiguous, refuse to loosen. A
    # relative home and a home inside the checkout have no legitimate cause; a
    # machine with no home at all has several, and that one keeps degrading the
    # way ADR-0004 chose, alongside `test_unreadable_settings_degrade_to_the_default`.
    _, problem = personal_settings_file()
    if problem is not None and problem.tampering:
        return "gated", None

    personal = plugin_option("autonomy", DEFAULT_AUTONOMY, scope="user")
    if personal == "gated" and raw != "gated":
        return "gated", None
    return raw, None


def vault_path():
    """The vault directory, always inside the repo.

    `repo_root() / value` discards the base entirely when the value is absolute,
    and nothing rejected `..` — so a committed `.claude/settings.json` could
    point the vault at `/etc`, or anywhere else on the machine. No interaction
    was needed to trigger it: checking out a contributor's branch is enough,
    because the SessionStart hook runs `pingu status` unprompted, and with
    `vault_dir: "/"` that walks and reads every markdown file on the disk.

    plugin.json already documents the option as "relative to the repo root".
    This is that promise, enforced.
    """
    root = repo_root()
    declared = plugin_option("vault_dir", "docs/vault")
    candidate = (root / declared).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        print(f"[pingu] ignoring vault_dir {declared!r}: it resolves outside the repo "
              f"({candidate}). Using docs/vault.", file=sys.stderr)
        return root / "docs/vault"
    return root / declared


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
        meta[key] = yaml_scalar(value)
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


def cmd_status(vault, quiet=False):
    if not vault.is_dir():
        # The SessionStart hook passes --quiet. It fires in *every* project,
        # because a personal-scope plugin loads everywhere, and a repo with no
        # vault is not using the loop — so this banner would be context spent in
        # every unrelated session telling somebody something they did not ask.
        # A human who types `pingu status` still gets the explanation.
        if not quiet:
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

    # The router used to carry this as `${user_config.autonomy}` in its own text,
    # which never interpolated — so the setting did nothing at all. Stating it
    # here puts it in front of every session, and `start` reads it from this
    # output rather than from a placeholder.
    level, unrecognised = autonomy()
    if unrecognised:
        print(f"[pingu] autonomy setting {unrecognised!r} is not recognised — "
              f"expected one of: {', '.join(AUTONOMY_LEVELS)}")
    print(f"[pingu] autonomy: {level} — {AUTONOMY_LEVELS[level]}")

    # Rare, and silent until now, which is the problem: with no home the personal
    # settings file is simply dropped, so every option falls back and behaves
    # exactly as though nothing had been declared. Three consequences the user
    # would otherwise have no way to notice — a personal `vault_dir` ignored (so
    # the setup guard inspects a directory that does not exist and allows
    # everything), a personal `gh_repo` ignored, and ADR-0004's autonomy floor
    # unable to fire at all.
    #
    # Said here rather than raised, because `plugin_option` promises never to
    # raise and this runs inside the SessionStart hook. Degrade, but say so —
    # the same trade as the unrecognised-autonomy line above.
    _, personal_problem = personal_settings_file()
    if personal_problem:
        print(f"[pingu] {personal_problem.reason}, so personal settings in "
              "~/.claude/settings.json are being ignored entirely")
        print("[pingu] repo settings still apply; a personal vault_dir, gh_repo "
              "or autonomy floor does not")

    if todo:
        names = ", ".join(sorted(n["path"].name for n in todo))
        if (vault / SETUP_DECLINED).is_file():
            # Asked and answered. Repeating the offer every session contradicts
            # the decision in front of the person who made it.
            print(f"[pingu] setup declined — running on generic defaults ({names})")
            print(f"[pingu] delete {SETUP_DECLINED} in the vault to be asked again")
        else:
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


# ------------------------------------------------------------------ setup guard

SETUP_DECLINED = ".setup-declined"

# Tools that put new content into the repo. Reading is never blocked: setup works
# by reading, and so does deciding whether setup is worth doing at all.
EDITING_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def cmd_guard(vault):
    """Refuse edits outside the vault while the vault is still templates.

    The router already says to stop and offer setup first. That is advice, and
    advice held in one headless run and not in another against a near-identical
    repo — the second spent ten minutes implementing a feature against template
    standards, which is the exact output the vault exists to prevent. An
    instruction that works most of the time is the worst failure rate to debug.

    This repo's own argument is that the model is the one party that cannot be
    trusted to say whether it met its own gate. The setup gate was the last one
    still asking it.

    Fails open on anything unexpected. It runs in front of every edit in every
    project a personal-scope plugin loads into, so a bug that blocked writing
    would cost far more than this protection is worth.
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if payload.get("tool_name") not in EDITING_TOOLS:
            return 0
        if (vault / SETUP_DECLINED).is_file():
            return 0                    # asked and answered
        # Covers both "no vault here" and "vault is filled in": load_notes on a
        # missing directory returns [], so a repo that never asked for a vault
        # falls through the same allow as one that is set up. An explicit
        # is_dir() check read better and was redundant — no test could tell it
        # from its absence, which by this repo's own rule means it goes.
        todo = unfilled(load_notes(vault))
        if not todo:
            return 0

        target = (payload.get("tool_input") or {}).get("file_path") or ""
        if target:
            try:
                # Setup must be able to write the files that are blocking setup.
                Path(target).resolve().relative_to(vault.resolve())
                return 0
            except ValueError:
                pass
        names = ", ".join(sorted(n["path"].name for n in todo))
    except Exception:
        return 0

    print(
        "Blocked by agent-pingu: this repo's vault is still templates "
        f"({names}).\n"
        "Every phase loads those files, so building against them produces the "
        "generic work the vault exists to prevent.\n\n"
        "Run the setup skill to draft them from this repo, or "
        "`pingu setup-decline` to record that you are skipping it — either way "
        "this stops asking.",
        file=sys.stderr,
    )
    return 2


def cmd_setup_decline(vault):
    if not vault.is_dir():
        print(f"no vault at {vault}", file=sys.stderr)
        return 1
    marker = vault / SETUP_DECLINED
    marker.write_text(
        f"Setup was declined on {date.today().isoformat()}.\n\n"
        "The standards, context index and glossary are still templates, so the "
        "loop runs on generic defaults. Delete this file to be asked again.\n",
        encoding="utf-8",
    )
    print(f"recorded: {marker}")
    print("the loop will not raise setup again in this repo")
    return 0


# ---------------------------------------------------------------------- next-id

RESERVED_DIR = ".ids"


def _reservations(vault):
    """The directory of claimed-but-not-yet-written IDs.

    Local only. A reservation means nothing in someone else's clone and would
    conflict on every merge if it were tracked, so the vault ignores it. Written
    on demand rather than by vault_init, so vaults scaffolded before this existed
    heal themselves on first use.
    """
    path = vault / RESERVED_DIR
    path.mkdir(parents=True, exist_ok=True)
    ignore = vault / ".gitignore"
    try:
        current = ignore.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if RESERVED_DIR not in current:
        prefix = "" if not current or current.endswith("\n") else "\n"
        body = (f"{current}{prefix}# ID reservations — a local mutex, not shared state\n"
                f"{RESERVED_DIR}/\n")
        # O_NOFOLLOW: `write_text` follows a symlink, and a PR branch can commit
        # both the settings naming a vault_dir and a symlinked .gitignore inside
        # it. The text appended is fixed, so this is file corruption rather than
        # execution — but it should not write through a link at all.
        #
        # POSIX-only. Reading it unguarded raised AttributeError on Windows
        # before anything else ran, and CI is Linux-only so nothing caught it.
        # Degrade rather than crash: a platform without the flag loses this one
        # protection and keeps a working allocator.
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(str(ignore), os.O_CREAT | os.O_WRONLY | os.O_TRUNC | nofollow, 0o644)
        except OSError:
            pass  # A symlink, or an unwritable vault. Reservations still work.
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
    return path


def ids_on_disk(vault, prefix):
    """Every ID of this type a note currently claims, read fresh.

    Reads the notes rather than matching filenames: the convention is
    `<ID>-<slug>.md`, but nothing enforces it at write time, and a hand-written
    note is exactly the one whose ID a globbing check would miss.
    """
    found = set()
    for note in load_notes(vault):
        nid = note.get("id") or ""
        if re.fullmatch(rf"{prefix}-\d+", nid):
            found.add(nid)
    return found


def allocate_id(vault, kind, attempts=1000):
    """Claim the next free ID for `kind`, atomically.

    `next_id` used to read the highest ID and return max+1, which is precisely
    the "two agents both guess the same number" failure the vault skill warns
    about — eight concurrent `pingu new task` calls produced two pairs of
    duplicates. O_EXCL is the fix: whoever creates the marker file owns the ID,
    and the loser of the race walks forward to the next one.

    Winning the marker is not sufficient on its own, which is what the first
    version got wrong. Markers are pruned once their note exists, to keep the
    directory bounded — and a marker is the only evidence a concurrent caller
    holding a stale `load_notes()` snapshot has that an ID is gone. Pruning let
    that caller recompute a low high-water mark and re-claim a live ID: 1 in 30
    trials of sixteen concurrent `pingu new task`. So a claim is confirmed
    against a *fresh* read of the notes before it is handed out. That is the
    load-bearing step; pruning is safe only because of it.

    This is a mutex within one working tree, which is the case the design
    encourages by running agents in parallel. Two people in separate clones can
    still land on the same ID; git shows both files and `pingu doctor` reports
    the duplicate.
    """
    prefix, _, pad = TYPES[kind]
    reserved = _reservations(vault)

    taken = set()
    for note in load_notes(vault):
        match = re.fullmatch(rf"{prefix}-(\d+)", note.get("id") or "")
        if match:
            taken.add(int(match.group(1)))

    highest = max(taken) if taken else 0
    for marker in reserved.iterdir():
        match = re.fullmatch(rf"{prefix}-(\d+)", marker.name)
        if not match:
            continue
        # Safe to prune a reservation whose note exists, but only because the
        # confirm step below re-reads the notes. Pruning alone reopened the race
        # this closes: the marker is the evidence a stale caller relies on.
        if int(match.group(1)) in taken:
            try:
                marker.unlink()
            except OSError:
                pass
            continue
        highest = max(highest, int(match.group(1)))

    number = highest + 1
    for _ in range(attempts):
        nid = f"{prefix}-{number:0{pad}d}"
        try:
            os.close(os.open(str(reserved / nid), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
        except FileExistsError:
            number += 1
            continue
        except OSError:
            # An unwritable vault should not silently hand out a colliding ID.
            raise
        if nid not in ids_on_disk(vault, prefix):
            return nid
        number += 1
    raise RuntimeError(f"could not allocate a {kind} ID after {attempts} attempts")


# Kept as the name the rest of the code and the docs use.
next_id = allocate_id


def cmd_next_id(vault, kind):
    print(allocate_id(vault, kind))
    return 0


# -------------------------------------------------------------------------- new

def yaml_quoted(value):
    """A free-text value as a YAML double-quoted scalar.

    Always quoted, never conditionally. A predicate deciding *when* to quote is
    one missed indicator character away from the bug this exists to fix, and the
    two that actually bit were unremarkable: `Fix: login bug` makes the note
    unparseable, and `#caching` is silently truncated to nothing by a YAML
    comment. The second is worse — an error gets noticed.

    Newlines collapse to spaces. A title is one line by construction, and a
    stray one would otherwise end the frontmatter block early.
    """
    text = " ".join(str(value).split())
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    # C0 control characters are rejected outright by a real YAML parser, which
    # is the same "pingu writes it, Obsidian drops it" failure this exists to
    # prevent. An escape sequence in a title is unremarkable in a terminal.
    text = "".join(c if c >= " " or c == "\t" else "\\x%02x" % ord(c) for c in text)
    return '"' + text + '"'


def yaml_scalar(value):
    """A frontmatter value as Python: the inverse of `yaml_quoted`, or None.

    Quoting decides whether `null` is nil or the four-letter word — YAML says a
    quoted scalar is always a string, and a task genuinely titled "null" should
    not read back as an absent title.
    """
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return re.sub(r"\\(.)", r"\1", text[1:-1])
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    # Unbalanced quotes: the old lenient behaviour, kept for notes written by
    # hand and for anyone editing frontmatter in Obsidian.
    text = text.strip('"').strip("'")
    return None if text in ("", "null", "~") else text


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

# {heading}

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
        # Two slots, two encodings: the frontmatter value is YAML and must be
        # quoted, the H1 below it is plain markdown and must not be.
        TEMPLATE.format(
            kind=kind, nid=nid, title=yaml_quoted(title), heading=title,
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

    warnings = hook_environment_warnings()

    if not problems:
        print(f"vault ok — {len(notes)} notes, no problems found")
        for w in warnings:
            print(f"  warning: {w}")
        return 0
    for p in problems:
        print(f"  {p}")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"\n{len(problems)} problem(s) across {len(notes)} notes")
    return 1


def hook_environment_warnings():
    """What would stop the two hooks working on this machine.

    Warnings, never problems: `doctor`'s exit code is about the vault, and a
    developer running it at all has a working Python by construction. The point
    is the *other* machine — see
    ADR-0005-hook-invocation-resolves-one-interpreter-and-fail, which closes the
    guard's fail-open everywhere a POSIX shell exists and records that it cannot
    be closed where one does not. This is how that hole is made visible on
    purpose instead of by noticing a missing line at session start.
    """
    out = []
    names = hook_interpreter_names()
    if not names:
        out.append("could not read the hook interpreters from hooks.json, so "
                   "whether the hooks can run here is unknown")
        return out

    found_name, found_path = hook_interpreter()
    if found_name is None:
        out.append(f"none of {', '.join(names)} is on PATH — the SessionStart "
                   "hook cannot report lane or phase, and the PreToolUse setup "
                   "guard will refuse every edit until one is installed")
    if shutil.which("sh") is None and shutil.which("bash") is None:
        out.append("no POSIX shell (sh or bash) on PATH — the setup guard "
                   "cannot fail closed here, so a missing interpreter would "
                   "allow edits rather than refuse them")
    return out


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
    quiet = "--quiet" in argv
    argv = [a for a in argv if a not in ("--execute", "--quiet")]
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd, vault = argv[1], vault_path()

    if cmd == "gate":
        return cmd_gate(vault, argv[2] if len(argv) > 2 else None, execute)
    if cmd == "status":
        return cmd_status(vault, quiet)
    if cmd == "doctor":
        return cmd_doctor(vault)
    if cmd == "guard":
        return cmd_guard(vault)
    if cmd == "setup-decline":
        return cmd_setup_decline(vault)
    if cmd == "vault-path":
        # vault_init.sh asks this rather than resolving vault_dir itself, so the
        # scaffolder and the tooling cannot end up pointed at different
        # directories — a failure that looks like an empty vault, not an error.
        print(vault)
        return 0
    if cmd == "next-id":
        if len(argv) < 3 or argv[2] not in TYPES:
            print(f"usage: pingu next-id <{'|'.join(TYPES)}>", file=sys.stderr)
            return 1
        return cmd_next_id(vault, argv[2])
    if cmd == "new":
        if len(argv) < 4 or argv[2] not in TYPES:
            print(f"usage: pingu new <{'|'.join(TYPES)}> <title>", file=sys.stderr)
            return 1
        return cmd_new(vault, argv[2], " ".join(argv[3:]))

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
