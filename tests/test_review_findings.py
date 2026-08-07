"""Regressions for what the four review agents found.

The verify phase ran for the first time against commits 941ecd5..1b661c1 and
returned three blocking findings, all reproduced here before being fixed. Two
were defects introduced by the very commits that set out to remove that class of
defect, which is the argument for the phase existing.
"""

import json
import pathlib
import shutil
import subprocess
import sys

import pytest
import yaml

import pingu
from conftest import BASH, NEEDS_O_NOFOLLOW, PLUGIN_ROOT, set_home


def note_at(capsys):
    import pathlib
    return pathlib.Path(capsys.readouterr().out.strip())


# ------------------------------------------------- the heading is not YAML

@pytest.mark.parametrize("title", [
    "Rate limiting: the search endpoint",
    'Use "Redis" for #caching',
    "plain title",
])
def test_the_note_heading_is_plain_markdown(vault, title, capsys):
    """`TEMPLATE` uses `{title}` twice — the frontmatter value and the body's H1.
    Quoting for YAML fed both, so every note created since gained literal quote
    marks in its heading. The new frontmatter suite could not see it: every
    assertion read `parsed(path)["title"]`, never the body.
    """
    pingu.cmd_new(vault, "task", title)
    body = note_at(capsys).read_text(encoding="utf-8")
    heading = [l for l in body.splitlines() if l.startswith("# ")][0]
    assert heading == f"# {title}", "the YAML quoting leaked into the markdown heading"


# ------------------------------------------- a stale scan cannot reuse an ID

def test_a_stale_scan_cannot_reclaim_an_id_a_note_already_holds(vault, monkeypatch):
    """The race the O_EXCL marker did not close.

    Pruning a spent marker destroys the only record a concurrent caller with a
    stale `load_notes()` snapshot could have seen, so that caller recomputes a
    low high-water mark and O_EXCL happily grants it an ID a note already holds.
    Measured at 1 in 30 trials of sixteen concurrent `pingu new task`.

    Simulated deterministically here rather than by hammering: hand `allocate_id`
    a scan that predates the notes on disk, which is exactly what losing that
    race looks like from inside.
    """
    for n in range(1, 6):
        (vault / "tasks" / f"T-{n:04d}-x.md").write_text(
            f"---\ntype: task\nid: T-{n:04d}\n---\n", encoding="utf-8")

    # Only the *first* read is stale. That is what losing the race looks like:
    # the peers' notes landed after this caller's scan and before its claim.
    # Stubbing every read instead would model a caller that never looks again,
    # which no amount of re-reading could defend against.
    real = pingu.load_notes
    calls = {"n": 0}

    def stale_first(v):
        calls["n"] += 1
        return [] if calls["n"] == 1 else real(v)

    monkeypatch.setattr(pingu, "load_notes", stale_first)
    assert pingu.allocate_id(vault, "task") == "T-0006"


def test_allocation_skips_an_id_whose_note_exists_without_a_marker(vault):
    """Markers are local and disposable — a fresh clone or a `git clean` leaves
    notes with no reservations behind them. The claim must still not collide."""
    (vault / "tasks" / "T-0001-x.md").write_text(
        "---\ntype: task\nid: T-0001\n---\n", encoding="utf-8")
    (vault / pingu.RESERVED_DIR).mkdir(parents=True, exist_ok=True)
    assert pingu.allocate_id(vault, "task") != "T-0001"


def test_the_confirm_step_reads_notes_rather_than_matching_filenames(vault, monkeypatch):
    """`<ID>-<slug>.md` is a convention, not something enforced at write time,
    and a hand-written note is exactly the one a filename glob would miss."""
    (vault / "tasks" / "some-hand-written-note.md").write_text(
        "---\ntype: task\nid: T-0001\ntitle: written by hand\n---\n", encoding="utf-8")
    (vault / pingu.RESERVED_DIR).mkdir(parents=True, exist_ok=True)

    real = pingu.load_notes
    calls = {"n": 0}

    def stale_first(v):
        calls["n"] += 1
        return [] if calls["n"] == 1 else real(v)

    monkeypatch.setattr(pingu, "load_notes", stale_first)
    assert pingu.allocate_id(vault, "task") != "T-0001"


# ------------------------------------------- the vault stays inside the repo

@pytest.mark.parametrize("escape", [
    "/etc",
    "../../../../tmp",
    "docs/../../outside",
    "/",
])
def test_a_vault_dir_outside_the_repo_is_refused(repo, monkeypatch, escape, capsys):
    """`repo_root() / value` discards the base entirely when the value is
    absolute, and nothing rejected `..`. A contributor's PR can commit
    `.claude/settings.json`; checking that branch out is enough, because the
    SessionStart hook runs `pingu status` unprompted. With `vault_dir: "/"` that
    walks and reads every markdown file on the machine.

    plugin.json already documents the option as "relative to the repo root".
    """
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu@skills-dir": {"options": {"vault_dir": escape}}}}),
        encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_VAULT_DIR", raising=False)

    assert pingu.vault_path() == repo / "docs" / "vault"
    assert "outside the repo" in capsys.readouterr().err


def test_a_vault_dir_inside_the_repo_is_honoured(repo, monkeypatch):
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu@skills-dir": {"options": {"vault_dir": "docs/knowledge"}}}}),
        encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_VAULT_DIR", raising=False)
    assert pingu.vault_path() == repo / "docs" / "knowledge"


@NEEDS_O_NOFOLLOW
def test_the_gitignore_write_does_not_follow_a_symlink(vault, tmp_path):
    """Both halves of this are committable to one PR branch: the settings file
    naming a vault_dir, and a symlinked .gitignore inside it. The appended text
    is fixed, so it is a file-corruption primitive, not code execution — but it
    writes wherever the link points."""
    target = tmp_path / "victim.txt"
    target.write_text("SECRET=hunter2\n", encoding="utf-8")
    (vault / ".gitignore").symlink_to(target)

    pingu.allocate_id(vault, "task")
    assert target.read_text(encoding="utf-8") == "SECRET=hunter2\n"


# ------------------------------------------------------- control characters

@pytest.mark.parametrize("title", ["esc\x1b[31mred", "bell\x07here", "nul\x00byte"])
def test_a_control_character_in_a_title_still_yields_valid_yaml(vault, title, capsys):
    """The same failure class 99cb2cc set out to eliminate: a note pingu writes
    and reads happily that a real parser rejects. Not attacker-driven — a title
    arrives from a developer or an agent — the commit's claim was just
    incomplete."""
    pingu.cmd_new(vault, "task", title)
    text = note_at(capsys).read_text(encoding="utf-8")
    yaml.safe_load(text[3:text.find("\n---", 3)])


# --------------------------------------------------- autonomy is a floor

def test_a_repo_cannot_loosen_the_autonomy_a_user_asked_for(repo, tmp_path, monkeypatch):
    """MANUAL tells teams to commit `<repo>/.claude/settings.json`, and repo
    settings outrank the user's own. So a PR branch could return someone who
    chose `gated` to `full-loop`, removing the per-phase stop they asked for.
    A repo may tighten autonomy; it may not loosen it."""
    home = tmp_path.parent / (tmp_path.name + "-home")
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu@skills-dir": {"options": {"autonomy": "gated"}}}}),
        encoding="utf-8")
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu@skills-dir": {"options": {"autonomy": "full-loop"}}}}),
        encoding="utf-8")
    set_home(monkeypatch, home)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_AUTONOMY", raising=False)

    assert pingu.autonomy()[0] == "gated"


def test_a_repo_may_tighten_autonomy(repo, tmp_path, monkeypatch):
    home = tmp_path.parent / (tmp_path.name + "-home2")
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu@skills-dir": {"options": {"autonomy": "full-loop"}}}}),
        encoding="utf-8")
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu@skills-dir": {"options": {"autonomy": "gated"}}}}),
        encoding="utf-8")
    set_home(monkeypatch, home)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_AUTONOMY", raising=False)

    assert pingu.autonomy()[0] == "gated"


# ------------------------------------------------------- runs where Python does

def test_reservations_work_without_o_nofollow(vault, monkeypatch):
    """`os.O_NOFOLLOW` is POSIX-only — it does not exist on Windows, where the
    plain attribute access would raise AttributeError before anything else ran.
    CI is Linux-only, so nothing here would have caught it.

    The symlink hardening degrades rather than crashing: a platform without the
    flag loses that one protection and keeps a working allocator.
    """
    monkeypatch.delattr("os.O_NOFOLLOW", raising=False)
    assert pingu.allocate_id(vault, "task") == "T-0001"
    assert (vault / ".gitignore").is_file()


@NEEDS_O_NOFOLLOW
def test_the_symlink_guard_is_still_applied_where_it_exists(vault, tmp_path):
    """The fallback must not quietly disable the protection on platforms that
    do support it.

    "Where it exists" is the whole point of this test and it had no skip, so on
    Windows it asserted the opposite of what it is named for. The pair matters:
    its sibling above proves the allocator survives without the flag, and this
    one proves that survival was not bought by dropping the protection where the
    flag is present. Skipping by capability keeps both halves honest — the
    Windows runner genuinely does create the symlink, so this is a real absence
    of protection, not an untestable one.
    """
    target = tmp_path / "victim.txt"
    target.write_text("SECRET=hunter2\n", encoding="utf-8")
    (vault / ".gitignore").symlink_to(target)

    pingu.allocate_id(vault, "task")
    assert target.read_text(encoding="utf-8") == "SECRET=hunter2\n"


# --------------------------------------- T-0005: the personal file is not a given
#
# ADR-0004 rule 2 calls `~/.claude/settings.json` the trusted source and lets it
# set a floor a repo may not loosen. Nothing established that `~` was trustworthy,
# and the security reviewer who raised it refused to assert either way because
# this repo had already produced three confident, well-sourced, wrong predictions
# about environment mechanisms in one day.
#
# Settled 2026-08-08 by running it, in two parts so a negative could not be
# ambiguous:
#
#   1. Does the `env` key of a *repo-committed* `.claude/settings.json` reach hook
#      subprocesses at all? A sentinel variable came through a real `claude -p`
#      session. **Yes.** Without this step, "the personal file was not found"
#      could not be told apart from "env never propagated".
#   2. Given that, what can the repo do to the floor? Three bypasses, below.
#
# So `HOME` is an input the *less* trusted party controls. Each case below failed
# before the fix, with the repo's own declaration winning.

def _floor(repo, home, monkeypatch, home_value=None):
    """A personal `gated` and a repo `full-loop`. Returns the level that wins."""
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu": {"options": {"autonomy": "gated"}}}}),
        encoding="utf-8")
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu": {"options": {"autonomy": "full-loop"}}}}),
        encoding="utf-8")
    set_home(monkeypatch, home if home_value is None else home_value)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_AUTONOMY", raising=False)
    return pingu.autonomy()[0]


def test_an_empty_home_cannot_make_the_repo_its_own_personal_settings(repo, tmp_path, monkeypatch):
    """`HOME=""` makes `Path.home()` return `Path(".")` on 3.9 — measured, and
    3.9 is in the CI matrix. The "personal" file then resolves relative to the
    cwd, which for a hook is the checkout. The repo is read as the user's own
    choice: not the floor removed, the floor **forged**.

    3.13 returns `/` instead, so this is version-dependent — which is exactly why
    it must be pinned rather than reasoned about, and why the assertion is about
    the path never landing in the repo rather than about any one interpreter.
    """
    home = tmp_path.parent / (tmp_path.name + "-empty-home")
    home.mkdir(exist_ok=True)

    assert _floor(repo, home, monkeypatch, home_value="") == "gated", (
        "a repo-committed HOME='' let the repo override the user's gated choice")
    for path in pingu.settings_files("user"):
        assert repo not in pathlib.Path(path).resolve().parents, (
            f"the personal settings file resolved inside the repo: {path}")


def test_a_home_pointing_at_the_checkout_cannot_forge_the_personal_file(repo, tmp_path, monkeypatch):
    """The same forgery with an absolute path, and so on *every* Python rather
    than only 3.9. This is the one that does not need a version quirk, and it is
    the reason the rule is about where the path lands, not about whether
    `Path.home()` happened to raise."""
    home = tmp_path.parent / (tmp_path.name + "-checkout-home")
    home.mkdir(exist_ok=True)

    assert _floor(repo, home, monkeypatch, home_value=repo) == "gated", (
        "a repo-committed HOME=<the checkout> let the repo forge the personal floor")


def test_a_missing_home_is_reported_rather_than_silently_dropping_the_floor(repo, tmp_path, monkeypatch, capsys):
    """The third bypass, and it was the quiet one: absolute and outside the repo,
    so indistinguishable from a user who never wrote a settings file.

    It cannot be closed — there is no way to recover the real home once `HOME` is
    overwritten — so the floor is genuinely absent here. What is fixed is the
    silence: `status` now says the personal file is being ignored and why. An
    unreported bypass is the thing being fixed, not the dropped setting.
    """
    home = tmp_path.parent / (tmp_path.name + "-missing-home")
    home.mkdir(exist_ok=True)
    missing = tmp_path.parent / (tmp_path.name + "-does-not-exist")

    level = _floor(repo, home, monkeypatch, home_value=missing)

    # The level, which this test used to discard. It must stay `full-loop`:
    # ADR-0004 is explicit that a machine with no home *loses* the floor rather
    # than being forced to the tightest setting, because that case fires for
    # containers and CI. Asserting only "a problem was reported" passed whether
    # this branch was classed as tampering or not, and classing it as tampering
    # would silently gate every container in the world.
    assert level == "full-loop", (
        "a missing home was treated as tampering and forced gated; ADR-0004 says "
        "this case degrades rather than tightens")

    _, problem = pingu.personal_settings_file()
    assert problem, "a home that does not exist was accepted silently"
    assert not problem.tampering, (
        "a missing home was classed as tampering, which forces gated on every "
        "container and CI box")

    pingu.main(["pingu.py", "status"])
    out = capsys.readouterr().out
    assert "being ignored entirely" in out, (
        f"status did not report that personal settings were dropped:\n{out}")


def test_a_real_home_outside_the_repo_still_sets_the_floor(repo, tmp_path, monkeypatch):
    """The other direction, and the reason the three above are not vacuous.

    Every one of them would pass if `settings_files('user')` simply returned
    nothing always — the floor would be unforgeable because it would never exist.
    This pins that the ordinary case still works.
    """
    home = tmp_path.parent / (tmp_path.name + "-real-home")
    home.mkdir(exist_ok=True)

    assert _floor(repo, home, monkeypatch) == "gated", (
        "the personal floor stopped working for an ordinary home")


# ------------------------------------------- T-0008: the hooks' environment, checked

def test_doctor_is_quiet_about_the_environment_on_a_healthy_machine(vault, capsys):
    """The half that stops the warnings being noise.

    A developer running `doctor` has a working Python by construction, so if this
    ever warns here it is warning wrongly — and a check that cries wolf is one
    people stop reading, which is worse than not having it.
    """
    assert pingu.hook_environment_warnings() == []


def test_doctor_warns_when_no_hook_interpreter_resolves(monkeypatch):
    """The hole ADR-0005 could not close, made visible on purpose.

    Where no POSIX shell exists the guard cannot fail closed, and the only other
    signal is *noticing an absent* `[pingu]` line at session start — useless to
    anyone who has never seen it present.
    """
    monkeypatch.setattr(pingu.shutil, "which", lambda name: None)
    warnings = pingu.hook_environment_warnings()

    assert any("on PATH" in w for w in warnings), warnings
    assert any("fail closed" in w for w in warnings), (
        f"no warning about the guard being unable to fail closed: {warnings}")


def test_doctor_reads_the_interpreters_from_hooks_json_rather_than_restating_them(tmp_path):
    """ADR-0001's rule, applied to this check.

    A hard-coded ("python3", "python") here would agree with hooks.json right up
    until someone edited one of them, and then `doctor` would confidently report
    on an interpreter the hooks no longer use.
    """
    fake = tmp_path / "hooks.json"
    fake.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
        {"command": 'PY="$(command -v pypy9 || command -v tclsh)"; exec "$PY" x.py'}]}]}}),
        encoding="utf-8")

    assert pingu.hook_interpreter_names(fake) == ("pypy9", "tclsh")


def test_the_interpreter_names_survive_a_hooks_file_that_cannot_be_read(tmp_path):
    """`doctor` must not raise on a malformed hooks.json — and must not then
    claim the environment is fine either. Empty names produce the "unknown"
    warning rather than silence."""
    broken = tmp_path / "hooks.json"
    broken.write_text("{not json", encoding="utf-8")

    assert pingu.hook_interpreter_names(broken) == ()


def test_vault_init_says_so_when_it_could_not_read_a_configured_vault_dir(tmp_path):
    """T-0004's quietest bullet, and it was nearly shipped unmet.

    `vault_init.sh` probed `pingu vault-path` with `2>/dev/null || true`, which
    collapsed two different outcomes into one empty string: "pingu answered, and
    nothing is configured" — where defaulting to `docs/vault` is correct — and
    "pingu never ran", where defaulting is a guess. In the second case a
    configured `vault_dir` goes unread and the vault is scaffolded somewhere the
    tooling will not look. That presents as an empty vault, not as an error.

    A spec reviewer caught this after the task had already been marked done.
    """
    import os
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    shell_only = tmp_path / "shell-only"
    shell_only.mkdir()
    for tool in ("git", "date", "basename", "dirname", "mkdir", "cat", "sed"):
        found = shutil.which(tool)
        if found:
            (shell_only / tool).symlink_to(found)

    # The shell is resolved absolutely so it can still be spawned; the *child's*
    # PATH stays doctored, which is what puts python out of reach. Resolving bash
    # against the doctored PATH instead would fail to spawn at all, and the test
    # would go red for a reason that has nothing to do with the interpreter.
    result = subprocess.run(
        [shutil.which(BASH) or BASH, str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=repo, capture_output=True, text=True,
        env=dict(os.environ, PATH=str(shell_only)),
    )

    assert "needs python3 on PATH" in result.stderr, (
        "vault_init.sh fell back to the default vault without saying it had "
        f"never read the configured one\n--- stderr ---\n{result.stderr}")


def test_a_case_varied_home_cannot_forge_the_personal_file(repo, tmp_path, monkeypatch):
    """The third forgery vector, found by a reviewer rather than by the tests.

    `os.path.realpath` resolves symlinks but does not canonicalise case, and this
    ships on APFS and NTFS — both case-insensitive, both in the CI matrix. So
    `HOME=/Repo/Path` and `HOME=/repo/path` name one directory on disk and two
    different strings, and the string comparison guarding the boundary said "not
    inside the repo" for a home that plainly was.

    Skipped where the filesystem is genuinely case-sensitive, because there the
    two paths really are different directories and there is nothing to catch.
    """
    swapped = pathlib.Path(str(repo).swapcase())
    if str(swapped) == str(repo) or not swapped.is_dir():
        pytest.skip("this filesystem is case-sensitive, so there is no case bypass")

    assert _floor(repo, repo, monkeypatch, home_value=swapped) == "gated", (
        "a case-varied HOME pointing at the checkout forged the personal floor")
    _, problem = pingu.personal_settings_file()
    assert problem is not None and problem.tampering, (
        "a case-varied home inside the repo was not recognised as tampering")


def test_the_interpreter_names_survive_a_hooks_file_that_is_not_an_object(tmp_path):
    """Valid JSON, wrong shape. `data.get` on a list raises AttributeError out of
    a function whose contract is to answer or return empty."""
    odd = tmp_path / "hooks.json"
    odd.write_text("[]", encoding="utf-8")

    assert pingu.hook_interpreter_names(odd) == ()


def test_the_option_env_var_cannot_forge_the_personal_floor(repo, tmp_path, monkeypatch):
    """The total bypass that walked past everything else in this file.

    `plugin_option` short-circuits on `CLAUDE_PLUGIN_OPTION_<KEY>` before it ever
    opens a file. `autonomy()` reads the floor with `scope="user"`, so that
    short-circuit made the floor read return the *attacker's* string: full-loop
    compared against full-loop, floor never fires. And the environment is exactly
    what a committed `.claude/settings.json` controls, via the `env` key that
    T-0005 measured as reaching hook subprocesses.

    So every control added for ADR-0004 rule 2 was bypassable with one line of
    committed JSON, without entering any of the branches they guard. Found by the
    security reviewer with a repro, after the rest of this work was finished.

    The env var stays honoured for ordinary lookups — `vault_init.sh` passes one
    deliberately — which is why the fix is scoped rather than a deletion, and why
    the second half of this test matters as much as the first.
    """
    home = tmp_path.parent / (tmp_path.name + "-optenv-home")
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu": {"options": {"autonomy": "gated"}}}}),
        encoding="utf-8")
    set_home(monkeypatch, home)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_AUTONOMY", "full-loop")

    assert pingu.autonomy()[0] == "gated", (
        "CLAUDE_PLUGIN_OPTION_AUTONOMY overrode the personal floor it is supposed "
        "to be subordinate to")

    # The other half: the short-circuit still works where it is not a bypass.
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_VAULT_DIR", "docs/knowledge")
    assert pingu.vault_path() == repo / "docs" / "knowledge", (
        "the fix went too far and broke the deliberate vault_init.sh channel")


@pytest.mark.parametrize("missing, expected", [
    ("python", "on PATH"),
    ("shell", "fail closed"),
    # Exactly one shell present. `and` is deliberate — either shell is enough to
    # run the hook, so this must NOT warn. Without this case the test cannot tell
    # `and` from `or`: with both shells present or both absent the two operators
    # agree, so a mutation to `or` sailed straight through the first two rows.
    ("bash-only", None),
    ("sh-only", None),
])
def test_the_two_hook_environment_warnings_fire_independently(monkeypatch, missing, expected):
    """Each condition on its own, because the pair was only ever tested together.

    `test_doctor_warns_when_no_hook_interpreter_resolves` patches `shutil.which`
    to return None for everything, which cannot tell `and` from `or` in the shell
    check, and cannot tell either warning from a version that emits both
    whenever anything is missing. A machine with bash but no Python is a real
    configuration — it is the one the whole ADR is about.
    """
    interpreters = set(pingu.hook_interpreter_names())
    real = shutil.which

    def fake(name, *args, **kwargs):
        if missing == "python" and name in interpreters:
            return None
        if missing == "shell" and name in ("sh", "bash"):
            return None
        if missing == "bash-only" and name == "sh":
            return None
        if missing == "sh-only" and name == "bash":
            return None
        return real(name, *args, **kwargs) or "/usr/bin/" + name

    monkeypatch.setattr(pingu.shutil, "which", fake)
    warnings = pingu.hook_environment_warnings()

    if expected is None:
        assert warnings == [], (
            f"one shell is missing but the other is present, which is a working "
            f"machine — it must not warn: {warnings}")
        return
    assert any(expected in w for w in warnings), (
        f"with only {missing} missing, expected a warning containing {expected!r}, "
        f"got {warnings}")
    assert len(warnings) == 1, (
        f"only {missing} is missing, so exactly one warning is right: {warnings}")
