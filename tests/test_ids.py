"""ID allocation under concurrency.

`skills/vault/SKILL.md` tells agents to allocate with `pingu next-id` because
"two agents working in parallel will both guess the same one" — and the command
did exactly that itself: it read the highest ID and reported max+1, so two
callers racing got the same answer. Eight concurrent `pingu new task` calls
produced two pairs of duplicate IDs.

The design actively encourages parallel agents ("one task, one file" is a
concurrency decision), so this is the case that matters, not an edge one.
"""

import re
import subprocess
import sys

import pingu
from conftest import PLUGIN_ROOT

# The sqa reviewer reintroduced the original max+1 bug and ran the concurrency
# tests fifteen times: all three passed on 3 of 15 runs. Eight processes on a
# fast local filesystem do not reliably force the interleaving, and CI runs this
# once per push — so a regression had roughly a 1-in-5 chance of going unnoticed.
# The deterministic guard is in test_review_findings.py; this raises the odds
# that the end-to-end version fails too rather than relying on scheduling luck.
CONCURRENCY = 24


def spawn(repo, *argv):
    return subprocess.Popen(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "pingu.py"), *argv],
        cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "CLAUDE_PROJECT_DIR": str(repo)},
    )


def gather(procs):
    out = []
    for p in procs:
        stdout, stderr = p.communicate(timeout=60)
        assert p.returncode == 0, stderr
        out.append(stdout.strip())
    return out


# ---------------------------------------------------------------- reservation

def test_next_id_reserves_rather_than_reporting(vault):
    """Two calls in a row must not hand out the same ID. `next-id` is documented
    as allocating, and an agent that has been given an ID will go and use it."""
    first = pingu.allocate_id(vault, "task")
    second = pingu.allocate_id(vault, "task")
    assert first != second


def test_an_allocated_id_survives_a_note_being_written(vault):
    nid = pingu.allocate_id(vault, "task")
    (vault / "tasks" / f"{nid}-thing.md").write_text(
        f"---\ntype: task\nid: {nid}\n---\n", encoding="utf-8")
    assert pingu.allocate_id(vault, "task") != nid


def test_allocation_counts_existing_notes(vault):
    (vault / "tasks" / "T-0009-existing.md").write_text(
        "---\ntype: task\nid: T-0009\n---\n", encoding="utf-8")
    assert pingu.allocate_id(vault, "task") == "T-0010"


def test_each_type_has_its_own_sequence(vault):
    assert pingu.allocate_id(vault, "task").startswith("T-")
    assert pingu.allocate_id(vault, "adr").startswith("ADR-")
    assert pingu.allocate_id(vault, "adr") == "ADR-0002"


def test_reservations_are_not_committed(vault):
    """They are a local mutex, meaningless in someone else's clone, and would
    conflict on every merge if they were tracked."""
    pingu.allocate_id(vault, "task")
    ignore = vault / ".gitignore"
    assert ignore.is_file(), "the reservation directory is not ignored"
    assert pingu.RESERVED_DIR in ignore.read_text(encoding="utf-8")


def test_reservations_are_not_mistaken_for_notes(vault):
    pingu.allocate_id(vault, "task")
    assert not [n for n in pingu.load_notes(vault) if n.get("id", "").startswith("T-")]


def test_allocation_does_not_degrade_behind_many_outstanding_reservations(vault):
    """An ID handed to an agent that never wrote its note stays reserved. Those
    accumulate, and the O_EXCL walk-forward alone would have to step over every
    one of them — past `attempts`, allocation would start failing outright.
    Counting reservations into the high-water mark is what keeps this O(1)."""
    reserved = vault / pingu.RESERVED_DIR
    reserved.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1201):
        (reserved / f"T-{n:04d}").touch()
    assert pingu.allocate_id(vault, "task") == "T-1201"


# Reservations were pruned once their note existed, to keep the directory
# bounded. That reopened the race — see
# tests/test_review_findings.py::test_a_stale_scan_cannot_reclaim_an_id_a_note_already_holds
# and the replacement, test_a_spent_reservation_is_kept_as_the_high_water_mark.


# --------------------------------------------------------------- concurrency

def test_concurrent_next_id_calls_get_distinct_ids(repo, vault):
    ids = gather([spawn(repo, "next-id", "task") for _ in range(CONCURRENCY)])
    assert len(set(ids)) == CONCURRENCY, f"duplicate IDs handed out: {sorted(ids)}"


def test_concurrent_new_calls_produce_distinct_ids(repo, vault):
    procs = [spawn(repo, "new", "task", f"parallel {i}") for i in range(CONCURRENCY)]
    gather(procs)
    ids = re.findall(r"^id: (\S+)$",
                     "\n".join(p.read_text(encoding="utf-8")
                               for p in (vault / "tasks").glob("*.md")),
                     re.MULTILINE)
    assert len(ids) == CONCURRENCY
    assert len(set(ids)) == CONCURRENCY, f"duplicate IDs on disk: {sorted(ids)}"


def test_concurrent_allocation_leaves_a_clean_vault(repo, vault, run_pingu):
    gather([spawn(repo, "new", "task", f"parallel {i}") for i in range(CONCURRENCY)])
    for path in (vault / "tasks").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("epic: \n", "epic: EPIC-01\n"), encoding="utf-8")
    (vault / "plan" / "EPIC-01-x.md").write_text(
        "---\ntype: epic\nid: EPIC-01\ntitle: x\nstatus: todo\nwork_type: feature\n---\n",
        encoding="utf-8")
    assert run_pingu("doctor") == 0
