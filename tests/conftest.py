"""Shared fixtures. Every test runs against a real scaffolded vault in tmp_path,
so the tests exercise vault_init.sh and the scripts together rather than a mock
of what we think the vault looks like."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))


def _bash():
    """The bash these tests should run `vault_init.sh` under.

    On Windows, bare `bash` resolves to `C:\\Windows\\System32\\bash.exe` — the
    WSL launcher — which shadows Git Bash on PATH. On a machine with no WSL
    distribution installed it prints a UTF-16 complaint and exits 1, which is
    what it did on the first Windows CI run: 250 errors, all of them this.

    `shutil.which` does not help, because the WSL stub is a real executable and
    is genuinely first. README tells Windows users to bring Git Bash or WSL, so
    look for Git Bash by name before falling back to whatever PATH offers.
    """
    if os.name != "nt":
        return "bash"
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                 os.environ.get("ProgramFiles(x86)"), r"C:\Program Files"):
        if not base:
            continue
        candidate = Path(base) / "Git" / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return "bash"


BASH = _bash()

# `os.O_NOFOLLOW` is POSIX-only. ADR-0004 rule 4 is explicit that a platform
# without it "loses this protection and keeps a working allocator", so a test
# asserting the protection holds is asserting something the decision does not
# claim. Skip rather than weaken the assertion — the point of the rule is that
# the degradation is known, not that it is invisible.
NEEDS_O_NOFOLLOW = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"),
    reason="ADR-0004 rule 4 is best-effort: no O_NOFOLLOW on this platform",
)

# `bin/` is bash. README tells Windows users to bring Git Bash or WSL, so the
# wrappers are out of scope for a bare Windows runner rather than broken on it.
POSIX_ONLY = pytest.mark.skipif(
    os.name == "nt", reason="bin/ wrappers are bash; see README on Windows"
)


def set_home(monkeypatch, path):
    """Point home resolution at `path`, on every platform.

    `HOME` alone does not do this on Windows: `ntpath.expanduser` reads
    USERPROFILE, so a fixture setting only HOME silently read the developer's
    real `~/.claude/settings.json` instead of the empty one it had just built.
    Every test that thought it was isolated was not.
    """
    monkeypatch.setenv("HOME", str(path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(path))


def write_note(vault, relpath, **fields):
    """Write a note with the given frontmatter. Body is a stub."""
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in fields.items())
    path.write_text(f"---\n{fm}\n---\n\n# {fields.get('title', 'note')}\n", encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    """A git repo with a vault scaffolded by the real vault_init.sh."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=tmp_path, capture_output=True, text=True,
    )
    # `check=True` here raised a CalledProcessError carrying the exit code and
    # nothing else, which is the failure this repo's own standard warns about:
    # capture stderr, so 127 and 1 stay distinguishable. Every test in the suite
    # depends on this fixture, so when it breaks on a platform nobody is sitting
    # in front of, its exit code alone is 250 identical errors and no diagnosis.
    if result.returncode != 0:
        raise AssertionError(
            f"vault_init.sh exited {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    return tmp_path


@pytest.fixture
def vault(repo):
    return repo / "docs" / "vault"


@pytest.fixture
def ready_vault(vault):
    """A vault whose seeded notes have been filled in, so `setup` no longer
    masks the phase the lane inference would otherwise report."""
    for path in vault.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "status: template" in text:
            path.write_text(text.replace("status: template", "status: ready"), encoding="utf-8")
    return vault


@pytest.fixture
def run_pingu(repo, monkeypatch):
    """Invoke pingu.py in-process against this repo, capturing stdout."""
    import pingu

    def _run(*argv, **env):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return pingu.main(["pingu.py", *argv])

    return _run
