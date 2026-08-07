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

import gh_sync
import pingu

from conftest import BASH, set_home  # noqa: E402  — see their docstrings on Windows

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def write_settings(path, options, plugin="agent-pingu@skills-dir"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pluginConfigs": {plugin: {"options": options}}}), encoding="utf-8"
    )
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty HOME, so a real ~/.claude/settings.json cannot leak in.

    Outside `tmp_path`, because `tmp_path` *is* the repo in this suite and a home
    inside the repo is now refused as an attempted forgery — see `fake_home_for`.
    """
    fake = tmp_path.parent / (tmp_path.name + "-home")
    fake.mkdir(exist_ok=True)
    set_home(monkeypatch, fake)
    # Every option, not the two that happened to be under test: plugin_option
    # checks the env var first, so an ambient CLAUDE_PLUGIN_OPTION_GH_REPO made
    # test_no_gh_repo_means_gh_uses_the_git_remote fail against a clean repo.
    for option in ("AUTONOMY", "VAULT_DIR", "GH_REPO"):
        monkeypatch.delenv(f"CLAUDE_PLUGIN_OPTION_{option}", raising=False)
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


def no_home(monkeypatch):
    """Make `Path.home()` raise, the way a machine with no resolvable home does.

    One helper rather than two idioms. The second copy of this was written as
    `lambda: (_ for _ in ()).throw(RuntimeError(...))` — a generator-throw trick
    to get around lambda's ban on `raise` — which bought nothing the plain
    function above it had not already bought, and read like a puzzle.
    """
    def raise_it():
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(pingu.Path, "home", staticmethod(raise_it))


def test_an_undeterminable_home_degrades_to_the_repo_settings(project, monkeypatch):
    """`plugin_option` says it never raises, and `settings_files` is called
    outside the try that makes that true. `Path.home()` raises RuntimeError when
    no home can be resolved, so the promise held only on machines that have one.

    Found by the widened CI matrix, on Windows, where a test built its own `env`
    with `HOME` set and nothing else — and `ntpath.expanduser` reads `USERPROFILE`.
    The cause is contrived; the consequence is not. This is the SessionStart hook,
    and the two repo-scoped settings files that could have answered were never
    reached.
    """
    no_home(monkeypatch)
    # Not inherited from the `home` fixture, because that fixture's whole job is
    # to make `Path.home()` resolve — the opposite of what this test needs. So
    # the env clearing it does has to be repeated by hand. Omitting it made this
    # test fail under an ambient CLAUDE_PLUGIN_OPTION_AUTONOMY: `plugin_option`
    # reads the env var before any file. Exactly the flake the `home` fixture's
    # own docstring records, reintroduced three lines from the fix for it, and
    # caught by two reviewers rather than by the suite.
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_AUTONOMY", raising=False)

    local = project / ".claude" / "settings.local.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(
        '{"pluginConfigs": {"agent-pingu": {"options": {"autonomy": "gated"}}}}',
        encoding="utf-8",
    )
    assert pingu.plugin_option("autonomy", "full-loop") == "gated"
    # And the personal-scope lookup, which has nothing else to fall back to.
    assert pingu.plugin_option("autonomy", "full-loop", scope="user") == "full-loop"


def test_the_autonomy_floor_is_absent_when_no_home_resolves(project, monkeypatch):
    """A documented limit, pinned so it cannot become an undocumented one.

    ADR-0004 rule 2 says a repo may tighten autonomy but never loosen it, and
    implements that by reading the personal file at `scope="user"`. With no home
    there is no personal file to read, so `settings_files("user")` is empty, the
    default comes back, and the floor cannot fire — a repo-committed `full-loop`
    wins by default rather than by decision.

    Failing closed instead (assume `gated` when the personal scope is
    unreadable) was considered and rejected here: it would also fire for a
    merely malformed personal file, where
    `test_unreadable_settings_degrade_to_the_default` deliberately encodes the
    opposite instinct. The trade is written into ADR-0004's Consequences rather
    than left for someone to rediscover from this assertion.
    """
    no_home(monkeypatch)
    write_settings(project / ".claude" / "settings.json", {"autonomy": "full-loop"})
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_AUTONOMY", raising=False)

    assert pingu.autonomy() == ("full-loop", None)


def test_a_corrupt_higher_precedence_file_falls_through_to_a_valid_one(home, project):
    """Distinct from "the file is absent", which every other fixture here
    exercises instead. If someone later special-cased malformed settings — a
    warning, an abort — nothing would have caught the loss of this behaviour."""
    local = project / ".claude" / "settings.local.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("{ truncated", encoding="utf-8")
    write_settings(project / ".claude" / "settings.json", {"autonomy": "gated"})
    assert pingu.plugin_option("autonomy", "full-loop") == "gated"


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


def test_status_says_so_when_no_home_resolves(project, run_pingu, monkeypatch, capsys):
    """The degradation was silent, which is the part worth fixing.

    `settings_files()` drops the personal settings file when `Path.home()`
    raises. Everything downstream then behaves as though the user had simply
    declared nothing: ADR-0004's autonomy floor cannot fire, a personal
    `vault_dir` is ignored so the setup guard inspects a directory that does not
    exist and allows every edit, and nothing anywhere says a word.

    Silence was the right call inside `plugin_option`, which promises never to
    raise. It is the wrong call at session start, which is the one place the
    model and the user both read. Same shape as the unrecognised-autonomy
    warning two tests above: degrade, but say so.
    """
    no_home(monkeypatch)
    run_pingu("status")
    out = capsys.readouterr().out

    assert "home" in out.lower(), "the degradation is still silent"
    assert "personal" in out.lower(), "does not say what is being ignored"


def test_status_stays_quiet_when_home_resolves(home, project, run_pingu, capsys):
    """The other half, and the one that makes the warning worth having. A notice
    printed every session is one nobody reads by the third day."""
    run_pingu("status")
    assert "no home" not in capsys.readouterr().out.lower()


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
        [BASH, str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
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
        [BASH, str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=fresh, check=True, capture_output=True, env=env,
    )
    assert (fresh / "docs" / "elsewhere" / "context.md").is_file()


def test_a_vault_dir_env_var_that_escapes_the_repo_is_refused(home, tmp_path):
    """`VAULT_DIR` used to be expanded by the shell as `$REPO/$VAULT_DIR`, which
    is a second resolver — and the one place it visibly diverged from
    `vault_path()` is the containment check that keeps a vault inside the repo.
    Routing it through pingu is what makes this refusal apply to it too."""
    fresh = tmp_path / "escape"
    fresh.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fresh, check=True)
    outside = tmp_path / "outside"

    env = dict(os.environ, HOME=str(home), VAULT_DIR="../outside")
    env.pop("CLAUDE_PLUGIN_OPTION_VAULT_DIR", None)
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=fresh, check=True, capture_output=True, text=True, env=env,
    )

    assert not outside.exists(), "vault_init.sh scaffolded outside the repo"
    assert (fresh / "docs" / "vault" / "context.md").is_file()
    # Refusing is half of it. Refusing silently is the failure mode this repo
    # keeps rediscovering, so the message has to reach the caller.
    assert "outside the repo" in result.stderr


def test_vault_init_says_when_an_env_var_vault_will_not_be_found_later(home, tmp_path):
    """`VAULT_DIR` dies with the process; `pingu` reads the settings files. So the
    two can agree during scaffolding and disagree in every session afterwards,
    and the symptom is an empty vault rather than an error. Same trade as the
    warnings `pingu status` already prints: degrade, but say so."""
    fresh = tmp_path / "divergent"
    fresh.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fresh, check=True)

    env = dict(os.environ, HOME=str(home), VAULT_DIR="docs/knowledge")
    env.pop("CLAUDE_PLUGIN_OPTION_VAULT_DIR", None)
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=fresh, check=True, capture_output=True, text=True, env=env,
    )

    assert (fresh / "docs" / "knowledge" / "context.md").is_file()
    assert "vault_dir" in result.stdout and "docs/knowledge" in result.stdout
    assert "this run only" in result.stdout


def test_no_such_notice_when_settings_and_the_env_var_agree(home, tmp_path):
    """The paired assertion, and it carries as much weight as the notice itself.
    A warning printed on a correct setup is one nobody reads by the third day."""
    fresh = tmp_path / "agreeing"
    fresh.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fresh, check=True)
    write_settings(fresh / ".claude" / "settings.json", {"vault_dir": "docs/knowledge"})

    env = dict(os.environ, HOME=str(home), VAULT_DIR="docs/knowledge")
    env.pop("CLAUDE_PLUGIN_OPTION_VAULT_DIR", None)
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "scripts" / "vault_init.sh")],
        cwd=fresh, check=True, capture_output=True, text=True, env=env,
    )

    assert (fresh / "docs" / "knowledge" / "context.md").is_file()
    assert "this run only" not in result.stdout


# ------------------------------------------------------------------- gh_repo

def test_gh_repo_is_read_from_settings(home, project):
    """Third instance of the same defect: the option was documented, and read
    only from an env var that is never exported."""
    write_settings(home / ".claude" / "settings.json", {"gh_repo": "acme/widgets"})
    assert gh_sync.repo_flag() == ["--repo", "acme/widgets"]


def test_no_gh_repo_means_gh_uses_the_git_remote(home, project):
    assert gh_sync.repo_flag() == []
