"""Tests for the skill definitions themselves.

`loop/SKILL.md` states the invariant "Only this skill sequences them. A phase
never invokes another phase." Nothing enforces that at runtime — dispatch is the
model's judgement, driven by the `description` field. These tests guard the one
lever that actually decides it.
"""

import re

import pytest

from conftest import PLUGIN_ROOT

# The eight phases that compete with the router for a request. `setup` is
# deliberately absent: it is the gate the router defers *to*, so it should keep
# triggering on "set up the vault" and on SETUP NEEDED without asking first.
PHASES = ["talk", "research", "adr", "plan", "diagnose", "execute", "verify", "retro"]

# Phrases that claim a raw, unscoped request. These belong to the router, which
# has to pick the lane before any phase is the right one. This list is a
# regression guard over the phrasings that were actually removed — it will not
# catch a newly invented pushy phrase. The `loop` mention above is the general
# check; treat this one as a reminder, not a safety net.
ROUTER_TERRITORY = [
    r"whenever someone describes something they want built",
    r"whenever someone says something is broken",
    r"someone asks to break down work",
    r'someone says "start building"',
    r"when starting a new project",
]


def description_of(skill):
    text = (PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    assert match, f"{skill} has no description"
    return match.group(1)


@pytest.mark.parametrize("skill", PHASES)
def test_a_phase_points_raw_requests_at_the_router(skill):
    """A phase description must name `loop` so dispatch has somewhere to defer
    to. Without it, `talk` and `plan` compete with the router for the same
    request and the lane, run log, and SETUP NEEDED gate are all skipped."""
    assert "loop" in description_of(skill).lower(), (
        f"{skill}'s description never mentions the loop router")


@pytest.mark.parametrize("skill", PHASES)
def test_a_phase_does_not_claim_an_unscoped_request(skill):
    description = description_of(skill).lower()
    for phrase in ROUTER_TERRITORY:
        assert not re.search(phrase, description), (
            f"{skill} claims the router's territory: {phrase!r}")


def test_the_router_still_claims_everything_else():
    """Narrowing the phases only works if `loop` remains the catch-all."""
    description = description_of("loop").lower()
    assert "build, fix, ship, refactor, investigate, or add anything" in description


# --------------------------------------------------------------- frontmatter yaml

def frontmatter_lines(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    return text[3:end].splitlines() if end != -1 else []


def all_component_files():
    for pattern in ("skills/*/SKILL.md", "agents/*.md"):
        yield from sorted(PLUGIN_ROOT.glob(pattern))


@pytest.mark.parametrize(
    "path", list(all_component_files()), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_frontmatter_has_no_unquoted_colon_space(path):
    """`key: some text: more text` is not valid YAML.

    Claude Code does not fall back gracefully — it drops *every* frontmatter
    field for that file, so the skill loads nameless and description-less and
    simply never triggers. It fails silently at runtime, which is why this is a
    test and not a code review note. Found by `claude plugin validate` after
    three descriptions were rewritten with a colon in the prose.
    """
    for line in frontmatter_lines(path):
        key, sep, value = line.partition(":")
        if not sep or line.startswith((" ", "\t", "#")):
            continue
        value = value.strip()
        if value.startswith(('"', "'")):
            continue
        assert ": " not in value, (
            f"{path.parent.name}/{path.name} — '{key}' contains an unquoted "
            f'": " so the whole frontmatter block fails to parse. '
            f"Use an em dash, or quote the value.")
