"""Tests for scripts/pingu.py."""

import pytest

import pingu
from conftest import PLUGIN_ROOT, write_note


# --------------------------------------------------------------- status resilience

def test_status_survives_a_non_integer_blocked_cap(run_pingu, ready_vault, capsys):
    """pingu.py's own docstring promises status degrades rather than crashing the
    SessionStart hook. An unparseable cap must not take the session down."""
    write_note(ready_vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="blocked", work_type="feature", title="wedged")

    assert run_pingu("status", PINGU_STATE_MAX_BLOCKED="none") == 0
    assert "BLOCKED T-0001" in capsys.readouterr().out


def test_status_honours_a_valid_blocked_cap(run_pingu, ready_vault, capsys):
    for n in range(1, 4):
        write_note(ready_vault, f"tasks/T-000{n}-x.md", type="task", id=f"T-000{n}",
                   status="blocked", work_type="bug", title=f"wedged {n}")

    run_pingu("status", PINGU_STATE_MAX_BLOCKED="2")
    out = capsys.readouterr().out
    assert out.count("[pingu] BLOCKED") == 2
    assert "...and 1 more blocked" in out


# ------------------------------------------------------------------ lane inference

def test_chore_lane_starts_at_execute(ready_vault):
    """start/SKILL.md: chore is `execute -> verify`. It has no talk phase."""
    write_note(ready_vault, "tasks/T-0001-bump.md", type="task", id="T-0001",
               status="todo", work_type="chore", title="bump deps")

    phase, _ = pingu.infer_phase(pingu.load_notes(ready_vault))
    assert phase == "execute"


def test_incident_lane_starts_at_diagnose_not_talk(ready_vault):
    """start/SKILL.md: incident is `diagnose -> execute -> verify -> retro`."""
    write_note(ready_vault, "research/R-0001-outage.md", type="research", id="R-0001",
               status="todo", work_type="incident", title="api down")

    phase, _ = pingu.infer_phase(pingu.load_notes(ready_vault))
    assert phase == "diagnose"


def test_bug_lane_closes_without_demanding_a_retro(ready_vault):
    """start/SKILL.md: bug is `talk -> diagnose -> execute -> verify`. No retro."""
    write_note(ready_vault, "tasks/T-0001-dupes.md", type="task", id="T-0001",
               status="done", work_type="bug", title="dupes for tenant B")

    phase, _ = pingu.infer_phase(pingu.load_notes(ready_vault))
    assert phase == "done"


def test_incident_lane_does_demand_a_retro(ready_vault):
    """The same shape as the bug lane above, but incident marks retro required."""
    write_note(ready_vault, "tasks/T-0001-outage.md", type="task", id="T-0001",
               status="done", work_type="incident", title="restore the api")

    phase, _ = pingu.infer_phase(pingu.load_notes(ready_vault))
    assert phase == "retro"


def test_feature_lane_with_adr_skipped_advances_to_plan(ready_vault):
    """`adr?` is marked skippable in the lane table, so its absence must not
    wedge the state machine at `adr` forever."""
    write_note(ready_vault, "brief.md", type="brief", id="BRIEF-001",
               status="locked", work_type="feature", title="rate limiting")

    phase, _ = pingu.infer_phase(pingu.load_notes(ready_vault))
    assert phase == "plan"


def test_spike_lane_goes_to_research_then_retro(ready_vault):
    """start/SKILL.md: spike is `talk -> research -> retro`, no production code."""
    write_note(ready_vault, "brief.md", type="brief", id="BRIEF-001",
               status="locked", work_type="spike", title="can we even do X")

    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == "research"

    write_note(ready_vault, "research/R-0001-x.md", type="research", id="R-0001",
               status="done", work_type="spike", title="answer")
    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == "retro"


@pytest.mark.parametrize("status,expected", [
    ("draft", "talk"),
    ("blocked", "talk"),
    ("locked", "plan"),
])
def test_feature_lane_holds_at_talk_until_the_brief_is_settled(ready_vault, status, expected):
    write_note(ready_vault, "brief.md", type="brief", id="BRIEF-001",
               status=status, work_type="feature", title="notifications")

    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == expected


def test_feature_lane_full_progression(ready_vault):
    write_note(ready_vault, "brief.md", type="brief", id="BRIEF-001",
               status="locked", work_type="feature", title="rate limiting")
    write_note(ready_vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", work_type="feature", title="middleware")
    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == "execute"

    write_note(ready_vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="review", work_type="feature", title="middleware")
    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == "verify"

    write_note(ready_vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="done", work_type="feature", title="middleware")
    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == "retro"


@pytest.mark.parametrize("status", [None, "deferred", "locked"])
def test_a_task_with_no_recognised_status_is_not_treated_as_implemented(ready_vault, status):
    """`execute` is met only when every task has reached review or done.
    Anything else — an unset status, a status doctor would reject — means the
    work is unfinished, and status must not wave the loop through to verify."""
    fields = dict(type="task", id="T-0001", work_type="feature", title="unset")
    if status:
        fields["status"] = status
    write_note(ready_vault, "tasks/T-0001-x.md", **fields)

    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == "execute"


def test_verify_is_reported_once_every_task_has_reached_review(ready_vault):
    write_note(ready_vault, "tasks/T-0001-a.md", type="task", id="T-0001",
               status="done", work_type="feature", title="a")
    write_note(ready_vault, "tasks/T-0002-b.md", type="task", id="T-0002",
               status="review", work_type="feature", title="b")

    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == "verify"


def test_a_blocked_task_wins_over_lane_order(ready_vault):
    write_note(ready_vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="blocked", work_type="chore", title="stuck")

    phase, why = pingu.infer_phase(pingu.load_notes(ready_vault))
    assert phase == "execute"
    assert "blocked" in why


def test_lane_comes_from_the_most_recently_updated_note(ready_vault):
    """Two lanes of work in one vault: the newer one decides what status reports."""
    write_note(ready_vault, "tasks/T-0001-old.md", type="task", id="T-0001",
               status="done", work_type="feature", title="old", updated="2026-01-01")
    write_note(ready_vault, "tasks/T-0002-new.md", type="task", id="T-0002",
               status="todo", work_type="chore", title="new", updated="2026-08-03")

    assert pingu.lane_of(pingu.load_notes(ready_vault)) == "chore"


def test_an_empty_vault_still_reports_talk(ready_vault):
    """No notes means no work_type to read, so the feature lane is the safe default."""
    assert pingu.infer_phase(pingu.load_notes(ready_vault))[0] == "talk"


# ------------------------------------------------------------------------- doctor

def test_doctor_accepts_a_path_qualified_wikilink(run_pingu, vault):
    """Obsidian resolves [[standards/engineering]]; doctor must not call it broken.

    Written as a research note so the assertion isolates link resolution — a
    task would also have to satisfy the task schema to reach rc 0."""
    write_note(vault, "research/R-0001-x.md", type="research", id="R-0001", status="done",
               title="see [[standards/engineering]]")

    assert run_pingu("doctor") == 0


def test_doctor_accepts_an_aliased_wikilink(run_pingu, vault):
    write_note(vault, "research/R-0001-x.md", type="research", id="R-0001",
               status="done", title="x")
    (vault / "research" / "R-0001-x.md").write_text(
        "---\ntype: research\nid: R-0001\ntitle: x\nstatus: done\n---\n\n"
        "see [[glossary|our words]]\n",
        encoding="utf-8")

    assert run_pingu("doctor") == 0


def test_doctor_ignores_wikilinks_inside_fenced_code(run_pingu, vault):
    """The board and every schema example in this vault are fenced code blocks."""
    (vault / "research" / "R-0001-x.md").write_text(
        "---\ntype: research\nid: R-0001\ntitle: x\nstatus: done\n---\n\n"
        "```yaml\nadrs: [\"[[ADR-0003-token-bucket]]\"]\n```\n",
        encoding="utf-8")

    assert run_pingu("doctor") == 0


def test_doctor_still_reports_a_genuinely_broken_link(run_pingu, vault, capsys):
    (vault / "tasks" / "T-0001-x.md").write_text(
        "---\ntype: task\nid: T-0001\nstatus: todo\n---\n\nsee [[ADR-9999-nope]]\n",
        encoding="utf-8")

    assert run_pingu("doctor") == 1
    assert "broken link [[ADR-9999-nope]]" in capsys.readouterr().out


def test_doctor_reports_duplicate_ids_and_orphaned_epics(run_pingu, vault, capsys):
    for name in ("a", "b"):
        write_note(vault, f"tasks/T-0001-{name}.md", type="task", id="T-0001",
                   status="todo", epic="EPIC-99", title=name)

    assert run_pingu("doctor") == 1
    out = capsys.readouterr().out
    assert "duplicate id T-0001" in out
    assert "epic EPIC-99 does not exist" in out


# --------------------------------------------------------------------- vault path

def test_vault_path_finds_the_repo_root_without_claude_project_dir(repo, monkeypatch):
    """CLAUDE_PROJECT_DIR is exported to hook processes, not to every Bash call.
    vault_init.sh already resolves the root with git; the scripts must agree."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_VAULT_DIR", raising=False)
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)

    assert pingu.vault_path() == repo / "docs" / "vault"


def test_vault_path_honours_the_configured_vault_dir(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_VAULT_DIR", "docs/knowledge")

    assert pingu.vault_path() == repo / "docs" / "knowledge"


# ----------------------------------------------------------------- bin/ wrappers

@pytest.mark.parametrize("command", ["pingu", "gh-sync", "vault-init"])
def test_every_documented_command_has_an_executable_wrapper(command):
    """Skills invoke these by bare name. A plugin's bin/ joins the Bash tool's
    PATH; `scripts/` does not resolve from the user's repo."""
    import os
    from conftest import PLUGIN_ROOT

    wrapper = PLUGIN_ROOT / "bin" / command
    assert wrapper.is_file(), f"bin/{command} is missing"
    assert os.access(wrapper, os.X_OK), f"bin/{command} is not executable"


def test_wrappers_run_from_a_subdirectory_of_the_repo(repo):
    """The wrapper must find the vault by walking up to the repo root, since
    CLAUDE_PROJECT_DIR is absent for ordinary Bash tool calls."""
    import subprocess
    from conftest import PLUGIN_ROOT

    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    env = {"PATH": f"{PLUGIN_ROOT / 'bin'}:/usr/bin:/bin"}

    result = subprocess.run(["pingu", "status"], cwd=sub, env=env,
                            capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "[pingu] vault: vault" in result.stdout


# ---------------------------------------------------------------- obsidian templates

@pytest.mark.parametrize("template", ["task.md", "brief.md", "adr.md"])
def test_obsidian_templates_carry_the_fields_the_tooling_reads(template):
    """These are what a human fills in by hand in Obsidian. A note created from
    one with no `work_type` is invisible to lane_of, so the next session reports
    the wrong lane."""
    from conftest import PLUGIN_ROOT

    text = (PLUGIN_ROOT / "templates" / template).read_text(encoding="utf-8")
    assert "work_type:" in text, f"templates/{template} has no work_type"
    assert "status:" in text, f"templates/{template} has no status"


# ------------------------------------------------ required fields per note type

def test_doctor_flags_a_task_missing_its_epic(run_pingu, vault, capsys):
    """vault/SKILL.md's schema says every task links up to its epic. doctor
    checked that a named epic *exists*, never that one was named at all."""
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", work_type="feature", title="orphan")

    assert run_pingu("doctor") == 1
    assert "missing required field 'epic'" in capsys.readouterr().out


def test_doctor_flags_an_adr_with_no_deciders(run_pingu, vault, capsys):
    """An ADR nobody is recorded as having decided is the failure mode the adr
    skill warns about — a record of a preference, not a decision."""
    write_note(vault, "decisions/ADR-0001-x.md", type="adr", id="ADR-0001",
               status="accepted", title="token bucket")

    assert run_pingu("doctor") == 1
    assert "missing required field 'deciders'" in capsys.readouterr().out


def test_doctor_accepts_a_complete_task(run_pingu, vault):
    write_note(vault, "plan/EPIC-01-x.md", type="epic", id="EPIC-01",
               status="todo", work_type="feature", title="epic")
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", work_type="feature", title="task", epic="EPIC-01")

    assert run_pingu("doctor") == 0


def test_doctor_does_not_demand_fields_of_index_notes(run_pingu, vault):
    """context.md, glossary.md and the standards carry no id and no work_type
    by design. The seeded vault must pass doctor untouched."""
    assert run_pingu("doctor") == 0


def test_a_note_scaffolded_by_new_passes_doctor(run_pingu, vault):
    """The tooling must not generate notes its own validator rejects."""
    for kind, title in [("epic", "Rate limiting"), ("adr", "Token bucket"),
                        ("research", "Feasibility"), ("retro", "What we learned")]:
        assert run_pingu("new", kind, title) == 0

    assert run_pingu("doctor") == 0


# ------------------------------------------------------- SessionStart quietness

def test_status_quiet_says_nothing_when_there_is_no_vault(repo, monkeypatch, capsys):
    """The SessionStart hook runs in *every* project, because a personal-scope
    plugin loads everywhere. A repo with no vault is not using the loop, so
    announcing that costs context in every unrelated session and invites nobody.

    The hook opts into silence rather than the CLI defaulting to it — a human
    who types `pingu status` in a bare repo should still be told what to do."""
    import shutil
    import pingu

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    shutil.rmtree(repo / "docs" / "vault")

    assert pingu.main(["pingu", "status", "--quiet"]) == 0
    assert capsys.readouterr().out == ""


def test_status_without_quiet_still_explains_a_missing_vault(repo, monkeypatch, capsys):
    import shutil
    import pingu

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    shutil.rmtree(repo / "docs" / "vault")

    assert pingu.main(["pingu", "status"]) == 0
    out = capsys.readouterr().out
    assert "no vault" in out and "vault-init" in out


def test_quiet_still_reports_once_a_vault_exists(repo, monkeypatch, capsys):
    """Silence is only for the no-vault case. A real vault is worth announcing."""
    import pingu

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))

    assert pingu.main(["pingu", "status", "--quiet"]) == 0
    assert "[pingu]" in capsys.readouterr().out


def test_the_session_start_hook_asks_for_quiet():
    """If hooks.json stops passing --quiet, every unrelated project gets the
    no-vault banner again."""
    import json

    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]

    assert "status" in command and "--quiet" in command, command
