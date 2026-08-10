"""The marketplace manifest, and the install path it promises.

Distribution is the other half of "everyone can use it". Before this, the only
install was a git clone plus one manual `rm -rf .../.git` that the README itself
called not optional — and skipping it produced a directory that *looked* right
while the plugin never loaded. Silent failure, in the first thing a new user
touches.

These are schema and consistency checks. They cannot prove the install works;
that was proved by running it (`marketplace add` -> `list` -> `install` ->
`uninstall` -> `remove`) against the real CLI, which is the only thing that could
have caught "install instructions referencing a zip nothing built".
"""

import json

import pytest

from conftest import PLUGIN_ROOT

MARKETPLACE = PLUGIN_ROOT / ".claude-plugin" / "marketplace.json"
MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"


@pytest.fixture(scope="module")
def marketplace():
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_the_marketplace_declares_the_fields_the_loader_requires(marketplace):
    for field in ("name", "owner", "plugins"):
        assert field in marketplace, f"marketplace.json has no {field!r}"
    assert marketplace["plugins"], "marketplace.json lists no plugins"
    for entry in marketplace["plugins"]:
        assert "name" in entry and "source" in entry


def test_the_entry_points_at_this_repo(marketplace):
    """`source` paths resolve against the directory containing `.claude-plugin/`,
    which here is the repo root — this repo *is* the plugin."""
    entry = marketplace["plugins"][0]
    assert entry["source"] == "./", (
        f"the plugin source is {entry['source']!r}; this repo is the plugin, so "
        f"it should be './'")
    assert (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").is_file()


def test_the_marketplace_entry_does_not_carry_its_own_version(marketplace, manifest):
    """One version, in plugin.json only.

    A marketplace entry may pin `version`, and if it does it wins. Setting it in
    both places is a second resolver — the exact shape ADR-0001 exists to forbid
    — and its failure mode is the ugly kind: the two agree until someone bumps
    one, and then users silently stop receiving updates while the manifest says
    they should be.

    Verified by installing from the real marketplace: `claude plugin list`
    reported the manifest's version, which could only have come from
    plugin.json. Re-checked at 0.5.0 against a GitHub-sourced install, not a
    local path — the README documents the GitHub form and only that form is
    evidence for it.
    """
    assert "version" in manifest, "plugin.json must be the one place a version lives"
    for entry in marketplace["plugins"]:
        assert "version" not in entry, (
            f"the marketplace entry for {entry['name']!r} pins its own version, so "
            f"plugin.json's is now dead. Keep the version in plugin.json alone.")


def test_the_marketplace_name_is_not_reserved(marketplace):
    """Reserved names are re-checked on every load, not only when added, so a
    marketplace that takes one stops loading rather than failing at install."""
    reserved = {
        "claude-code-marketplace", "claude-code-plugins", "claude-plugins-official",
        "claude-plugins-community", "claude-community", "anthropic-marketplace",
        "anthropic-plugins", "agent-skills", "anthropic-agent-skills",
        "knowledge-work-plugins", "life-sciences", "claude-for-legal",
        "claude-for-financial-services", "financial-services-plugins",
        "first-party-plugins", "healthcare",
    }
    assert marketplace["name"] not in reserved


def test_the_readme_documents_the_marketplace_install():
    """The pair: shipping a marketplace nobody is told about installs nobody.

    Named commands rather than the word "marketplace", so the check fails when
    the instructions go stale rather than when the prose is reworded.
    """
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    assert "/plugin marketplace add" in readme, (
        "README never tells anyone how to add the marketplace")
    assert "/plugin install" in readme, (
        "README never tells anyone how to install from it")


def test_the_readme_still_warns_about_the_vendored_install_footgun():
    """The marketplace does not retire the vendored install, so it does not
    retire its warning either. A committed gitlink gives teammates an empty
    directory that looks correct and never loads."""
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    if ".claude/skills/agent-pingu" not in readme:
        pytest.skip("the vendored install is no longer documented")
    assert "rm -rf" in readme, (
        "the vendored install is still documented but its `rm -rf .git` step is "
        "gone — without it teammates get an empty directory and no error")
