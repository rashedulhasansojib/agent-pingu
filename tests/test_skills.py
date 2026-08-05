"""Tests for the skill definitions themselves.

`start/SKILL.md` states the invariant "Only this skill sequences them. A phase
never invokes another phase." Nothing enforces that at runtime — dispatch is the
model's judgement, driven by the `description` field. These tests guard the one
lever that actually decides it.
"""

import re
import subprocess

import pytest

from conftest import PLUGIN_ROOT

# The eight phases that compete with the router for a request. `setup` is
# deliberately absent: it is the gate the router defers *to*, so it should keep
# triggering on "set up the vault" and on SETUP NEEDED without asking first.
PHASES = ["talk", "research", "adr", "plan", "diagnose", "execute", "verify", "retro"]

# Phrases that claim a raw, unscoped request. These belong to the router, which
# has to pick the lane before any phase is the right one. This list is a
# regression guard over the phrasings that were actually removed — it will not
# catch a newly invented pushy phrase. The `start` mention above is the general
# check; treat this one as a reminder, not a safety net.
ROUTER_TERRITORY = [
    r"whenever someone describes something they want built",
    r"whenever someone says something is broken",
    r"someone asks to break down work",
    r'someone says "start building"',
    r"when starting a new project",
]


MARKDOWN_SOURCES = sorted(
    list((PLUGIN_ROOT / "skills").rglob("*.md")) + list((PLUGIN_ROOT / "agents").rglob("*.md"))
)


@pytest.mark.parametrize("path", MARKDOWN_SOURCES, ids=lambda p: str(p.relative_to(PLUGIN_ROOT)))
def test_no_skill_relies_on_user_config_interpolation(path):
    """`${user_config.KEY}` does not interpolate in a skill or agent body — it
    reaches the model as that literal string, verified against a real session.

    `start` carried `${user_config.autonomy}` for eleven commits, so the whole
    full-loop/gated setting silently did nothing while two documents described
    it as working. Read plugin options through `pingu status`, which resolves
    them from the settings file.
    """
    text = path.read_text(encoding="utf-8")
    hits = re.findall(r"\$\{user_config\.\w+\}", text)
    assert not hits, (
        f"{path.relative_to(PLUGIN_ROOT)} expects {hits} to be substituted. It is not. "
        "Resolve the option in scripts/pingu.py and surface it via `pingu status`."
    )


def test_the_router_reads_autonomy_from_the_status_output():
    """The counterpart to the test above: having removed the placeholder, the
    router still has to learn the level from somewhere."""
    text = (PLUGIN_ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    assert "autonomy" in text, "the router no longer mentions autonomy at all"
    assert re.search(r"`pingu status`[^\n]*autonomy|autonomy[^\n]*`pingu status`", text), (
        "the router mentions autonomy but does not say to read it from `pingu status`"
    )
    for level in ("full-loop", "gated"):
        assert level in text, f"the router does not say what {level} does"


def description_of(skill):
    text = (PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    assert match, f"{skill} has no description"
    return match.group(1)


@pytest.mark.parametrize("skill", PHASES)
def test_a_phase_points_raw_requests_at_the_router(skill):
    """A phase description must name `start` so dispatch has somewhere to defer
    to. Without it, `talk` and `plan` compete with the router for the same
    request and the lane, run log, and SETUP NEEDED gate are all skipped."""
    # Backticked, deliberately. The router is called `start`, and asserting on a
    # bare "start" would pass on "starts a run log", "start building", or
    # "starting a new project" — the check would look green while meaning nothing.
    assert "`start`" in description_of(skill), (
        f"{skill}'s description never defers to the `start` router")


@pytest.mark.parametrize("skill", PHASES)
def test_a_phase_does_not_claim_an_unscoped_request(skill):
    description = description_of(skill).lower()
    for phrase in ROUTER_TERRITORY:
        assert not re.search(phrase, description), (
            f"{skill} claims the router's territory: {phrase!r}")


def test_the_router_still_claims_everything_else():
    """Narrowing the phases only works if `start` remains the catch-all."""
    description = description_of("start").lower()
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
    """The lane table from start/SKILL.md, as {lane: (phases, optional)}.

    Mirrors the parse ccw's check-skills-index.mjs does over its own index:
    read the human-facing document, and diff it against the machine-readable
    structure the tooling actually runs on.
    """
    text = (PLUGIN_ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    # Scope to the "Pick the lane" section. The agents table further down has
    # the same row shape (`| \`architect\` | ... |`) and would otherwise be
    # parsed as lanes named after agents.
    section = re.search(r"^## Pick the lane$(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert section, "start/SKILL.md no longer has a '## Pick the lane' section"
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
    """`start/SKILL.md`'s table and `LANES` in pingu.py are the same state machine
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
    """The phases listed in start/SKILL.md's gate table, in order."""
    text = (PLUGIN_ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    section = re.search(r"^## Gates$(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert section, "start/SKILL.md no longer has a '## Gates' section"
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
    text = (PLUGIN_ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
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


def fenced_blocks(text):
    """Every fenced block's body.

    Scans line by line rather than pairing ``` with a regex: the naive pattern
    only matches fences opened with a bare ```, so a ```bash block earlier in
    the file shifts every subsequent pair and the block you wanted is never
    seen. That is not hypothetical — the first version of the test below matched
    zero blocks and passed happily.
    """
    blocks, current = [], None
    for line in text.splitlines():
        if line.startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append("\n".join(current))
                current = None
        elif current is not None:
            current.append(line)
    return blocks


def test_documented_status_output_matches_what_status_prints(repo, run_pingu, capsys):
    """Transcripts in the docs go stale silently, because nothing runs them.

    The walkthrough showed a `pingu status` block that predated the autonomy
    line, so it described output the tool no longer produces — and autonomy was
    the very thing that had just been fixed. Compare against a real run.
    """
    # Most status lines depend on vault state — SETUP NEEDED, blocked tasks,
    # unsynced IDs — and a transcript of one state should not have to show
    # another's. Derive the lines that appear regardless by running against two
    # real vaults in different states and intersecting, rather than assuming
    # which ones those are.
    def status_lines():
        run_pingu("status")
        return [l for l in capsys.readouterr().out.splitlines() if l.startswith("[pingu]")]

    def prefixes(lines):
        return {l.split(":")[0] + ":" for l in lines}

    # Both states come from the scaffolded fixture, not from whatever vault this
    # repo happens to hold. An earlier version read the plugin's own vault and
    # broke the moment that stopped existing — a test depending on incidental
    # repo state, which is the thing this whole file exists to prevent.
    seeded = prefixes(status_lines())
    for path in (repo / "docs" / "vault").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "status: template" in text:
            path.write_text(text.replace("status: template", "status: ready"), encoding="utf-8")
    real = status_lines()
    filled = prefixes(real)

    required = seeded & filled
    assert "[pingu] autonomy:" in required, "status no longer always reports autonomy"

    checked = 0
    for doc in ("WALKTHROUGH.md", "MANUAL.md", "README.md"):
        text = (PLUGIN_ROOT / doc).read_text(encoding="utf-8")
        for block in fenced_blocks(text):
            # Any block quoting a status line, not only those in the current
            # format: MANUAL showed `[pingu] phase: setup` from an older shape,
            # which a stricter match skipped and so never flagged as stale.
            if not any(l.startswith("[pingu]") and "phase:" in l
                       for l in block.splitlines()):
                continue
            checked += 1
            missing = [p for p in required if p not in block]
            assert not missing, (
                f"{doc} shows a `pingu status` transcript missing {missing}. "
                f"A real run prints: {real}")
    assert checked, "no status transcript found to check — has the doc changed shape?"


AGENT_NAMES = sorted(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))


def test_the_router_dispatches_agents_by_their_namespaced_name():
    """Plugin agents resolve as `<plugin>:<agent>`, exactly like plugin skills.
    A fresh session lists `agent-pingu:reviewer-standards`; the bare
    `reviewer-standards` is rejected outright, so the delegation just fails.

    The agent table names them bare, which reads naturally — so the router has
    to say somewhere that the dispatch name carries the prefix.
    """
    text = (PLUGIN_ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    assert f"{PLUGIN_NAME}:" in text, (
        "start/SKILL.md never mentions the plugin prefix, so the router will "
        "dispatch bare agent names and every delegation will fail")
    assert re.search(rf"subagent_type[^\n]*{PLUGIN_NAME}:", text), (
        "start/SKILL.md should show the prefix on subagent_type specifically")


@pytest.mark.parametrize("skill", ["start", "verify"])
def test_a_skill_that_dispatches_agents_names_the_prefix(skill):
    """`verify` is where the four reviewers are actually dispatched, so it needs
    the namespacing rule as much as the router does — a bare `reviewer-standards`
    is rejected outright and the whole phase silently does nothing."""
    text = (PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert f"{PLUGIN_NAME}:" in text, (
        f"{skill}/SKILL.md dispatches agents but never shows the {PLUGIN_NAME}: prefix")


def test_verify_says_to_freeze_the_tree():
    """Reviewers read the working tree. A commit landing mid-review makes their
    findings describe a state that no longer exists — which happened on the first
    real run, and cost one reviewer most of its report."""
    text = (PLUGIN_ROOT / "skills" / "verify" / "SKILL.md").read_text(encoding="utf-8")
    assert re.search(r"[Ff]reeze the tree", text), (
        "verify/SKILL.md no longer tells the phase to hold the tree still while "
        "the reviewers read it")


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_every_agent_the_router_names_actually_exists(name):
    """The table is hand-written; a renamed agent file would leave it pointing
    at a subagent type that does not resolve."""
    text = (PLUGIN_ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    assert f"`{name}`" in text, f"agents/{name}.md is not in the router's agent table"


# ------------------------------------------------------------------- layout

def tracked_files(*paths):
    """What git actually ships, which is the only honest answer to "what is in
    this repo". Two layout guards read the filesystem instead and both broke on
    things that merely happened to be present."""
    return subprocess.run(
        ["git", "ls-files", *paths],
        cwd=PLUGIN_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()


def layout_block():
    """The fenced block under README's `## Layout` heading."""
    text = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    section = re.search(r"^## Layout$.*?^```\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    assert section, "README no longer has a '## Layout' fenced block"
    return section.group(1)


def test_the_layout_block_lists_every_directory_that_ships():
    """A layout diagram nobody checks is a diagram that quietly goes stale — it
    already had, missing hooks/, templates/, .claude-plugin/ and .github/."""
    block = layout_block()

    # What git tracks, not what the filesystem holds. Reading the directory made
    # the test demand the README document whatever happened to be lying around —
    # `__pycache__` from a test run, or an untracked working directory. Twice.
    # The question the diagram answers is "what ships", and git knows that.
    top = {name.split("/", 1)[0] for name in tracked_files()}
    shipped = sorted(d for d in top if (PLUGIN_ROOT / d).is_dir())
    assert shipped, "git lists no tracked directories"

    # Anchored to the start of a line, because a bare substring search passes on
    # a mention inside another entry's description. `docs/` was satisfied by the
    # words "scaffolds docs/vault/" on the vault-init line, so the block went on
    # claiming to be complete while a whole top-level directory was missing.
    missing = [d for d in shipped
               if not re.search(rf"^{re.escape(d)}/", block, re.MULTILINE)]
    assert not missing, f"README's layout block never lists: {', '.join(missing)}"


ASSETS = PLUGIN_ROOT / "assets"


def rendered_images():
    """Every image the renderer produces. The GIF counts: it is generated from a
    transcript exactly like the stills, and leaving it out of these guards is how
    the one image nobody can regenerate ends up being the one that goes stale."""
    return sorted(list(ASSETS.glob("*.png")) + list(ASSETS.glob("*.gif")))


def test_every_screenshot_the_readme_shows_exists():
    """A README that renders a broken image is worse than one with no images."""
    text = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    referenced = re.findall(r'src="(assets/[^"]+)"', text)
    assert referenced, "the README no longer shows any screenshots"
    for rel in referenced:
        assert (PLUGIN_ROOT / rel).is_file(), f"README shows {rel}, which is not in the repo"


def test_no_screenshot_is_orphaned():
    """The inverse: an image nobody shows is an image nobody notices has gone
    stale."""
    text = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    for image in rendered_images():
        assert f"assets/{image.name}" in text, f"{image.name} is in assets/ but shown nowhere"


def test_every_recording_keeps_the_tape_that_made_it():
    """A recording cannot notice it has gone stale — that is the price of it
    being real rather than drawn. Shipping the tape is what makes re-recording
    a one-line job instead of an archaeology exercise."""
    for image in rendered_images():
        tape = ASSETS / f"{image.stem}.tape"
        assert tape.is_file(), (
            f"{image.name} has no tape; nobody can re-record it when the output "
            f"changes")


@pytest.mark.parametrize(
    "path", sorted((PLUGIN_ROOT / "assets").glob("*.tape")), ids=lambda p: p.name)
def test_a_tape_records_commands_this_plugin_provides(path):
    """A recording is a claim about behaviour, and an invented one is the most
    convincing kind of wrong documentation. Every command a tape types has to be
    something this repo actually ships."""
    text = path.read_text(encoding="utf-8")
    assert re.search(r'^Output "assets/', text, re.MULTILINE), (
        f"{path.name} does not write its output into assets/")

    typed = re.findall(r'^Type "([^"]+)"', text, re.MULTILINE)
    assert typed, f"{path.name} types nothing"
    commands = {line.split()[0] for line in typed
                if not line.startswith("cd ")}
    assert commands, f"{path.name} runs no command"
    assert commands <= {"pingu", "gh-sync", "vault-init", "claude"}, (
        f"{path.name} types {sorted(commands - {'pingu', 'gh-sync', 'vault-init', 'claude'})}, "
        f"which is not this plugin or Claude Code")


def test_this_repos_own_working_notes_stay_out_of_the_repo():
    """README's "Built with itself" section says the vault this repo runs on
    stays local. It was published once by accident, and removing it afterwards
    needed a history rewrite and a repo recreation — a force-push alone left the
    content readable by SHA. Cheaper to make it impossible to add back.

    This does not constrain the vaults the plugin creates in *user* repos, which
    are meant to be committed alongside the code they describe.
    """
    tracked = tracked_files("docs")
    assert not tracked, (
        "this repo's own vault is tracked again: " + ", ".join(tracked[:5]) +
        " — it holds working notes about building the plugin, not part of what "
        "ships. Keep it gitignored.")

    ignore = (PLUGIN_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"^docs/?$", ignore, re.MULTILINE), (
        ".gitignore no longer covers docs/, so the next `git add -A` publishes "
        "this repo's working notes")


def test_the_layout_block_does_not_invent_directories():
    """The inverse: everything the diagram claims must actually be there."""
    claimed = set(re.findall(r"^([a-z._-]+)/", layout_block(), re.MULTILINE))

    for name in claimed:
        assert (PLUGIN_ROOT / name).is_dir(), f"README claims {name}/ which does not exist"


def test_the_layout_block_names_the_real_scripts_and_bin_entries():
    block = layout_block()

    # Only what git tracks. Iterating the directory picked up `__pycache__`,
    # which pytest creates in `scripts/` while importing the modules under test —
    # so the test demanded the README document a build artifact, and passed or
    # failed depending on whether the cache happened to exist yet. It survived
    # every local run and failed on CI's clean checkout, first push.
    tracked = tracked_files("bin", "scripts")
    assert tracked, "git lists nothing under bin/ or scripts/"

    for name in tracked:
        leaf = name.rsplit("/", 1)[-1]
        assert leaf in block, f"{name} is missing from the layout"


def vault_dirs_created():
    """The directories vault_init.sh actually makes, parsed from its mkdir."""
    text = (PLUGIN_ROOT / "scripts" / "vault_init.sh").read_text(encoding="utf-8")
    match = re.search(r'mkdir -p "\$VAULT"/\{([^}]+)\}', text)
    assert match, "vault_init.sh no longer creates the vault with one brace expansion"
    return sorted(d.strip() for d in match.group(1).split(","))


def manual_vault_tree():
    text = (PLUGIN_ROOT / "MANUAL.md").read_text(encoding="utf-8")
    # Two steps, deliberately. One pattern with DOTALL lets `.*[Ll]ayout.*` run
    # from the `# Manual` title down to any stray "layout" later in the file and
    # capture whatever fence follows — which is how this first matched a
    # paragraph about test_command and passed while testing nothing.
    heading = re.search(r"^#+ [^\n]*[Ll]ayout[^\n]*$", text, re.MULTILINE)
    assert heading, "MANUAL has no layout section"
    block = re.search(r"^```\n(.*?)^```", text[heading.end():], re.MULTILINE | re.DOTALL)
    assert block, "MANUAL's layout section has no fenced tree"
    return block.group(1)


def test_the_manual_documents_every_directory_the_vault_gets():
    """MANUAL's tree and vault_init.sh's mkdir are the same list twice. The
    script is the source of truth; the doc is what a human reads."""
    tree = manual_vault_tree()

    missing = [d for d in vault_dirs_created() if f"{d}/" not in tree]
    assert not missing, f"MANUAL's vault tree never mentions: {', '.join(missing)}"


def test_the_manual_vault_tree_invents_nothing():
    tree = manual_vault_tree()
    created = set(vault_dirs_created())

    assert tree.lstrip().startswith("docs/vault/"), "the tree should be rooted at the vault"

    # Indented entries only. The unindented first line is the vault root itself,
    # which is a container rather than something the mkdir creates.
    for name in re.findall(r"^\s+([a-z][a-z._-]*)/", tree, re.MULTILINE):
        assert name in created, f"MANUAL claims {name}/ which vault-init never creates"


@pytest.mark.parametrize("doc", ["README.md", "MANUAL.md"])
def test_the_install_instructions_reference_something_that_exists(doc):
    """Both docs told people to `unzip agent-pingu.zip` for the whole life of
    the project. Nothing ever produced that zip, so the documented install was
    impossible — and the rename guard did not catch it, because the command was
    wrong rather than stale."""
    text = (PLUGIN_ROOT / doc).read_text(encoding="utf-8")

    for artifact in re.findall(r"unzip\s+(\S+)", text):
        assert (PLUGIN_ROOT / artifact).exists(), (
            f"{doc} says to unzip {artifact}, which nothing in this repo builds")


@pytest.mark.parametrize("doc", ["README.md", "MANUAL.md", "WALKTHROUGH.md"])
def test_the_install_instructions_name_a_real_clone_source(doc):
    """`git clone <this repo>` is not a command. The install said that for the
    whole life of the project, in the same way it previously said to unzip a
    file nothing built — plausible-looking, and impossible to run."""
    text = (PLUGIN_ROOT / doc).read_text(encoding="utf-8")
    for source in re.findall(r"git clone (\S+)", text):
        assert not source.startswith("<"), (
            f"{doc} says `git clone {source}` — a placeholder, not something "
            f"anyone can run")
        assert source.startswith("http") or source.startswith("git@"), (
            f"{doc} clones from {source}, which is not a URL")


def test_the_documented_version_matches_the_manifest():
    """The walkthrough quotes `claude plugin list` output, version included, and
    it had gone stale by a release."""
    import json as _json
    version = _json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    text = (PLUGIN_ROOT / "WALKTHROUGH.md").read_text(encoding="utf-8")
    quoted = re.findall(r"^\s*Version:\s*(\S+)\s*$", text, re.MULTILINE)
    assert quoted, "WALKTHROUGH no longer quotes a Version line"
    for shown in quoted:
        assert shown == version, (
            f"WALKTHROUGH shows Version: {shown}, manifest says {version}")


@pytest.mark.parametrize("doc", ["README.md", "MANUAL.md"])
def test_the_install_instructions_name_a_skills_directory(doc):
    """A skills-directory plugin only loads from one. If the install section
    stops saying so, it stops working."""
    text = (PLUGIN_ROOT / doc).read_text(encoding="utf-8")
    install = re.search(r"^#+ .*Install.*$", text, re.MULTILINE)
    assert install, f"{doc} has no install section"

    section = text[install.end():install.end() + 1200]
    assert ".claude/skills/" in section, f"{doc} never names a skills directory"
