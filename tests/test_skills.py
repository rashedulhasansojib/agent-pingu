"""Tests for the skill definitions themselves.

`pingu/SKILL.md` states the invariant "Only this skill sequences them. A phase
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
# catch a newly invented pushy phrase. The `pingu` mention above is the general
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
    """A phase description must name `pingu` so dispatch has somewhere to defer
    to. Without it, `talk` and `plan` compete with the router for the same
    request and the lane, run log, and SETUP NEEDED gate are all skipped."""
    assert "pingu" in description_of(skill).lower(), (
        f"{skill}'s description never mentions the pingu router")


@pytest.mark.parametrize("skill", PHASES)
def test_a_phase_does_not_claim_an_unscoped_request(skill):
    description = description_of(skill).lower()
    for phrase in ROUTER_TERRITORY:
        assert not re.search(phrase, description), (
            f"{skill} claims the router's territory: {phrase!r}")


def test_the_router_still_claims_everything_else():
    """Narrowing the phases only works if `pingu` remains the catch-all."""
    description = description_of("pingu").lower()
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


# ------------------------------------------------------------------ lane table

def lane_table():
    """The lane table from pingu/SKILL.md, as {lane: (phases, optional)}.

    Mirrors the parse ccw's check-skills-index.mjs does over its own index:
    read the human-facing document, and diff it against the machine-readable
    structure the tooling actually runs on.
    """
    text = (PLUGIN_ROOT / "skills" / "pingu" / "SKILL.md").read_text(encoding="utf-8")
    # Scope to the "Pick the lane" section. The agents table further down has
    # the same row shape (`| \`architect\` | ... |`) and would otherwise be
    # parsed as lanes named after agents.
    section = re.search(r"^## Pick the lane$(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert section, "pingu/SKILL.md no longer has a '## Pick the lane' section"
    lanes = {}
    for row in re.finditer(r"^\|\s*`(\w+)`\s*\|([^|]+)\|", section.group(1), re.MULTILINE):
        lane, cell = row.group(1), row.group(2)
        phases, optional = [], set()
        for token in cell.split("->"):
            # "talk (brief)" and "retro (**required**)" are annotations for the
            # reader; a trailing ? is the table's mark for a skippable phase.
            token = re.sub(r"\([^)]*\)", "", token).replace("*", "").strip()
            if not token:
                continue
            if token.endswith("?"):
                token = token[:-1]
                optional.add(token)
            phases.append(token)
        lanes[lane] = (tuple(phases), optional)
    return lanes


def test_the_lane_table_is_parseable_at_all():
    """If the table's shape changes, the tests below would silently pass on an
    empty dict. Anchor them."""
    assert set(lane_table()) == {"feature", "bug", "incident", "refactor", "spike", "chore"}


@pytest.mark.parametrize("lane", ["feature", "bug", "incident", "refactor", "spike", "chore"])
def test_lane_phases_match_the_code(lane):
    """`pingu/SKILL.md`'s table and `LANES` in pingu.py are the same state machine
    written twice. Order matters — it is what infer_phase walks."""
    import pingu as pingu_py

    documented, _ = lane_table()[lane]
    assert pingu_py.LANES[lane] == documented, (
        f"{lane}: SKILL.md says {documented}, LANES says {pingu_py.LANES[lane]}")


@pytest.mark.parametrize("lane", ["feature", "bug", "incident", "refactor", "spike", "chore"])
def test_skippable_phases_match_the_code(lane):
    """A `?` in the table is the same claim as membership in OPTIONAL. A phase
    documented as skippable but not in OPTIONAL wedges the state machine."""
    import pingu as pingu_py

    _, documented = lane_table()[lane]
    assert set(pingu_py.OPTIONAL.get(lane, frozenset())) == documented, (
        f"{lane}: SKILL.md marks {documented or '{}'} skippable, "
        f"OPTIONAL has {set(pingu_py.OPTIONAL.get(lane, frozenset())) or '{}'}")


# ---------------------------------------------------------------------- agents

READ_ONLY_AGENTS = ["architect", "security-reviewer", "reviewer-standards", "reviewer-spec"]


def agent_frontmatter(name):
    lines = frontmatter_lines(PLUGIN_ROOT / "agents" / f"{name}.md")
    fields, current = {}, None
    for line in lines:
        if line.startswith(("  -", "\t-")):
            fields.setdefault(current, []).append(line.split("-", 1)[1].strip())
            continue
        key, sep, value = line.partition(":")
        if sep:
            current = key.strip()
            fields[current] = value.strip() if value.strip() else []
    return fields


@pytest.mark.parametrize("name", READ_ONLY_AGENTS)
def test_read_only_agents_use_a_tools_allowlist(name):
    """An allowlist denies by default; `disallowedTools` only removes what it
    names. For agents whose entire job is to read and report, the allowlist is
    the honest expression of that."""
    fields = agent_frontmatter(name)

    assert "tools" in fields, f"{name} still relies on inheritance"
    allowed = {t.strip() for t in fields["tools"].split(",")}
    assert not (allowed & {"Write", "Edit", "NotebookEdit"}), (
        f"{name} is meant to report, not edit: {allowed}")
    assert "Read" in allowed


@pytest.mark.parametrize("name", READ_ONLY_AGENTS)
def test_an_allowlisted_agent_does_not_also_carry_a_denylist(name):
    """Both is confusing and implies the denylist is doing work it isn't."""
    assert "disallowedTools" not in agent_frontmatter(name)


def test_agents_that_may_need_mcp_tools_keep_their_inherited_pool():
    """A `tools:` allowlist strips every MCP tool, not just built-ins. These two
    do open-ended work in someone else's repo, where a project's MCP server may
    be exactly what they need, so they stay on inheritance deliberately."""
    for name in ("senior-engineer", "sqa"):
        assert "tools" not in agent_frontmatter(name), (
            f"{name} was given an allowlist, which silently removes MCP tools")


@pytest.mark.parametrize("name,expected", [
    ("architect", {"vault", "domain-modeling"}),
    ("senior-engineer", {"vault"}),
])
def test_agents_preload_the_disciplines_they_depend_on(name, expected):
    """Both agents are told in prose to follow the vault's conventions. Preloading
    injects that content at startup instead of hoping they go and read it."""
    assert set(agent_frontmatter(name).get("skills", [])) == expected


@pytest.mark.parametrize("name", ["reviewer-standards", "reviewer-spec"])
def test_the_blind_reviewers_preload_nothing(name):
    """Preloading `vault` would hand both reviewers a map to `brief.md`. The
    separation is already only a convention; do not spend it for convenience."""
    assert not agent_frontmatter(name).get("skills")


# ------------------------------------------------------------------ gate table

def gate_table():
    """The phases listed in pingu/SKILL.md's gate table, in order."""
    text = (PLUGIN_ROOT / "skills" / "pingu" / "SKILL.md").read_text(encoding="utf-8")
    section = re.search(r"^## Gates$(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert section, "pingu/SKILL.md no longer has a '## Gates' section"
    rows = re.findall(r"^\|\s*(\w[\w-]*)\s*\|", section.group(1), re.MULTILINE)
    return [r for r in rows if r != "Phase"]


def test_the_gate_table_is_parseable_at_all():
    assert len(gate_table()) == 9, f"parsed {gate_table()}"


def test_every_documented_gate_is_declared_in_code():
    """`pingu gate <phase>` must cover exactly the phases the table promises.
    A documented gate with no declaration is the state this whole feature
    existed to end."""
    import pingu as pingu_py

    assert gate_table() == list(pingu_py.GATES)


def test_the_skill_points_at_the_runner_rather_than_asking_for_self_assessment():
    """The gate section used to instruct the model to decide whether its own
    gate was met. It has to name the command instead."""
    text = (PLUGIN_ROOT / "skills" / "pingu" / "SKILL.md").read_text(encoding="utf-8")
    section = re.search(r"^## Gates$(.*?)^## ", text, re.MULTILINE | re.DOTALL).group(1)

    assert "pingu gate" in section


# ------------------------------------------------------------------- identity

PLUGIN_NAME = "agent-pingu"


def test_the_manifest_name_matches_the_directory():
    """A skills-directory plugin is loaded as `<dirname>@skills-dir`, and its
    skills are namespaced by the manifest `name`. If the two disagree, the docs
    tell people to type a prefix that does not resolve."""
    import json

    manifest = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

    assert manifest["name"] == PLUGIN_NAME
    assert PLUGIN_ROOT.name == PLUGIN_NAME, (
        f"directory is {PLUGIN_ROOT.name!r}, manifest says {manifest['name']!r}")


@pytest.mark.parametrize("doc", ["README.md", "MANUAL.md"])
def test_no_stale_project_name_survives_the_rename(doc):
    text = (PLUGIN_ROOT / doc).read_text(encoding="utf-8").lower()

    assert "agentic-loop" not in text, f"{doc} still names the old plugin"


@pytest.mark.parametrize("doc", ["README.md", "MANUAL.md"])
def test_skill_invocations_use_the_current_namespace(doc):
    """Plugin skills resolve as `<plugin>:<skill>`. Documenting a bare `/adr`
    or a stale prefix sends people to a command that does not exist."""
    text = (PLUGIN_ROOT / doc).read_text(encoding="utf-8")

    for match in re.findall(r"`/([a-z-]+):", text):
        assert match == PLUGIN_NAME, f"{doc} documents /{match}: — should be /{PLUGIN_NAME}:"
