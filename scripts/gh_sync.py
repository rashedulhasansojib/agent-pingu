#!/usr/bin/env python3
"""Mirror vault task notes to GitHub Issues.

The vault note is the source of truth for task content. The Issue is the
surface the rest of the team already watches. This script keeps them in step
without making anyone open Obsidian.

Invoked as `gh-sync <command>` — bin/gh-sync puts this on the Bash tool's PATH.

  gh-sync push     create Issues for tasks lacking gh_issue, write number back
  gh-sync status   push status changes (close on done, label otherwise)
  gh-sync pull     append new Issue comments into the note as a thread

`push` refuses on a public repo, because it mirrors note bodies verbatim and the
vault holds internal context. Pass --public-ok when that is what you want.

`pull` and `status` refuse when `gh_repo` names a repository other than this
checkout's own remote. `gh_repo` can come from a committed settings file, and
`pull` writes Issue comment bodies into task notes that the loop then reads as
project state. Pass --allow-foreign when the other repo is intended.

Uses the `gh` CLI, so authentication is whatever the developer already has.
No third-party Python dependencies.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# One definition of where the vault is, shared with pingu.py. Two scripts each
# resolving it their own way is how `vault_dir` ends up half-implemented.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pingu import plugin_option, vault_path, yaml_quoted, yaml_scalar  # noqa: E402

STATUS_LABELS = {
    "todo": "pingu:todo",
    "doing": "pingu:doing",
    "blocked": "pingu:blocked",
    "review": "pingu:review",
    "done": "pingu:done",
}


def gh(*args, check=True):
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def split_note(path):
    """Return (frontmatter_text, body). Empty frontmatter if the note has none."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    return text[3:end].strip(), text[end + 4 :].lstrip("\n")


def read_field(fm, key):
    # `[^\S\n]*` and not `\s*`: \s matches newlines, so an empty value would
    # swallow the line break and capture the *next* field's line. `epic:` with
    # nothing after it then reads as "gh_issue: null", and an empty `gh_issue:`
    # reads as truthy — which makes push skip that task silently forever.
    match = re.search(rf"^{re.escape(key)}:[^\S\n]*(.*)$", fm, re.MULTILINE)
    if not match:
        return None
    return yaml_scalar(match.group(1))


def write_field(path, key, value):
    """Set a frontmatter key in place, adding it if absent."""
    text = path.read_text(encoding="utf-8")
    end = text.find("\n---", 3)
    if not text.startswith("---") or end == -1:
        # Without a closing delimiter the slices below would splice the file
        # back together wrongly. Refuse rather than corrupt someone's note.
        raise ValueError(f"{path}: no frontmatter block to write '{key}' into")
    fm, rest = text[3:end], text[end:]
    # Only ever called with gh_issue today, which is numeric — but nothing stops
    # the next caller passing prose, and an unquoted free-text value is exactly
    # the unparseable-note bug the quoting on the `pingu new` path removed.
    # Numbers, booleans and null stay bare so `gh_issue: 42` is still a number
    # to Dataview rather than a string.
    # Integers stay bare so `gh_issue: 42` is still a number to Dataview.
    # Everything else is quoted, including the strings "null" and "true": no
    # caller needs a literal YAML null, and exempting those words recreates
    # exactly the "is it a value or a keyword" ambiguity the quoting removed.
    rendered = str(value)
    if not re.fullmatch(r"-?\d+", rendered):
        rendered = yaml_quoted(rendered)
    line = f"{key}: {rendered}"
    if re.search(rf"^{re.escape(key)}:", fm, re.MULTILINE):
        fm = re.sub(rf"^{re.escape(key)}:.*$", line, fm, count=1, flags=re.MULTILINE)
    else:
        fm = fm.rstrip("\n") + "\n" + line + "\n"
    path.write_text("---" + fm + rest, encoding="utf-8")


def task_notes(vault):
    for path in sorted((vault / "tasks").glob("*.md")):
        fm, body = split_note(path)
        if read_field(fm, "type") == "task":
            yield path, fm, body


def repo_flag():
    repo = plugin_option("gh_repo")
    return ["--repo", repo] if repo else []


REMOTE_URL = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$")


def git_remote_repo():
    """`owner/name` from this repo's origin, or None if it cannot be read.

    Deliberately git, not `gh repo view` — `gh` would answer for whatever
    `--repo` we pass it, and the question here is what *this* checkout points at.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=vault_path().parent.parent, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = REMOTE_URL.search(result.stdout.strip())
    return f"{match.group('owner')}/{match.group('name')}" if match else None


def foreign_repo_refusal(command, allow_foreign):
    """A message to print and refuse on, or None to proceed.

    `push` sends the vault out and guards on visibility. `pull` and `status` run
    the other way — into the vault, and into the repo's Issues — so they need the
    opposite question answered: is this repository ours at all? `gh_repo` is
    resolved from settings, and `<repo>/.claude/settings.json` is a file a pull
    request can carry, so a contributor's branch can aim these at a repository
    they control. `pull` then writes its comment bodies into task notes, which
    the loop reads as project state.
    """
    declared = plugin_option("gh_repo")
    if not declared or allow_foreign:
        return None
    remote = git_remote_repo()
    if remote is None:
        return (f"refusing to {command}: gh_repo is {declared!r}, and this repo's own "
                f"remote could not be read, so there is nothing to check it against.\n"
                f"Re-run with --allow-foreign if that repo is intended.")
    if declared.lower() != remote.lower():
        return (f"refusing to {command}: gh_repo is {declared!r}, but this repo's remote "
                f"is {remote!r}.\n"
                f"{'Comment bodies from it are written into your notes and read by the loop as project state.' if command == 'pull' else 'This would close Issues and move labels in a repo that is not this one.'}\n"
                f"Re-run with --allow-foreign if that repo is intended.")
    return None


def ensure_label(name):
    # No --force: creating a label that already exists is a no-op we can ignore,
    # but --force would also silently recolour a label the repo already uses for
    # something else. check=False swallows the "already exists" case.
    gh("label", "create", name, "--color", "5319e7", *repo_flag(), check=False)


def repo_visibility():
    """PUBLIC, PRIVATE, INTERNAL — or None when gh cannot tell us."""
    raw = gh("repo", "view", "--json", "visibility", *repo_flag(), check=False)
    if not raw:
        return None
    try:
        return (json.loads(raw).get("visibility") or "").upper() or None
    except (json.JSONDecodeError, AttributeError):
        return None


TITLE_ID = re.compile(r"^([A-Z]+-\d+):")


def issues_by_task():
    """{task id -> issue number} for every Issue this repo already has.

    push writes gh_issue back only after `gh issue create` returns, so a crash
    in that window leaves an Issue no note points at. Looking first means the
    next run adopts it instead of opening a second one.

    Fetched in one call, deliberately. Per-task `--search` would hit GitHub's
    search API, rate-limited to roughly 30/min rather than the core 5000/hr, and
    an epic's worth of tasks would exhaust it mid-push. Worse, the lookup runs
    with check=False, so a throttled call would read as "no existing issue" and
    open a duplicate — the failure would land exactly where duplicates cost most.
    """
    raw = gh(
        "issue", "list", "--state", "all", "--limit", "500",
        "--json", "number,title", *repo_flag(), check=False,
    )
    if not raw:
        return {}
    try:
        issues = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    found = {}
    for issue in issues:
        match = TITLE_ID.match(str(issue.get("title", "")))
        if match:
            found.setdefault(match.group(1), str(issue.get("number")))
    return found


def cmd_push(vault, public_ok=False):
    """Open an Issue per unmirrored task.

    Note bodies are mirrored verbatim, and setup deliberately fills the vault
    with trust boundaries, retention rules, and landmines — so this refuses on a
    public repo unless told otherwise.

    Be precise about what that buys, because the obvious argument is weaker than
    it looks: the vault lives inside the repo it describes, so on a public repo
    those notes are public the moment they are committed, and mirroring them
    exposes nothing new to anyone who can already read the repo. Two cases are
    left, and they are the ones worth a guard:

      - `gh_repo` can point somewhere other than the repo holding the vault, so
        a private project's notes can be mirrored into a public tracker.
      - A note is pushed the moment it is written. Committing it is a separate,
        reviewable step that may never happen — push publishes first.

    INTERNAL is allowed through for the same reason PRIVATE is: everyone it
    exposes the Issue to can already read the repo the vault sits in. Unknown
    visibility is refused, because guessing wrong cannot be undone.
    """
    if not public_ok:
        visibility = repo_visibility()
        if visibility is None:
            print("refusing to push: could not determine this repo's visibility.")
            print("Check `gh auth status`, or pass --public-ok if you know it is fine.")
            return 1
        if visibility == "PUBLIC":
            print(f"refusing to push: this repo is {visibility}, and push mirrors each")
            print("task's whole note body — including notes not yet committed, and")
            print("anything setup wrote about trust boundaries and landmines.")
            print("Re-run with --public-ok if publishing them is intended.")
            return 1

    already = issues_by_task()
    created = 0
    for path, fm, body in task_notes(vault):
        if read_field(fm, "gh_issue"):
            continue
        task_id = read_field(fm, "id") or path.stem

        adopted = already.get(task_id)
        if adopted:
            write_field(path, "gh_issue", adopted)
            print(f"adopted existing #{adopted} for {task_id}")
            continue

        title = read_field(fm, "title") or path.stem
        epic = read_field(fm, "epic")
        status = read_field(fm, "status") or "todo"

        note_body = (
            f"{body.strip()}\n\n---\n"
            f"Mirrored from the project vault: `docs/vault/tasks/{path.name}`\n"
            f"The vault note is the source of truth for this task's content."
        )
        args = ["issue", "create", "--title", f"{task_id}: {title}", "--body", note_body]
        for label in filter(None, [STATUS_LABELS.get(status), f"epic:{epic}" if epic else None]):
            ensure_label(label)
            args += ["--label", label]

        url = gh(*args, *repo_flag())
        number = url.rstrip("/").split("/")[-1]
        write_field(path, "gh_issue", number)
        print(f"created #{number} for {task_id}")
        created += 1
    print(f"push complete: {created} issue(s) created")
    return 0


def cmd_status(vault, allow_foreign=False):
    """Push status changes, and report what actually happened.

    These calls used to run with check=False and print success regardless, so a
    failed sync was indistinguishable from a working one. The verify phase of
    this very loop says to record the actual result; the tooling should too.
    """
    refusal = foreign_repo_refusal("status", allow_foreign)
    if refusal:
        print(refusal)
        return 1
    failed = 0
    for path, fm, _ in task_notes(vault):
        number = read_field(fm, "gh_issue")
        if not number:
            continue
        status = read_field(fm, "status") or "todo"
        problems = []

        label = STATUS_LABELS.get(status)
        if label:
            ensure_label(label)
            others = [v for k, v in STATUS_LABELS.items() if v != label]
            try:
                gh(
                    "issue", "edit", number,
                    "--add-label", label,
                    *sum([["--remove-label", o] for o in others], []),
                    *repo_flag(),
                )
            except RuntimeError as exc:
                problems.append(str(exc))
        if status == "done":
            try:
                gh("issue", "close", number, *repo_flag())
            except RuntimeError as exc:
                problems.append(str(exc))

        if problems:
            failed += 1
            print(f"#{number} FAILED -> {status}: {problems[0]}")
        else:
            print(f"#{number} -> {status}")
    return 1 if failed else 0


def cmd_pull(vault, allow_foreign=False):
    refusal = foreign_repo_refusal("pull", allow_foreign)
    if refusal:
        print(refusal)
        return 1
    for path, fm, _ in task_notes(vault):
        number = read_field(fm, "gh_issue")
        if not number:
            continue
        raw = gh("issue", "view", number, "--json", "comments", *repo_flag(), check=False)
        if not raw:
            continue
        comments = json.loads(raw).get("comments", [])
        if not comments:
            continue
        existing = path.read_text(encoding="utf-8")
        lines = []
        for c in comments:
            marker = f"<!-- gh-comment:{c.get('id')} -->"
            if marker in existing:
                continue
            author = (c.get("author") or {}).get("login", "unknown")
            lines.append(f"\n{marker}\n**@{author}** ({c.get('createdAt', '')[:10]}):\n\n{c.get('body', '').strip()}\n")
        if not lines:
            continue
        if "## Thread" not in existing:
            existing = existing.rstrip("\n") + "\n\n## Thread\n"
        path.write_text(existing.rstrip("\n") + "\n" + "".join(lines), encoding="utf-8")
        print(f"pulled {len(lines)} comment(s) into {path.name}")
    return 0


def main():
    args = sys.argv[1:]
    public_ok = "--public-ok" in args
    allow_foreign = "--allow-foreign" in args
    args = [a for a in args if a not in ("--public-ok", "--allow-foreign")]

    if not args or args[0] not in ("push", "status", "pull"):
        print(__doc__)
        return 1
    vault = vault_path()
    if not (vault / "tasks").is_dir():
        print(f"no tasks directory at {vault / 'tasks'}")
        return 1
    if args[0] == "push":
        return cmd_push(vault, public_ok=public_ok) or 0
    return {"status": cmd_status, "pull": cmd_pull}[args[0]](
        vault, allow_foreign=allow_foreign) or 0


if __name__ == "__main__":
    sys.exit(main())
