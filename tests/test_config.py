"""Plugin configuration resolution.

`${user_config.KEY}` does not interpolate in a SKILL.md body — it reaches the
model as that literal string — and `CLAUDE_PLUGIN_OPTION_*` is not exported to
the Bash tool either. Both were verified against a real session. So the options
declared in plugin.json's userConfig are only real if this script goes and reads
them, which is what these tests pin down.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

import pingu

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def write_settings(path, options, plugin="agent-pingu@skills-dir"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pluginConfigs": {plugin: {"options": options}}}), encoding="utf-8"
    )
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty HOME, so a real ~/.claude/settings.json cannot leak in."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_AUTONOMY", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_VAULT_DIR", raising=False)
    return fake


@pytest.fixture
def project(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    return repo


# ------------------------------------------------------------- plugin_option

def test_an_undeclared_option_falls_back_to_its_default(home, project):
    assert pingu.plugin_option("autonomy", "full-loop") == "full-loop"


def test_an_option_declared_in_user_settings_is_found(home, project):
    write_settings(home / ".claude" / "settings.json", {"autonomy": "gated"})
    assert pingu.plugin_option("autonomy", "full-loop") == "gated"


def test_project_settings_beat_user_settings(home, project):
    write_settings(home / ".claude" / "settings.json", {"autonomy": "full-loop"})
    write_settings(project / ".claude" / "settings.json", {"autonomy": "gated"})
    assert pingu.plugin_option("autonomy", "full-loop") == "gated"


def test_local_settings_beat_project_settings(home, project):
    write_settings(project / ".claude" / "settings.json", {"autonomy": "full-loop"})
    write_settings(project / ".claude" / "settings.local.json", {"autonomy": "gated"})
    assert pingu.plugin_option("autonomy", "full-loop") == "gated"


@pytest.mark.parametrize("key", ["agent-pingu", "agent-pingu@skills-dir", "agent-pingu@somewhere-else"])
def test_the_source_suffix_on_the_plugin_key_is_ignored(home, project, key):
    """How the plugin was discovered decides that suffix, not the user. Matching
    the whole key would make the setting silently stop working on a reinstall."""
    write_settings(home / ".claude" / "settings.json", {"autonomy": "gated"}, plugin=key)
    assert pingu.plugin_option("autonomy", "full-loop") == "gated"


def test_another_plugins_options_are_not_read(home, project):
    write_settings(home / ".claude" / "settings.json", {"autonomy": "gated"}, plugin="other-plugin")
    assert pingu.plugin_option("autonomy", "full-loop") == "full-loop"


def test_unreadable_settings_degrade_to_the_default(home, project):
    """This runs inside the SessionStart hook, where raising costs the user the
    whole session over a stray comma in a file this plugin does not own."""
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json at all", encoding="utf-8")
    assert pingu.plugin_option("autonomy", "full-loop") == "full-loop"


def test_a_settings_file_without_plugin_configs_is_skipped(home, project):
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
    assert pingu.plugin_option("autonomy", "full-loop") == "full-loop"


def test_an_empty_value_does_not_shadow_the_default(home, project):
    """plugin.json marks gh_repo optional, and an untouched optional field can
    land in settings as an empty string."""
    write_settings(home / ".claude" / "settings.json", {"autonomy": ""})
    assert pingu.plugin_option("autonomy", "full-loop") == "full-loop"


def test_the_env_var_wins_when_something_does_export_it(home, project, monkeypatch):
    write_settings(home / ".claude" / "settings.json", {"autonomy": "gated"})
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_AUTONOMY", "full-loop")
    assert pingu.plugin_option("autonomy", "full-loop") == "full-loop"


# ------------------------------------------------------------------ autonomy

def test_autonomy_defaults_to_full_loop(home, project):
    assert pingu.autonomy() == ("full-loop", None)


def test_autonomy_reads_a_declared_level(home, project):
    write_settings(home / ".claude" / "settings.json", {"autonomy": "gated"})
    assert pingu.autonomy() == ("gated", None)


def test_an_unrecognised_level_falls_back_and_reports_itself(home, project):
    """Silently treating a typo as the default is how someone runs unattended
    for a week believing they set gated."""
    write_settings(home / ".claude" / "settings.json", {"autonomy": "Gated "})
    assert pingu.autonomy() == ("full-loop", "Gated ")


def test_every_documented_level_is_accepted(home, project):
    for level in pingu.AUTONOMY_LEVELS:
        write_settings(home / ".claude" / "settings.json", {"autonomy": level})
        assert pingu.autonomy() == (level, None)


# -------------------------------------------------------------------- status

def test_status_states_the_autonomy_level(home, project, run_pingu, capsys):
    run_pingu("status")
    assert "autonomy: full-loop" in capsys.readouterr().out


def test_status_states_a_configured_autonomy_level(home, project, run_pingu, capsys):
    write_settings(home / ".claude" / "settings.json", {"autonomy": "gated"})
    run_pingu("status")
    out = capsys.readouterr().out
    assert "autonomy: gated" in out
    assert "stops after every phase" in out


def test_status_warns_about_an_unrecognised_level(home, project, run_pingu, capsys):
    write_settings(home / ".claude" / "settings.json", {"autonomy": "yolo"})
    run_pingu("status")
    out = capsys.readouterr().out
    assert "yolo" in out
    assert "autonomy: full-loop" in out


def test_status_survives_a_broken_settings_file(home, project, run_pingu, capsys):
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{{{", encoding="utf-8")
    assert run_pingu("status") == 0
    assert "autonomy: full-loop" in capsys.readouterr().out


# ----------------------------------------------------------------- vault_dir

def test_vault_dir_is_read_from_settings(home, project):
    """Same defect as autonomy, same fix — the option was documented as working
    and read only from an env var nothing exports."""
    write_settings(home / ".claude" / "settings.json", {"vault_dir": "docs/knowledge"})
    assert pingu.vault_path() == project / "docs" / "knowledge"


def test_vault_dir_defaults_to_docs_vault(home, project):
    assert pingu.vault_path() == project / "docs" / "vault"


def test_vault_init_puts_the_vault_where_settings_say(home, tmp_path):
    """The shell scaffolder and the Python tooling have to agree on where the
    vault is, or the loop scaffolds one directory and then reads another."""
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fresh, check=True)
    write_settings(fresh / ".claude" / "settings.json", {"vault_dir": "docs/knowledge"})

    env = dict(os.environ, HOME=str(home))
    env.pop("CLAUDE_PLUGIN_OPTION_VAULT_DIR", None)
    env.pop("VAULT_DIR", None)
    subprocess.run(
        ["bash", str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=fresh, check=True, capture_output=True, env=env,
    )
    assert (fresh / "docs" / "knowledge" / "context.md").is_file()
    assert not (fresh / "docs" / "vault").exists()


def test_an_explicit_vault_dir_env_var_still_overrides_settings(home, tmp_path):
    """Documented in the script's own header, and the escape hatch for scaffolding
    a second vault without editing settings."""
    fresh = tmp_path / "fresh2"
    fresh.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fresh, check=True)
    write_settings(fresh / ".claude" / "settings.json", {"vault_dir": "docs/knowledge"})

    env = dict(os.environ, HOME=str(home), VAULT_DIR="docs/elsewhere")
    subprocess.run(
        ["bash", str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=fresh, check=True, capture_output=True, env=env,
    )
    assert (fresh / "docs" / "elsewhere" / "context.md").is_file()


# ------------------------------------------------------------------- gh_repo

def test_gh_repo_is_read_from_settings(home, project):
    """Third instance of the same defect: the option was documented, and read
    only from an env var that is never exported."""
    import gh_sync

    write_settings(home / ".claude" / "settings.json", {"gh_repo": "acme/widgets"})
    assert gh_sync.repo_flag() == ["--repo", "acme/widgets"]


def test_no_gh_repo_means_gh_uses_the_git_remote(home, project):
    import gh_sync

    assert gh_sync.repo_flag() == []
