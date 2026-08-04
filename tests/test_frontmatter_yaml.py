"""Every note this plugin writes must parse as real YAML.

pingu's own frontmatter reader is deliberately lenient — it partitions on the
first colon and never raises — which is exactly why this went unnoticed: the
tooling read back notes that no real YAML parser accepts. Obsidian and Dataview
do use a real parser, and the board is the artifact that silently loses the note.

Two failure modes, both found by pointing PyYAML at what `pingu new` produced:

    title: Rate limiting: the search endpoint   -> ScannerError, note unparseable
    title: Use "Redis" for #caching             -> silently truncates to 'Use "Redis" for'

The second is worse than the first. An error gets noticed.
"""

import subprocess
import sys

import pytest
import yaml

import gh_sync
import pingu
from conftest import PLUGIN_ROOT

# Titles that a person would plausibly type, each of which is a YAML indicator
# somewhere. "Fix: login bug" is not an edge case; it is how people name tasks.
HOSTILE_TITLES = [
    "Rate limiting: the search endpoint",
    'Use "Redis" for #caching',
    "  leading and trailing space  ",
    "null",
    "- starts with a dash",
    "123",
    "{braces} [brackets] & anchor *alias |block >fold %directive @at `tick",
    "single 'quotes' and \\backslashes\\",
    "trailing colon:",
    "yes",
]


# board.md is a Dataview dashboard, not a note — it is queried, never queried
# *for*, so it carries no frontmatter. Named explicitly rather than skipping
# anything without a block, so a note that loses its frontmatter still fails.
NO_FRONTMATTER = {"board.md"}

# Obsidian's template syntax, substituted when a note is created from the
# template. The raw file is not meant to parse; what it becomes is.
PLACEHOLDERS = {"{{date:YYYY-MM-DD}}": "2026-08-05", "{{title}}": "A title"}


def frontmatter_of(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path} has no frontmatter"
    end = text.find("\n---", 3)
    assert end != -1, f"{path} has no closing frontmatter delimiter"
    return text[3:end]


def parsed(path):
    """The frontmatter as a real YAML parser sees it."""
    try:
        return yaml.safe_load(frontmatter_of(path))
    except yaml.YAMLError as exc:
        pytest.fail(f"{path.name} is not valid YAML: {str(exc).splitlines()[0]}")


# ------------------------------------------------------------ what `new` writes

@pytest.mark.parametrize("title", HOSTILE_TITLES)
@pytest.mark.parametrize("kind", sorted(pingu.TYPES))
def test_a_new_note_is_valid_yaml(vault, kind, title, capsys):
    pingu.cmd_new(vault, kind, title)
    path = __import__("pathlib").Path(capsys.readouterr().out.strip())
    assert parsed(path) is not None


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_a_title_survives_the_round_trip(vault, title, capsys):
    """Valid YAML is not enough — `#caching` was dropped from a note that parsed
    perfectly well. The value has to come back the same."""
    pingu.cmd_new(vault, "task", title)
    path = __import__("pathlib").Path(capsys.readouterr().out.strip())
    assert parsed(path)["title"] == title.strip()


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_pingus_own_reader_agrees_with_a_real_parser(vault, title, capsys):
    """The lenient reader and PyYAML disagreeing is how this stayed hidden."""
    pingu.cmd_new(vault, "task", title)
    path = __import__("pathlib").Path(capsys.readouterr().out.strip())
    assert pingu.parse_frontmatter(path)["title"] == parsed(path)["title"]


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_gh_sync_reads_the_same_title(vault, title, capsys):
    """It becomes the GitHub Issue title, so a mangled read ships to the team."""
    pingu.cmd_new(vault, "task", title)
    path = __import__("pathlib").Path(capsys.readouterr().out.strip())
    fm, _ = gh_sync.split_note(path)
    assert gh_sync.read_field(fm, "title") == title.strip()


def test_a_newline_in_a_title_cannot_break_the_block(vault, capsys):
    """`pingu new task` joins its arguments, and a shell heredoc or a copied
    string can carry a newline into one of them."""
    pingu.cmd_new(vault, "task", "first line\nsecond: line\n---\nnot a delimiter")
    path = __import__("pathlib").Path(capsys.readouterr().out.strip())
    assert parsed(path)["type"] == "task"


# ------------------------------------------------- what ships and what is seeded

def test_every_seeded_note_is_valid_yaml(vault):
    seeded = sorted(vault.rglob("*.md"))
    assert seeded, "vault_init.sh seeded nothing"
    for path in seeded:
        if path.name in NO_FRONTMATTER:
            assert not path.read_text(encoding="utf-8").startswith("---"), (
                f"{path.name} now has frontmatter; take it out of NO_FRONTMATTER")
            continue
        assert parsed(path) is not None


@pytest.mark.parametrize(
    "path", sorted((PLUGIN_ROOT / "templates").glob("*.md")),
    ids=lambda p: p.name,
)
def test_every_shipped_template_is_valid_yaml_once_obsidian_fills_it_in(path, tmp_path):
    """These are for writing a note by hand, so a broken one teaches the mistake.

    Substitute the Obsidian placeholders first: the raw template is not supposed
    to parse, the note it becomes is.
    """
    text = path.read_text(encoding="utf-8")
    for placeholder, value in PLACEHOLDERS.items():
        text = text.replace(placeholder, value)
    filled = tmp_path / path.name
    filled.write_text(text, encoding="utf-8")
    assert "{{" not in frontmatter_of(filled), (
        f"{path.name} uses a placeholder this test does not know how to fill in")
    assert parsed(filled) is not None


def test_a_note_written_through_the_cli_is_valid_yaml(repo, vault):
    """The in-process tests above share an interpreter with the code under test.
    Run it the way a skill does, once, to prove nothing depends on that."""
    result = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "pingu.py"),
         "new", "task", "Fix: the #1 thing"],
        cwd=repo, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "CLAUDE_PROJECT_DIR": str(repo)},
    )
    assert result.returncode == 0, result.stderr
    path = __import__("pathlib").Path(result.stdout.strip())
    assert parsed(path)["title"] == "Fix: the #1 thing"
