from typing import List, Optional
from subprocess import run, PIPE
import textwrap
import sys
import os

from .odb import Repository, Commit, Tree, Oid


def commit_range(base: Commit, tip: Commit) -> List[Commit]:
    """Oldest-first iterator over the given commit range,
    not including the commit |base|"""
    commits = []
    while tip != base:
        commits.append(tip)
        tip = tip.parent()
    commits.reverse()
    return commits


def run_editor(
    repo: Repository,
    filename: str,
    text: bytes,
    comments: Optional[str] = None,
    allow_empty: bool = False,
) -> bytes:
    """Run the editor configured for git to edit the given text"""
    path = repo.get_tempdir() / filename
    with open(path, "wb") as handle:
        for line in text.splitlines():
            handle.write(line + b"\n")

        if comments:  # If comments were provided, write them after the text.
            handle.write(b"\n")
            for comment in textwrap.dedent(comments).splitlines():
                handle.write(b"# " + comment.encode("utf-8") + b"\n")

    # Invoke the editor
    proc = run(["bash", "-c", f"exec $(git var GIT_EDITOR) '{path}'"])
    if proc.returncode != 0:
        print("editor exited with a non-zero exit code", file=sys.stderr)
        sys.exit(1)

    # Read in all lines from the edited file.
    lines = []
    with open(path, "rb") as handle:
        for line in handle.readlines():
            if comments and line.startswith(b"#"):
                continue
            lines.append(line)

    # Concatenate parsed lines, stripping trailing newlines.
    data = b"".join(lines).rstrip() + b"\n"
    if data == b"\n" and not allow_empty:
        print("empty file - aborting", file=sys.stderr)
        sys.exit(1)
    return data


def edit_commit_message(commit: Commit) -> Commit:
    # If the target commit is not the initial commit, produce a diff --stat to
    # include in the commit message comments.
    if len(commit.parents()) == 1:
        base_tree = commit.parent().tree().persist().hex()
        commit_tree = commit.tree().persist().hex()

        diff_stat = run(
            ["git", "diff-tree", "--stat", base_tree, commit_tree],
            check=True,
            stdout=PIPE,
        ).stdout.decode(errors="replace")
    else:
        diff_stat = "<initial commit>"

    message = run_editor(
        commit.repo,
        "COMMIT_EDITMSG",
        commit.message,
        comments=textwrap.dedent(
            """\
            Please enter the commit message for your changes. Lines starting
            with '#' will be ignored, and an empty message aborts the commit.

            """
        )
        + diff_stat,
    )
    return commit.update(message=message)


def update_head(ref: str, old: Commit, new: Commit, expected: Optional[Tree]):
    # Update the HEAD commit to point to the new value.
    print(f"Updating {ref} ({old.oid} => {new.oid})")
    new.update_ref(ref, "git-revise rewrite", old.oid)

    # We expect our tree to match the tree we started with (including index
    # changes). If it does not, print out a warning.
    if expected and new.tree() != expected:
        print(
            "(warning) unexpected final tree\n"
            f"(note) expected: {expected.oid}\n"
            f"(note) actual: {new.tree().oid}\n"
            "(note) working directory & index have not been updated.\n"
            "(note) use `git status` to see what has changed.",
            file=sys.stderr,
        )


def cut_commit(commit: Commit) -> Commit:
    repo = commit.repo

    # Create an environment with an explicit index file.
    temp_index = repo.get_tempdir() / "TEMP_INDEX"
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(temp_index)

    # Read the target tree into a temporary index.
    run(
        ["git", "read-tree", commit.tree().persist().hex()],
        check=True,
        env=env,
        cwd=repo.workdir,
    )

    # Run an interactive git-reset to allow picking which pieces of the
    # patch should go into which part.
    run(
        ["git", "reset", "--patch", commit.parent().persist().hex()],
        check=True,
        env=env,
        cwd=repo.workdir,
    )

    # Use write-tree to get the new intermediate tree state.
    written = run(
        ["git", "write-tree"], check=True, stdout=PIPE, env=env, cwd=repo.workdir
    )
    mid_tree = repo.get_tree(Oid.fromhex(written.stdout.rstrip().decode()))

    # Check if one or the other of the commits will be empty
    if mid_tree == commit.parent().tree() or mid_tree == commit.tree():
        raise ValueError("intermediate state not distinct from end states")

    # Build the first commit
    part1 = commit.update(tree=mid_tree, message=b"[1] " + commit.message)
    part1 = edit_commit_message(part1)

    # Build the second commit
    part2 = commit.update(parents=[part1], message=b"[2] " + commit.message)
    part2 = edit_commit_message(part2)

    return part2
