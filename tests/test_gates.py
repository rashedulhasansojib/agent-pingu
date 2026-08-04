"""Tests for `pingu gate`.

`start/SKILL.md` claims "the gates are what make autonomy safe". Until now that
was a markdown table nothing checked. These tests hold the runner to the two
properties that make a gate worth having: it never claims a pass it did not
verify, and it never runs a command nobody declared.
"""

import json

import pytest

import pingu
from conftest import write_note


def set_context(vault, **fields):
    """Rewrite the seeded context.md frontmatter."""
    path = vault / "context.md"
    lines = ["---", "type: context", "title: demo", "status: ready"]
    for key, value in fields.items():
        lines.append(f"{key}: {json.dumps(value) if isinstance(value, list) else value}")
    lines += ["---", "", "# demo", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def statuses(result):
    return {check["name"]: check["status"] for check in result["checks"]}


# ------------------------------------------------------------------ declaration

def test_every_phase_in_the_gate_table_has_a_declared_gate():
    """The table in start/SKILL.md and GATES are the same list written twice."""
    assert set(pingu.GATES) == {
        "setup", "talk", "research", "adr", "plan",
        "diagnose", "execute", "verify", "retro",
    }


def test_every_check_declares_a_kind_the_runner_understands():
    for phase, checks in pingu.GATES.items():
        assert checks, f"{phase} declares no checks at all"
        for check in checks:
            assert check.kind in ("vault", "command", "manual"), (
                f"{phase}: unknown check kind {check.kind!r}")


# ----------------------------------------------------------------- manual gates

def test_a_manual_check_never_passes_even_when_executing(ready_vault):
    """The whole point of the manual kind. A gate a tool cannot verify must stay
    visibly unverified rather than quietly counting as met."""
    result = pingu.run_gate(ready_vault, "diagnose", execute=True)

    assert all(c["status"] == "manual-review" for c in result["checks"])
    assert result["ready"] is False


def test_a_phase_of_only_manual_checks_is_not_a_failure(ready_vault):
    """Unverified is not the same as broken — exit code must distinguish them."""
    result = pingu.run_gate(ready_vault, "diagnose", execute=True)

    assert result["ok"] is True
    assert result["ready"] is False


# ------------------------------------------------------------------ vault gates

def test_setup_gate_fails_while_notes_are_still_templates(vault):
    result = pingu.run_gate(vault, "setup")

    assert statuses(result)["standards, context and glossary are filled in"] == "failed"
    assert result["ok"] is False


def test_setup_gate_passes_once_the_templates_are_filled(ready_vault):
    result = pingu.run_gate(ready_vault, "setup")

    assert statuses(result)["standards, context and glossary are filled in"] == "passed"
    assert result["ok"] is True


def test_talk_gate_fails_when_non_goals_is_an_empty_heading(ready_vault):
    (ready_vault / "brief.md").write_text(
        "---\ntype: brief\nid: BRIEF-001\ntitle: b\nstatus: draft\nwork_type: feature\n---\n\n"
        "## Success criteria\np95 under 400ms\n\n## Non-goals\n\n",
        encoding="utf-8")

    result = pingu.run_gate(ready_vault, "talk")

    assert result["ok"] is False
    assert "non-goals" in json.dumps(result).lower()


def test_talk_gate_passes_when_both_sections_have_content(ready_vault):
    (ready_vault / "brief.md").write_text(
        "---\ntype: brief\nid: BRIEF-001\ntitle: b\nstatus: locked\nwork_type: feature\n---\n\n"
        "## Success criteria\np95 under 400ms\n\n## Non-goals\nNo tenant isolation work.\n",
        encoding="utf-8")

    assert pingu.run_gate(ready_vault, "talk")["ok"] is True


def test_talk_gate_fails_when_there_is_no_brief_at_all(ready_vault):
    assert pingu.run_gate(ready_vault, "talk")["ok"] is False


def test_plan_gate_fails_when_a_task_has_no_acceptance_criteria(ready_vault):
    write_note(ready_vault, "plan/EPIC-01-x.md", type="epic", id="EPIC-01",
               status="todo", work_type="feature", title="e")
    (ready_vault / "tasks" / "T-0001-x.md").parent.mkdir(parents=True, exist_ok=True)
    (ready_vault / "tasks" / "T-0001-x.md").write_text(
        "---\ntype: task\nid: T-0001\ntitle: t\nstatus: todo\nwork_type: feature\n"
        "epic: EPIC-01\n---\n\n## Acceptance criteria\n\n## Approach\nsomething\n",
        encoding="utf-8")

    result = pingu.run_gate(ready_vault, "plan")

    assert result["ok"] is False
    assert "T-0001" in json.dumps(result)


def test_plan_gate_passes_when_every_task_has_a_checkbox_criterion(ready_vault):
    write_note(ready_vault, "plan/EPIC-01-x.md", type="epic", id="EPIC-01",
               status="todo", work_type="feature", title="e")
    (ready_vault / "tasks" / "T-0001-x.md").parent.mkdir(parents=True, exist_ok=True)
    (ready_vault / "tasks" / "T-0001-x.md").write_text(
        "---\ntype: task\nid: T-0001\ntitle: t\nstatus: todo\nwork_type: feature\n"
        "epic: EPIC-01\n---\n\n## Acceptance criteria\n- [ ] returns 429 past the limit\n",
        encoding="utf-8")

    assert pingu.run_gate(ready_vault, "plan")["ok"] is True


# ---------------------------------------------------------------- command gates

def test_a_command_gate_is_planned_not_run_by_default(ready_vault):
    """Running someone's test suite is a side effect. Default to showing what
    would run, the way claude-obsidian's gates.py plans before it executes."""
    set_context(ready_vault, test_command=["python3", "-c", "raise SystemExit(1)"])

    result = pingu.run_gate(ready_vault, "verify")

    assert statuses(result)["test suite passes"] == "planned"
    assert result["ok"] is True, "planning must not report a failure"
    assert result["ready"] is False


def test_a_command_gate_runs_and_passes_when_executed(ready_vault):
    set_context(ready_vault, test_command=["python3", "-c", "raise SystemExit(0)"])

    result = pingu.run_gate(ready_vault, "verify", execute=True)

    assert statuses(result)["test suite passes"] == "passed"


def test_a_command_gate_runs_and_fails_when_the_command_fails(ready_vault):
    set_context(ready_vault, test_command=["python3", "-c", "raise SystemExit(3)"])

    result = pingu.run_gate(ready_vault, "verify", execute=True)

    assert statuses(result)["test suite passes"] == "failed"
    assert result["ok"] is False
    assert "3" in json.dumps(result), "the exit code should be reported"


def test_an_undeclared_command_is_not_a_silent_pass(ready_vault):
    """The seeded context.md has no test_command. A gate that cannot find its
    command must say so — treating absence as success is how a green tick starts
    meaning nothing."""
    result = pingu.run_gate(ready_vault, "verify", execute=True)

    assert statuses(result)["test suite passes"] == "not-declared"
    assert result["ready"] is False


def test_a_command_declared_as_a_bare_string_is_rejected(ready_vault):
    """A list keeps the command off a shell. Accepting a string would invite
    `npm test && deploy` and quietly run it through one."""
    set_context(ready_vault, test_command="pytest -q")

    result = pingu.run_gate(ready_vault, "verify", execute=True)

    assert statuses(result)["test suite passes"] == "not-declared"
    assert "list" in json.dumps(result).lower()


def test_a_command_gate_never_uses_a_shell(ready_vault, tmp_path):
    """If this ran through a shell, the redirection would create the file."""
    marker = tmp_path / "pwned.txt"
    set_context(ready_vault, test_command=["python3", "-c", "pass", ">", str(marker)])

    pingu.run_gate(ready_vault, "verify", execute=True)

    assert not marker.exists()


# ------------------------------------------------------------------- cli surface

def test_gate_cli_exits_zero_when_nothing_it_can_check_is_broken(run_pingu, ready_vault, capsys):
    assert run_pingu("gate", "setup") == 0
    assert "passed" in capsys.readouterr().out


def test_gate_cli_exits_one_on_a_real_failure(run_pingu, vault, capsys):
    assert run_pingu("gate", "setup") == 1
    assert "failed" in capsys.readouterr().out


def test_gate_cli_defaults_to_the_phase_the_vault_is_in(run_pingu, ready_vault, capsys):
    """`pingu gate` with no argument gates whatever infer_phase reports, so the
    router does not have to name the phase twice.

    A todo task means the execute gate is genuinely unmet, so rc is 1 here —
    that is the gate working, and asserting rc 0 would be asserting that gates
    do not gate."""
    write_note(ready_vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", work_type="chore", title="bump", epic="")

    assert run_pingu("gate") == 1
    assert "[gate] execute" in capsys.readouterr().out


def test_gate_cli_says_so_when_the_loop_is_closed(run_pingu, ready_vault, capsys):
    """infer_phase can report `done`, which has no gate. That is not an error."""
    write_note(ready_vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="done", work_type="chore", title="bump", epic="")

    assert run_pingu("gate") == 0
    assert "nothing left to gate" in capsys.readouterr().out


def test_gate_cli_rejects_an_unknown_phase(run_pingu, ready_vault):
    assert run_pingu("gate", "nonsense") == 1


def test_gate_cli_reports_manual_checks_visibly(run_pingu, ready_vault, capsys):
    run_pingu("gate", "diagnose", "--execute")
    out = capsys.readouterr().out

    assert "manual-review" in out
    assert "not verified" in out.lower() or "human" in out.lower()


# ------------------------------------------------- the seeded declaration slot

def test_vault_init_seeds_the_command_keys(vault):
    """setup can only fill in a field the scaffold told it about. An empty
    `test_command: []` is a prompt; a missing key is invisible."""
    frontmatter = pingu.parse_frontmatter(vault / "context.md")

    assert "test_command" in frontmatter[pingu.DECLARED]
    assert "lint_command" in frontmatter[pingu.DECLARED]


def test_the_seeded_command_is_empty_not_a_guess(vault):
    """A scaffold that guessed `["npm","test"]` would have gate --execute run
    the wrong thing on the first try."""
    argv, error = pingu.declared_command(vault, "test_command")

    assert argv is None
    assert error


def test_a_gate_of_only_vault_checks_is_ready_without_execute(ready_vault):
    """`--execute` exists to opt into running commands. A gate that declares no
    commands has nothing to defer, so requiring the flag would report a fully
    checked gate as 'not met yet' — and 0 outstanding checks is a pass."""
    (ready_vault / "brief.md").write_text(
        "---\ntype: brief\nid: BRIEF-001\ntitle: b\nstatus: locked\nwork_type: feature\n---\n\n"
        "## Success criteria\np95 under 400ms\n\n## Non-goals\nNo tenant work.\n",
        encoding="utf-8")

    result = pingu.run_gate(ready_vault, "talk")

    assert result["pending"] == []
    assert result["ready"] is True


def test_ready_stays_false_while_a_command_is_only_planned(ready_vault):
    """The inverse: an unrun command must keep the gate unmet."""
    set_context(ready_vault, test_command=["python3", "-c", "pass"])

    result = pingu.run_gate(ready_vault, "verify")

    assert "test suite passes" in result["pending"]
    assert result["ready"] is False


# ------------------------------------------------------- what the docs promise

def test_the_documented_split_of_checkable_versus_manual_still_holds():
    """README, MANUAL and start/SKILL.md all state this breakdown in prose. It
    was stated wrong once already — written from the design note before the
    gates were built. If GATES changes, fix those three files too."""
    fully_checkable, partly_manual, entirely_manual = [], [], []
    for phase, checks in pingu.GATES.items():
        kinds = {c.kind for c in checks}
        if kinds == {"manual"}:
            entirely_manual.append(phase)
        elif "manual" in kinds:
            partly_manual.append(phase)
        else:
            fully_checkable.append(phase)

    assert fully_checkable == ["talk", "research", "plan"]
    assert partly_manual == ["setup", "execute", "verify", "retro"]
    assert entirely_manual == ["adr", "diagnose"]
