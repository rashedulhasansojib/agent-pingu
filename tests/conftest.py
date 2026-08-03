"""Shared fixtures. Every test runs against a real scaffolded vault in tmp_path,
so the tests exercise vault_init.sh and the scripts together rather than a mock
of what we think the vault looks like."""

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))


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
    subprocess.run(
        ["bash", str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=tmp_path, check=True, capture_output=True,
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
def run_loop(repo, monkeypatch):
    """Invoke loop.py in-process against this repo, capturing stdout."""
    import loop

    def _run(*argv, **env):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return loop.main(["loop.py", *argv])

    return _run
