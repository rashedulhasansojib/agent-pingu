"""Tests for the skill definitions themselves.

`loop/SKILL.md` states the invariant "Only this skill sequences them. A phase
never invokes another phase." Nothing enforces that at runtime — dispatch is the
model's judgement, driven by the `description` field. These tests guard the one
lever that actually decides it.
"""

import re

import pytest

from conftest import PLUGIN_ROOT

PHASES = ["talk", "research", "adr", "plan", "diagnose", "execute", "verify", "retro"]

# Phrases that claim a raw, unscoped request. These belong to the router, which
# has to pick the lane before any phase is the right one.
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
