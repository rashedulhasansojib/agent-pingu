"""Where the Issues come from, for the commands that write into the vault.

`push` sends note bodies out and has a visibility guard. `pull` runs the other
way: it appends comment bodies verbatim into task notes, and the loop then reads
those notes as authoritative project state. `gh_repo` is resolved from settings,
including `<repo>/.claude/settings.json` — a file a pull request can carry. So a
contributor's branch can aim `pull` at a repository they control and write
whatever they like into the agent's working memory.

The guard mirrors `push`'s: refuse by default, allow with an explicit flag.
"""

import json
import subprocess

import pytest

from conftest import set_home

import gh_sync


@pytest.fixture
def repo_with_remote(repo, monkeypatch):
    import subprocess
    subprocess.run(["git", "remote", "add", "origin",
                    "https://github.com/you/yours.git"], cwd=repo, check=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_GH_REPO", raising=False)
    return repo


def set_gh_repo(repo, value):
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu@skills-dir": {"options": {"gh_repo": value}}}}),
        encoding="utf-8")


# ------------------------------------------------------- reading the remote

@pytest.mark.parametrize("url,expected", [
    ("https://github.com/you/yours.git", "you/yours"),
    ("https://github.com/you/yours", "you/yours"),
    ("git@github.com:you/yours.git", "you/yours"),
    ("ssh://git@github.com/you/yours.git", "you/yours"),
])
def test_the_remote_is_read_in_every_url_form(repo, monkeypatch, url, expected):
    import subprocess
    subprocess.run(["git", "remote", "add", "origin", url], cwd=repo, check=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert gh_sync.git_remote_repo() == expected


def test_no_remote_reads_as_unknown(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert gh_sync.git_remote_repo() is None


def test_the_remote_is_read_from_the_repo_not_from_above_the_vault(tmp_path, monkeypatch):
    """The remote must come from `repo_root()`, never from walking up the vault.

    `git_remote_repo` used to run in `vault_path().parent.parent`, which is the
    repo root only while `vault_dir` is exactly two segments deep. `vault_dir:
    "vault"` is one, and two levels up from it is the *parent of the checkout* —
    so with a repo nested inside another repo, the provenance guard compared
    `gh_repo` against a repository the user never named.

    Reproduced before it was fixed, which is why this builds the nesting rather
    than asserting on a mock: the trap is entirely in the path arithmetic, and a
    fake `git` would have agreed with the bug.
    """
    outer, inner = tmp_path / "outer", tmp_path / "outer" / "checkout"
    inner.mkdir(parents=True)
    for path, url in ((outer, "https://github.com/wrong/outer.git"),
                      (inner, "https://github.com/you/yours.git")):
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=path, check=True)

    settings = inner / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(
        {"pluginConfigs": {"agent-pingu": {"options": {"vault_dir": "vault"}}}}),
        encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(inner))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_VAULT_DIR", raising=False)
    set_home(monkeypatch, tmp_path / "nohome")

    # The arithmetic that was wrong, pinned so the reason this test exists stays
    # legible: two levels up from this vault is genuinely not the checkout.
    assert gh_sync.vault_path() == inner / "vault"
    assert gh_sync.vault_path().parent.parent == outer

    assert gh_sync.git_remote_repo() == "you/yours"


# --------------------------------------------------------------- the guard

def test_pull_refuses_a_repo_that_is_not_this_ones_remote(repo_with_remote, capsys):
    set_gh_repo(repo_with_remote, "attacker/exfil")
    assert gh_sync.cmd_pull(repo_with_remote / "docs" / "vault") == 1
    out = capsys.readouterr().out
    assert "attacker/exfil" in out and "you/yours" in out
    assert "--allow-foreign" in out


def test_pull_proceeds_when_gh_repo_matches_the_remote(repo_with_remote, monkeypatch):
    set_gh_repo(repo_with_remote, "you/yours")
    monkeypatch.setattr(gh_sync, "task_notes", lambda _v: iter(()))
    assert gh_sync.cmd_pull(repo_with_remote / "docs" / "vault") == 0


def test_pull_proceeds_when_no_gh_repo_is_declared(repo_with_remote, monkeypatch):
    """Nothing to disagree with — `gh` uses the remote itself."""
    monkeypatch.setattr(gh_sync, "task_notes", lambda _v: iter(()))
    assert gh_sync.cmd_pull(repo_with_remote / "docs" / "vault") == 0


def test_allow_foreign_is_the_way_through(repo_with_remote, monkeypatch):
    set_gh_repo(repo_with_remote, "acme/other")
    monkeypatch.setattr(gh_sync, "task_notes", lambda _v: iter(()))
    assert gh_sync.cmd_pull(repo_with_remote / "docs" / "vault", allow_foreign=True) == 0


def test_pull_refuses_when_the_remote_cannot_be_determined(repo, monkeypatch, capsys):
    """Same reasoning as push's unknown-visibility branch: guessing wrong here
    writes someone else's text into the notes, and that is not undoable."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_GH_REPO", raising=False)
    set_gh_repo(repo, "acme/other")
    assert gh_sync.cmd_pull(repo / "docs" / "vault") == 1
    out = capsys.readouterr().out
    assert "could not be read" in out and "--allow-foreign" in out


def test_status_is_guarded_too(repo_with_remote, capsys):
    """`status` closes Issues and moves labels in whatever repo it is pointed at."""
    set_gh_repo(repo_with_remote, "attacker/exfil")
    assert gh_sync.cmd_status(repo_with_remote / "docs" / "vault") == 1
    assert "--allow-foreign" in capsys.readouterr().out


def test_the_flag_reaches_the_commands(repo_with_remote, monkeypatch):
    seen = {}
    monkeypatch.setattr(gh_sync, "cmd_pull", lambda v, allow_foreign=False: seen.setdefault("pull", allow_foreign) or 0)
    monkeypatch.setattr(sys_argv_holder(), "argv", ["gh-sync", "pull", "--allow-foreign"])
    gh_sync.main()
    assert seen["pull"] is True


def sys_argv_holder():
    import sys
    return sys


# ------------------------------------------------------- write_field's contract

@pytest.mark.parametrize("value,expected", [
    ("Fix: login bug", "Fix: login bug"),
    ("the #1 thing", "the #1 thing"),
    ('says "hello"', 'says "hello"'),
    ("null", "null"),
])
def test_write_field_quotes_free_text(tmp_path, value, expected):
    """No caller passes prose today — `gh_issue` is a number — which is exactly
    why this needs pinning rather than trusting. An unquoted free-text value here
    is the same unparseable-note bug that the `pingu new` path already fixed, and
    a future caller would reintroduce it silently.
    """
    import yaml
    path = tmp_path / "T-0001-x.md"
    path.write_text("---\ntype: task\nid: T-0001\n---\n\nbody\n", encoding="utf-8")

    gh_sync.write_field(path, "note", value)

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text[3:text.find("\n---", 3)])["note"] == expected


@pytest.mark.parametrize("value", [42, "42", -7])
def test_write_field_leaves_numbers_bare(tmp_path, value):
    """`gh_issue: 42` has to stay a number for Dataview, not become a string."""
    import yaml
    path = tmp_path / "T-0002-x.md"
    path.write_text("---\ntype: task\nid: T-0002\n---\n\nbody\n", encoding="utf-8")

    gh_sync.write_field(path, "gh_issue", value)

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text[3:text.find("\n---", 3)])["gh_issue"] == int(value)
