"""Regressions for what the four review agents found.

The verify phase ran for the first time against commits 941ecd5..1b661c1 and
returned three blocking findings, all reproduced here before being fixed. Two
were defects introduced by the very commits that set out to remove that class of
defect, which is the argument for the phase existing.
"""

import json
import subprocess
import sys

import pytest
import yaml

import pingu
from conftest import NEEDS_O_NOFOLLOW, PLUGIN_ROOT, set_home


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
    home = tmp_path / "home"
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
    home = tmp_path / "home2"
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


def test_the_symlink_guard_is_still_applied_where_it_exists(vault, tmp_path):
    """The fallback must not quietly disable the protection on platforms that
    do support it."""
    target = tmp_path / "victim.txt"
    target.write_text("SECRET=hunter2\n", encoding="utf-8")
    (vault / ".gitignore").symlink_to(target)

    pingu.allocate_id(vault, "task")
    assert target.read_text(encoding="utf-8") == "SECRET=hunter2\n"
