"""Tests for scripts/gh_sync.py.

The `gh` CLI is the one boundary stubbed here: it talks to GitHub, and the
behaviour under test is what this script decides to send and how it reports the
result, not what GitHub does with it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

import gh_sync
from conftest import PLUGIN_ROOT, write_note


@pytest.fixture
def fake_gh(monkeypatch):
    """Record every gh invocation; let each test decide what gh returns."""

    class Gh:
        def __init__(self):
            # Per-instance, not class-level: a shared dict would leak a reply
            # set by one test into the next one.
            self.calls = []
            self.replies = {"repo view": '{"visibility":"PRIVATE"}'}
            self.fails = set()

        def __call__(self, *args, check=True):
            self.calls.append(args)
            verb = " ".join(args[:2])
            if verb in self.fails:
                if check:
                    raise RuntimeError(f"gh {verb} failed: boom")
                return ""
            return self.replies.get(verb, "")

        def created(self):
            return [c for c in self.calls if c[:2] == ("issue", "create")]

    gh = Gh()
    monkeypatch.setattr(gh_sync, "gh", gh)
    return gh


# ------------------------------------------------------- frontmatter field reading

def test_read_field_returns_none_for_an_empty_value():
    fm = "type: task\nid: T-0001\nepic: \ngh_issue: null\n"

    assert gh_sync.read_field(fm, "epic") is None


def test_read_field_does_not_bleed_into_the_following_line():
    """An empty value must not swallow the next line, or every downstream
    consumer gets another field's contents."""
    fm = "type: task\ngh_issue: \nstatus: todo\ntitle: real work\n"

    assert gh_sync.read_field(fm, "gh_issue") is None
    assert gh_sync.read_field(fm, "status") == "todo"


def test_read_field_reads_ordinary_values():
    fm = "type: task\nid: T-0042\nepic: EPIC-01\ngh_issue: 142\n"

    assert gh_sync.read_field(fm, "id") == "T-0042"
    assert gh_sync.read_field(fm, "epic") == "EPIC-01"
    assert gh_sync.read_field(fm, "gh_issue") == "142"


def test_read_field_strips_quotes_and_treats_null_as_absent():
    fm = 'owner: "@alice"\nsupersedes: null\ndeciders: ~\n'

    assert gh_sync.read_field(fm, "owner") == "@alice"
    assert gh_sync.read_field(fm, "supersedes") is None
    assert gh_sync.read_field(fm, "deciders") is None


# --------------------------------------------------------- cross-script agreement

def test_a_task_scaffolded_by_loop_py_pushes_without_a_junk_epic_label(repo, vault, fake_gh, monkeypatch):
    """loop.py new task writes an empty `epic:`. gh_sync must not turn that into
    a label named after the next line of frontmatter."""
    subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "loop.py"), "new", "task", "Token bucket"],
        cwd=repo, check=True, capture_output=True,
        env={"CLAUDE_PROJECT_DIR": str(repo), "PATH": "/usr/bin:/bin"},
    )
    fake_gh.replies["issue create"] = "https://github.com/o/r/issues/7"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))

    gh_sync.cmd_push(vault)

    labels = [a[i + 1] for a in fake_gh.calls for i, x in enumerate(a) if x == "--label"]
    assert labels == ["loop:todo"]


def test_push_writes_the_issue_number_back_into_the_note(vault, fake_gh):
    path = write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
                      status="todo", title="middleware", epic="", gh_issue="null")
    fake_gh.replies["issue create"] = "https://github.com/o/r/issues/7"

    gh_sync.cmd_push(vault)

    assert "gh_issue: 7" in path.read_text(encoding="utf-8")


def test_push_skips_a_task_that_is_already_mirrored(vault, fake_gh):
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", title="middleware", gh_issue="142")

    gh_sync.cmd_push(vault)

    assert not [c for c in fake_gh.calls if c[:2] == ("issue", "create")]


# ------------------------------------------------------------------- vault location

def test_gh_sync_and_loop_agree_on_a_configured_vault_dir(repo, monkeypatch):
    """loop.py honours vault_dir; gh_sync.py must read the same vault or it
    pushes tasks from a directory the rest of the loop abandoned."""
    import loop

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_VAULT_DIR", "docs/knowledge")

    assert gh_sync.vault_path() == loop.vault_path()


# --------------------------------------------------------------- honest reporting

def test_status_reports_a_failed_sync_instead_of_claiming_success(vault, fake_gh, capsys):
    """verify/SKILL.md: record the actual result. A swallowed gh failure that
    still prints `-> done` is the exact opposite."""
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="done", title="middleware", gh_issue="142")
    fake_gh.fails = {"issue edit", "issue close"}

    rc = gh_sync.cmd_status(vault)

    out = capsys.readouterr().out
    assert rc == 1
    assert "FAILED" in out
    assert "#142 -> done" not in out


def test_status_reports_success_when_gh_succeeds(vault, fake_gh, capsys):
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="done", title="middleware", gh_issue="142")

    rc = gh_sync.cmd_status(vault)

    assert rc == 0
    assert "#142 -> done" in capsys.readouterr().out
    assert [c for c in fake_gh.calls if c[:2] == ("issue", "close")]


# ------------------------------------------------------------------ note rewriting

def test_write_field_leaves_a_note_without_closing_frontmatter_alone(vault):
    path = vault / "tasks" / "T-0001-broken.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    original = "---\ntype: task\nid: T-0001\n\nno closing delimiter\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError):
        gh_sync.write_field(path, "gh_issue", "7")

    assert path.read_text(encoding="utf-8") == original


# ------------------------------------------------------- public-repo push guard

def test_push_refuses_on_a_public_repo(vault, fake_gh, capsys):
    """Setup deliberately fills the vault with trust boundaries and landmines.
    Mirroring a note body publishes it, and an unattended run gets no second
    chance, so the default has to fail closed."""
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", title="middleware")
    fake_gh.replies["repo view"] = '{"visibility":"PUBLIC"}'

    rc = gh_sync.cmd_push(vault)

    assert rc == 1
    assert not fake_gh.created()
    out = capsys.readouterr().out
    assert "PUBLIC" in out and "--public-ok" in out


def test_push_proceeds_on_a_public_repo_when_explicitly_allowed(vault, fake_gh):
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", title="middleware")
    fake_gh.replies["repo view"] = '{"visibility":"PUBLIC"}'
    fake_gh.replies["issue create"] = "https://github.com/o/r/issues/7"

    assert gh_sync.cmd_push(vault, public_ok=True) == 0
    assert fake_gh.created()


def test_push_proceeds_on_a_private_repo(vault, fake_gh):
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", title="middleware")
    fake_gh.replies["issue create"] = "https://github.com/o/r/issues/7"

    assert gh_sync.cmd_push(vault) == 0
    assert fake_gh.created()


def test_push_refuses_when_visibility_cannot_be_determined(vault, fake_gh, capsys):
    """Unknown is not the same as private. Guessing wrong publishes the vault."""
    write_note(vault, "tasks/T-0001-x.md", type="task", id="T-0001",
               status="todo", title="middleware")
    fake_gh.replies["repo view"] = ""

    assert gh_sync.cmd_push(vault) == 1
    assert not fake_gh.created()
    assert "could not determine" in capsys.readouterr().out.lower()


# ------------------------------------------------------------------ idempotency

def test_push_adopts_an_orphaned_issue_instead_of_creating_a_duplicate(vault, fake_gh, capsys):
    """push writes gh_issue back after creating the Issue. A crash in that
    window leaves an Issue the note does not know about; the next run must
    adopt it rather than open a second one."""
    path = write_note(vault, "tasks/T-0042-x.md", type="task", id="T-0042",
                      status="todo", title="token bucket")
    fake_gh.replies["issue list"] = '[{"number":7,"title":"T-0042: token bucket"}]'

    assert gh_sync.cmd_push(vault) == 0

    assert not fake_gh.created()
    assert "gh_issue: 7" in path.read_text(encoding="utf-8")
    assert "adopted" in capsys.readouterr().out.lower()


def test_push_creates_when_no_issue_matches_the_task_id(vault, fake_gh):
    write_note(vault, "tasks/T-0042-x.md", type="task", id="T-0042",
               status="todo", title="token bucket")
    fake_gh.replies["issue list"] = '[{"number":9,"title":"T-0043: something else"}]'
    fake_gh.replies["issue create"] = "https://github.com/o/r/issues/10"

    gh_sync.cmd_push(vault)

    assert fake_gh.created()


def test_push_looks_up_existing_issues_once_not_once_per_task(vault, fake_gh):
    """`--search` hits GitHub's search API, rate-limited to ~30/min rather than
    the core 5000/hr. A 40-task epic would exhaust it mid-push — and since the
    lookup runs with check=False, a throttled call reads as "no existing issue"
    and pushes a duplicate. Fetch the list once instead."""
    for n in range(1, 41):
        write_note(vault, f"tasks/T-{n:04d}-x.md", type="task", id=f"T-{n:04d}",
                   status="todo", title=f"task {n}")
    fake_gh.replies["issue list"] = "[]"
    fake_gh.replies["issue create"] = "https://github.com/o/r/issues/1"

    gh_sync.cmd_push(vault)

    lookups = [c for c in fake_gh.calls if c[:2] == ("issue", "list")]
    assert len(lookups) == 1, f"{len(lookups)} lookups for 40 tasks"
    assert "--search" not in lookups[0], "still using the rate-limited search API"


def test_push_adopts_from_the_bulk_listing(vault, fake_gh):
    write_note(vault, "tasks/T-0042-x.md", type="task", id="T-0042",
               status="todo", title="token bucket")
    write_note(vault, "tasks/T-0043-y.md", type="task", id="T-0043",
               status="todo", title="limit headers")
    fake_gh.replies["issue list"] = (
        '[{"number":7,"title":"T-0042: token bucket"},'
        ' {"number":8,"title":"T-0043: limit headers"}]')

    gh_sync.cmd_push(vault)

    assert not fake_gh.created()
    assert "gh_issue: 7" in (vault / "tasks" / "T-0042-x.md").read_text(encoding="utf-8")
    assert "gh_issue: 8" in (vault / "tasks" / "T-0043-y.md").read_text(encoding="utf-8")
