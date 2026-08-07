"""The hooks, actually run — not just parsed as JSON.

`hooks/hooks.json` is the whole always-on surface of this plugin. Per ADR-0001,
SessionStart is the *only* channel that gets lane, phase and autonomy into the
model's context, and PreToolUse is the one gate that does not ask the model
whether it met it. Until this file existed, CI proved exactly one thing about
both: that the file was valid JSON. The pytest suite called `pingu.py` directly
and never went through a command string, so a typo in either one shipped green.

This lives in pytest rather than as a step in test.yml so it runs on all four
matrix cells, Windows included. A bash step would have run on one.

**What this proves, and what it does not.** It proves the commands declared in
`hooks.json` name a real script, that the script runs, and that it exits with the
codes the hook protocol reads. It does *not* prove Claude Code executes them the
same way on every platform: `${CLAUDE_PLUGIN_ROOT}` is expanded by Claude Code,
not by us, and whether a hook command goes through a POSIX shell on Windows is
T-0004's first open question. Substituting the placeholder here would be testing
our own expansion and calling it theirs. Being explicit about the boundary is the
point — the alternative is the confident green tick this repo exists to avoid.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

import pingu
from conftest import BASH, PLUGIN_ROOT, isolated_env

PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"


def hook_entries(event, shell="bash"):
    """Every hook declared for one event, for one declared shell.

    Entries are filtered by their `shell` key rather than returned as bare
    strings, because since ADR-0006 an event carries one entry per shell and the
    two are written in different languages. Running a PowerShell command through
    bash is not a weaker test, it is a *wrong* one — and it passes: bash exits 2
    on a syntax error, which is exactly the code the fail-closed test asserts. It
    went green against a command that had never run.
    """
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return [h for entry in hooks["hooks"].get(event, []) for h in entry["hooks"]
            if h.get("shell", "bash") == shell]


def hook_commands(event, shell="bash"):
    return [h["command"] for h in hook_entries(event, shell)]


PWSH = shutil.which("pwsh") or shutil.which("powershell")

NEEDS_PWSH = pytest.mark.skipif(
    PWSH is None, reason="no PowerShell on this machine; ADR-0006's Windows path")


def shell_argv(shell, command):
    """How Claude Code would invoke this command, for the shell it declares."""
    body = command.replace(PLACEHOLDER, str(PLUGIN_ROOT))
    if shell == "powershell":
        return [PWSH, "-NoProfile", "-NonInteractive", "-Command", body]
    return [shutil.which(BASH) or BASH, "-c", body]


def hook_env(repo, path=None):
    """`isolated_env`, but with a PATH that can actually find an interpreter.

    `isolated_env` pins PATH to `/usr/bin:/bin` for isolation. Since ADR-0005 the
    hook commands *resolve* their interpreter off PATH, so that pin is no longer
    incidental — it is the input under test. Callers that want the missing-
    interpreter case pass their own `path`.
    """
    env = isolated_env(repo)
    env["PATH"] = os.environ.get("PATH", "") if path is None else path
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    return env


def run_hook(command, repo, payload=None, path=None, shell="bash"):
    """Run a declared hook command through the shell it declares.

    These commands are *shell form* — no `args` key — which per ADR-0005 is
    deliberate, because only a shell can resolve an interpreter and still exit 2
    when it cannot. So they must be executed by a shell here too. They used to be
    `shlex.split` into an argv, which stopped being meaningful the moment the
    command became a script rather than a bare invocation.
    """
    return subprocess.run(
        shell_argv(shell, command),
        cwd=repo, env=hook_env(repo, path),
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True, text=True,
    )


# ------------------------------------------------------------------ SessionStart

def test_the_session_start_hook_is_declared():
    assert hook_commands("SessionStart"), "hooks.json declares no SessionStart hook"


@pytest.mark.parametrize("command", hook_commands("SessionStart"))
def test_the_session_start_command_runs_and_reports_the_vault(command, repo):
    """Exit 0 alone would pass for a command that printed nothing at all.

    `repo` is a freshly scaffolded vault, so its notes are templates and the one
    thing this output must carry is the setup banner. That pins that the command
    reached the vault and read it, which is the whole reason the hook exists.
    """
    result = run_hook(command, repo)

    assert result.returncode == 0, (
        f"{command!r} exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}")
    assert "SETUP NEEDED" in result.stdout, (
        f"the SessionStart hook ran but said nothing about the vault:\n{result.stdout}")


# ------------------------------------------------------------------- PreToolUse

def guard_commands(shell="bash"):
    return [c for c in hook_commands("PreToolUse", shell) if "guard" in c]


def test_the_guard_hook_is_declared():
    assert guard_commands(), "hooks.json declares no PreToolUse guard hook"


@pytest.mark.parametrize("command", guard_commands())
def test_the_guard_command_blocks_an_edit_outside_a_template_vault(command, repo):
    """Exit 2 is the number that matters. The hook protocol reads 2 as *blocked*
    and everything else — including the 1 this used to exit with when it crashed
    — as a non-blocking error, which lets the edit through. A test asserting
    "non-zero" would pass on the exact failure this gate was written to fix."""
    result = run_hook(command, repo, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "src" / "feature.py")},
    })

    assert result.returncode == 2, (
        f"{command!r} exited {result.returncode}, not 2 (blocked)\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}")
    assert "still templates" in result.stderr


@pytest.mark.parametrize("command", guard_commands())
def test_the_guard_command_allows_an_edit_inside_the_vault(command, repo):
    """The other direction, and it is not a formality: setup has to be able to
    write the files that are blocking setup. A guard that blocked both ways would
    wedge the repo, and both assertions passing at exit 0 is the vacuous version
    of this pair."""
    result = run_hook(command, repo, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "docs" / "vault" / "context.md")},
    })

    assert result.returncode == 0, (
        f"{command!r} blocked a write inside the vault\n--- stderr ---\n{result.stderr}")


# ----------------------------------------------------- the interpreter, on record

NO_PYTHON_PATH = "/nonexistent-agent-pingu-empty-bin"


def _path_without_bash():
    """The real PATH minus any directory containing a bash, so the PowerShell
    entry's stand-down branch does not fire. Windows CI has Git Bash, which is
    exactly the machine these tests must pretend not to be."""
    keep = []
    for part in os.environ.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        if any((pathlib.Path(part) / n).exists() for n in ("bash", "bash.exe")):
            continue
        keep.append(part)
    return os.pathsep.join(keep)

# Skipped by *capability*, not by platform name — the same convention as
# NEEDS_O_NOFOLLOW, and for the same reason. These two tests prove ADR-0005's
# headline claim, and skipping them on `os.name == "nt"` made them invisible on
# precisely the platform where that claim is least certain. `conftest.BASH`
# resolves Git Bash by name on Windows, and every other test in this file already
# runs through it there, so there is no platform limitation to hide behind: if a
# POSIX shell is present the claim is testable, and if one is not then ADR-0005
# says outright that the guarantee does not hold.
NEEDS_POSIX_SHELL = pytest.mark.skipif(
    shutil.which(BASH) is None,
    reason="ADR-0005: the guard can only fail closed where a POSIX shell exists",
)


@NEEDS_POSIX_SHELL
@pytest.mark.parametrize("command", guard_commands())
def test_the_guard_fails_closed_when_no_interpreter_resolves(command, repo):
    """The finding this run exists for, and the one number that encodes it.

    Measured before the fix: with no Python on PATH the old command exited 127,
    the hook protocol read that as a non-blocking error, and **the edit went
    through** — verified end to end against a real `claude -p` session, with a
    hook that exits 2 as the control to prove the probe could detect a block.
    So the setup gate silently granted permission on exactly the machines it was
    written to protect.

    `!= 0` would pass on 127 and assert nothing. It must be 2.
    """
    result = run_hook(command, repo, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "src" / "feature.py")},
    }, path=NO_PYTHON_PATH)

    assert result.returncode == 2, (
        f"with no interpreter on PATH the guard exited {result.returncode}, not 2 — "
        f"anything but 2 lets the edit through\n--- stderr ---\n{result.stderr}")


@NEEDS_POSIX_SHELL
@pytest.mark.parametrize("command", hook_commands("SessionStart"))
def test_session_start_does_not_block_when_no_interpreter_resolves(command, repo):
    """The opposite trade from the guard, and deliberate — ADR-0005 rule 3.

    A session that cannot print its status line should say so, not refuse to
    start. Non-zero so the failure is visible; never 2, which would block.
    """
    result = run_hook(command, repo, path=NO_PYTHON_PATH)

    assert result.returncode != 0, "a missing interpreter should be reported, not silent"
    assert result.returncode != 2, (
        "SessionStart exited 2, which blocks. Only the guard may fail closed.")


@pytest.mark.parametrize("shell", ["bash", "powershell"])
def test_both_hooks_resolve_the_interpreter_the_same_way(shell):
    """ADR-0005 rule 5: the visible hook is the canary for the invisible one.

    SessionStart prints `[pingu]` lines a human sees. PreToolUse is silent when
    it allows. Because both resolve the interpreter identically, a missing
    `[pingu]` line at session start means the guard is not running either — the
    only user-facing signal that the gate is down.

    ADR-0006 put two entries on each event, one per shell, so the invariant is now
    **per shell** rather than global: whichever entry actually fires on a machine,
    the same one fires for both events, so the inference still holds there. Left
    global it would have compared a bash resolver against a PowerShell one and
    failed for a reason that has nothing to do with the property.
    """
    def resolver(command):
        if shell == "powershell":
            found = re.search(r"@\((.*?)\)", command)
        else:
            found = re.search(r"\$\((.*?)\)", command)
        return found.group(1).strip() if found else command

    commands = hook_commands("SessionStart", shell) + guard_commands(shell)
    assert commands, f"no {shell} hooks declared"
    resolvers = {resolver(c) for c in commands}
    assert len(resolvers) == 1, (
        f"the {shell} hooks no longer resolve the interpreter identically, so a "
        f"present [pingu] line no longer implies a working guard:\n"
        + "\n".join(sorted(resolvers)))


@pytest.mark.parametrize("command", guard_commands())
def test_the_fallback_cannot_turn_a_block_into_an_allow(command):
    """The trap T-0004 named, pinned so nobody rediscovers it by shipping it.

    `guard` returns 2 to mean *blocked*. So a fallback chained onto the guard —
    `... pingu.py guard || ... pingu.py guard` — would re-run it on every block
    and let the second, successful run allow the edit. Every block becomes an
    allow, and the suite stays green because the happy path is unchanged.

    The resolver's `||` is therefore only ever allowed *inside* the command
    substitution that picks an interpreter, which runs before `pingu.py` is
    invoked at all.
    """
    before_exec, _, after_exec = command.partition("exec ")
    assert "||" not in after_exec, (
        "a `||` appears after the interpreter is resolved, so a blocked edit "
        f"(exit 2) could be retried into an allow:\n{command}")
    # The script itself must be invoked exactly once, and only after resolution.
    # Matching on the word "guard" would not work: it appears in the diagnostic
    # message too, which is prose rather than an invocation.
    assert "pingu.py" not in before_exec, (
        "pingu.py is invoked before the interpreter is resolved, so a block "
        f"could be retried into an allow:\n{command}")
    assert after_exec.count("pingu.py") == 1, (
        f"pingu.py is invoked more than once, which is how a block becomes an "
        f"allow:\n{command}")


@pytest.mark.xfail(
    os.name == "nt", strict=False,
    reason="T-0004: whether `python3` resolves on Windows is open. Recorded, not asserted.",
)
def test_the_interpreter_the_hooks_name_resolves_on_this_platform():
    """Every hook command hard-codes an interpreter name, and if it does not
    resolve, both hooks fail quietly — no lane in context, no setup gate.

    Non-blocking on Windows on purpose. T-0004 is open precisely because nobody
    has run this there, and this repo has already produced one confident, wrong,
    well-sourced answer about Windows by reasoning instead of running. An xfail
    makes the runner answer it: XPASS means `python3` resolves and T-0004's
    second question is settled in the affirmative; XFAIL means it does not and
    the hooks need the resolver that task describes. Either way the build stays
    green and the answer comes from a machine.

    Reading the answer takes looking: run pytest with `-rXx` to see XPASS and
    XFAIL in the summary. Nothing turns red either way, which is the point and
    also the cost — someone has to go and look at the Windows job.
    """
    names = pingu.hook_interpreter_names()
    assert names, "no interpreter names could be read out of hooks.json"
    assert any(shutil.which(n) for n in names), (
        f"hooks.json tries {', '.join(names)}, and none resolves on this "
        f"platform — SessionStart would report nothing and the guard would "
        f"refuse every edit")


# --------------------------------------------------- the PowerShell path, ADR-0006
#
# These are the whole point of ADR-0006 and they cannot run on macOS or Linux.
# They skip by *capability* — no PowerShell present — so on the Windows cell,
# which has it, they run. Verifying the stock-Windows path on a runner is the
# closest thing to a Windows workstation available here, and it is a great deal
# closer than reasoning about it, which this repo is three-for-three wrong at.

@NEEDS_PWSH
@pytest.mark.parametrize("command", guard_commands("powershell"))
def test_the_powershell_guard_blocks_an_edit_outside_a_template_vault(command, repo):
    """The same claim as the bash guard, in the other language.

    `bash` is hidden from PATH so the stand-down branch does not fire — that
    branch is what the next test is for, and conflating the two would let a guard
    that always stands down pass as a guard that blocks.
    """
    result = run_hook(command, repo, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "src" / "feature.py")},
    }, path=_path_without_bash(), shell="powershell")

    assert result.returncode == 2, (
        f"the PowerShell guard exited {result.returncode}, not 2 (blocked)\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}")


@NEEDS_PWSH
@pytest.mark.parametrize("command", guard_commands("powershell"))
def test_the_powershell_guard_allows_an_edit_inside_the_vault(command, repo):
    """Setup has to be able to write the files that are blocking setup."""
    result = run_hook(command, repo, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "docs" / "vault" / "context.md")},
    }, path=_path_without_bash(), shell="powershell")

    assert result.returncode == 0, (
        f"the PowerShell guard blocked a write inside the vault\n{result.stderr}")


@NEEDS_PWSH
@pytest.mark.parametrize("command", guard_commands("powershell"))
def test_the_powershell_guard_fails_closed_when_no_interpreter_resolves(command, repo):
    """ADR-0005 rule 2, carried into the PowerShell path rather than dropped.

    This is the claim ADR-0005 said could not be met without a POSIX shell, and
    the reason ADR-0006 supersedes it in part. `!= 0` would pass on the
    command-not-found code and assert nothing; it must be 2.
    """
    result = run_hook(command, repo, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "src" / "feature.py")},
    }, path=NO_PYTHON_PATH, shell="powershell")

    assert result.returncode == 2, (
        f"with no interpreter and no bash the PowerShell guard exited "
        f"{result.returncode}, not 2 — anything else lets the edit through\n"
        f"--- stderr ---\n{result.stderr}")


@NEEDS_PWSH
@pytest.mark.parametrize("command", guard_commands("powershell") + hook_commands("SessionStart", "powershell"))
def test_the_powershell_entry_stands_down_when_bash_is_present(command, repo):
    """The mutual exclusion that stops double execution.

    Both entries fire on a Windows box that has Git Bash — the platform has no
    conditional in the hook schema, and every entry in an event runs. Without a
    stand-down the guard would run twice and `[pingu]` would print twice.

    Exit 0 rather than a refusal, because on `PreToolUse` 0 means "no decision,
    use the normal flow" — it does not overrule the bash entry's 2. A stand-down
    that exited 2 would block every edit on every Windows machine with Git Bash.
    """
    result = run_hook(command, repo, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "src" / "feature.py")},
    }, shell="powershell")

    assert result.returncode == 0, (
        f"the PowerShell entry did not stand down with bash on PATH; it exited "
        f"{result.returncode}\n--- stderr ---\n{result.stderr}")
    assert "[pingu]" not in result.stdout, (
        "the PowerShell entry produced output while standing down, so a machine "
        f"with both shells would report twice:\n{result.stdout}")
