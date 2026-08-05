"""The setup gate, enforced rather than requested.

`start/SKILL.md` says to stop and offer setup when the vault is still templates,
even on full-loop. Two headless runs against near-identical repos did opposite
things: one stopped and reported the gate blocked, the other spent ten minutes
implementing the feature against template standards. Neither run was wrong about
the instruction — the instruction is just advice, and advice holds most of the
time, which is the worst failure rate to debug.

This repo's own argument against that is on the README: the model is "the one
party that can't answer" whether it met its own gate. The setup gate was exactly
that. A PreToolUse hook makes it a fact instead.
"""

import json
import subprocess
import sys

import pytest

import pingu
from conftest import PLUGIN_ROOT

WRITE = {"hook_event_name": "PreToolUse", "tool_name": "Write",
         "tool_input": {"file_path": "search/api.py", "content": "x"}}


def guard(repo, payload):
    """Run the guard exactly as the hook does: JSON on stdin, exit code out."""
    result = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "pingu.py"), "guard"],
        input=json.dumps(payload), capture_output=True, text=True, cwd=repo,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "CLAUDE_PROJECT_DIR": str(repo)},
    )
    return result


def fill_in(vault):
    for path in vault.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "status: template" in text:
            path.write_text(text.replace("status: template", "status: ready"), encoding="utf-8")


# --------------------------------------------------------------- when it blocks

def test_a_write_is_blocked_while_the_vault_is_templates(repo):
    result = guard(repo, WRITE)
    assert result.returncode == 2, result.stdout
    assert "setup" in result.stderr.lower()
    assert "context.md" in result.stderr, "the reason should name what is unfilled"


def test_the_block_says_how_to_get_past_it(repo):
    """A guard that stops you without saying what to do is just an outage."""
    stderr = guard(repo, WRITE).stderr
    assert "decline" in stderr, "no escape hatch offered"


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
def test_every_editing_tool_is_covered(repo, tool):
    payload = dict(WRITE, tool_name=tool)
    assert guard(repo, payload).returncode == 2


# --------------------------------------------------------------- when it allows

def test_setup_can_still_write_the_vault_it_is_filling_in(repo, vault):
    """Without this the guard deadlocks: setup cannot fix the thing that is
    blocking setup."""
    payload = dict(WRITE, tool_input={"file_path": str(vault / "context.md")})
    assert guard(repo, payload).returncode == 0


def test_a_filled_in_vault_does_not_block(repo, vault):
    fill_in(vault)
    assert guard(repo, WRITE).returncode == 0


def test_a_repo_with_no_vault_is_none_of_our_business(tmp_path):
    """The plugin loads in every project. Blocking writes in repos that never
    asked for a vault would be indefensible."""
    plain = tmp_path / "plain"
    plain.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=plain, check=True)
    assert guard(plain, WRITE).returncode == 0


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "Bash", "Task"])
def test_reading_is_never_blocked(repo, tool):
    """Setup works by reading the repo. Blocking that would defeat the point."""
    assert guard(repo, dict(WRITE, tool_name=tool)).returncode == 0


# ------------------------------------------------------------- the escape hatch

def test_declining_setup_unblocks_writing(repo, vault):
    """Their call, and the loop is documented as not nagging twice."""
    subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "pingu.py"), "setup-decline"],
        cwd=repo, capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "CLAUDE_PROJECT_DIR": str(repo)},
    )
    assert guard(repo, WRITE).returncode == 0


def test_the_decision_is_recorded_where_the_team_can_see_it(repo, vault):
    subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "pingu.py"), "setup-decline"],
        cwd=repo, capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "CLAUDE_PROJECT_DIR": str(repo)},
    )
    marker = vault / pingu.SETUP_DECLINED
    assert marker.is_file(), "declining left no trace"
    assert "setup" in marker.read_text(encoding="utf-8").lower()


# ------------------------------------------------------------- it must not bite

def test_a_malformed_payload_fails_open(repo):
    """This runs in front of every edit in every project. A guard that crashes
    closed would make the plugin unusable; one that crashes open only loses the
    protection it was adding."""
    result = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "pingu.py"), "guard"],
        input="not json at all", capture_output=True, text=True, cwd=repo,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "CLAUDE_PROJECT_DIR": str(repo)},
    )
    assert result.returncode == 0


def test_no_payload_at_all_fails_open(repo):
    result = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "pingu.py"), "guard"],
        input="", capture_output=True, text=True, cwd=repo,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "CLAUDE_PROJECT_DIR": str(repo)},
    )
    assert result.returncode == 0


# ------------------------------------------------------------------- it is wired

def test_the_hook_is_declared():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entries = hooks["hooks"].get("PreToolUse", [])
    commands = [h["command"] for entry in entries for h in entry["hooks"]]
    assert any("guard" in c for c in commands), "hooks.json does not run the setup guard"
    matchers = [entry.get("matcher", "") for entry in entries]
    assert any("Write" in m and "Edit" in m for m in matchers), (
        "the guard is not matched against the editing tools")


def test_status_stops_nagging_once_setup_is_declined(repo, vault, run_pingu, capsys):
    """The loop is documented as not asking twice. Printing "run the setup skill"
    after someone declined contradicts the decline in front of them, every
    single session."""
    (vault / pingu.SETUP_DECLINED).write_text("declined\n", encoding="utf-8")

    run_pingu("status")
    out = capsys.readouterr().out

    assert "run the setup skill" not in out
    assert "declined" in out.lower(), "status hides the decision entirely"
