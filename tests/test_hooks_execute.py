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
import re
import shutil
import subprocess

import pytest

import pingu
from conftest import BASH, PLUGIN_ROOT, isolated_env

PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"


def hook_commands(event):
    """Every command string `hooks.json` declares for one event."""
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return [h["command"] for entry in hooks["hooks"].get(event, []) for h in entry["hooks"]]


def hook_env(repo, path=None):
    """`isolated_env`, but with a PATH that can actually find an interpreter.

    `isolated_env` pins PATH to `/usr/bin:/bin` for isolation. Since ADR-0005 the
    hook commands *resolve* their interpreter off PATH, so that pin is no longer
    incidental — it is the input under test. Callers that want the missing-
    interpreter case pass their own `path`.
    """
    env = isolated_env(repo)
    env["PATH"] = os.environ.get("PATH", "") if path is None else path
    return env


def run_hook(command, repo, payload=None, path=None):
    """Run a declared hook command the way Claude Code does: through a shell.

    These commands are *shell form* — no `args` key — which per ADR-0005 is
    deliberate, because only a shell can resolve an interpreter and still exit 2
    when it cannot. So they must be executed by a shell here too. They used to be
    `shlex.split` into an argv, which stopped being meaningful the moment the
    command became a script rather than a bare invocation: argv[0] became
    `PY=$(command`, every command "failed to resolve", and the helper silently
    substituted `sys.executable` and tested nothing that was declared.
    """
    # Absolute, because the missing-interpreter cases hand this a PATH with
    # nothing on it — including bash. Resolving the shell against that PATH would
    # fail to spawn at all, and the test would "pass" or error for a reason that
    # has nothing to do with the interpreter under test.
    shell = shutil.which(BASH) or BASH
    return subprocess.run(
        [shell, "-c", command.replace(PLACEHOLDER, str(PLUGIN_ROOT))],
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

def guard_commands():
    return [c for c in hook_commands("PreToolUse") if "guard" in c]


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


@pytest.mark.skipif(os.name == "nt", reason="needs a POSIX shell to be the shell")
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


@pytest.mark.skipif(os.name == "nt", reason="needs a POSIX shell to be the shell")
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


def test_both_hooks_resolve_the_interpreter_the_same_way():
    """ADR-0005 rule 5: the visible hook is the canary for the invisible one.

    SessionStart prints `[pingu]` lines a human sees. PreToolUse is silent when
    it allows. Because both resolve the interpreter identically, a missing
    `[pingu]` line at session start means the guard is not running either — the
    only user-facing signal that the gate is down. It exists only while the two
    stay identical, and nothing else would notice them diverging.
    """
    def resolver(command):
        """The interpreter-choosing expression, i.e. what is inside `$( ... )`.

        Not "everything before the first `;`" — the two commands carry different
        diagnostic messages, and those contain semicolons, so that comparison
        fails for a reason unrelated to what this test is about.
        """
        found = re.search(r"\$\((.*?)\)", command)
        return found.group(1).strip() if found else command

    resolvers = {resolver(c) for c in hook_commands("SessionStart") + guard_commands()}
    assert len(resolvers) == 1, (
        "the hooks no longer resolve the interpreter identically, so a present "
        f"[pingu] line no longer implies a working guard:\n" + "\n".join(sorted(resolvers)))


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
