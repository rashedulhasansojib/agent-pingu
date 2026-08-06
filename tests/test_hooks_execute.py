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
import shlex
import shutil
import subprocess
import sys
import warnings

import pytest

from conftest import PLUGIN_ROOT, isolated_env

PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"


def hook_commands(event):
    """Every command string `hooks.json` declares for one event."""
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return [h["command"] for entry in hooks["hooks"].get(event, []) for h in entry["hooks"]]


def argv_for(command):
    """The declared command string as an argv this test can run.

    Split *before* substituting, not after. `shlex.split` in POSIX mode eats
    backslashes, so expanding the placeholder first would mangle every Windows
    path into an unrecognisable one — and the failure would look like a bug in
    the hook rather than in this helper.

    The interpreter is resolved to an absolute path against the ambient PATH,
    because the subprocess runs under `isolated_env`, whose PATH is deliberately
    minimal. Resolving it here keeps the isolation without pretending the
    interpreter is missing.
    """
    tokens = [t.replace(PLACEHOLDER, str(PLUGIN_ROOT)) for t in shlex.split(command)]
    resolved = shutil.which(tokens[0]) or shutil.which(tokens[0] + ".exe")
    if resolved is None:
        # Falling back keeps the question this test asks ("does the hook's script
        # work?") separate from the one the test below asks ("does the declared
        # interpreter name resolve here?"). Conflating them would let a missing
        # `python3` masquerade as a broken guard.
        #
        # Said out loud, because a silent substitution is how every one of these
        # tests passes on a platform where the hooks would not run at all. The
        # xfail below records the fact; this makes it visible in the CI log of
        # the job that actually did the substituting.
        warnings.warn(
            f"{tokens[0]!r} does not resolve here — running these hook commands "
            f"with {sys.executable!r} instead. The scripts are being tested; the "
            f"interpreter name in hooks.json is not. See T-0004.",
            stacklevel=2,
        )
        tokens[0] = sys.executable
    else:
        tokens[0] = resolved
    return tokens


def run_hook(command, repo, payload=None):
    return subprocess.run(
        argv_for(command), cwd=repo, env=isolated_env(repo),
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
    interpreters = {shlex.split(c)[0] for c in hook_commands("SessionStart") + hook_commands("PreToolUse")}
    assert interpreters, "no hook commands to check"
    for name in interpreters:
        assert shutil.which(name), (
            f"hooks.json runs {name!r}, which does not resolve on this platform — "
            f"both hooks would fail silently")
