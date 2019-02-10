from typing import List, Optional
from subprocess import run, CalledProcessError
from pathlib import Path
import textwrap
import sys
import os
import shlex

from .odb import Repository, Commit, Tree, Oid, Reference


class EditorError(Exception):
    pass


def commit_range(base: Commit, tip: Commit) -> List[Commit]:
    """Oldest-first iterator over the given commit range,
    not including the commit ``base``"""
    commits = []
    while tip != base:
        commits.append(tip)
        tip = tip.parent()
    commits.reverse()
    return commits


def edit_file(path: Path) -> bytes:
    try:
        run(
            ["bash", "-c", f"exec $(git var GIT_EDITOR) {shlex.quote(path.name)}"],
            check=True,
            cwd=path.parent,
        )
    except CalledProcessError as err:
        raise EditorError(f"Editor exited with status {err}")
    return path.read_bytes()


def strip_comments(data: bytes) -> bytes:
    lines = b""
    for line in data.splitlines(keepends=True):
        if not line.startswith(b"#"):
            lines += line

    lines = lines.rstrip()
    if lines != b"":
        lines += b"\n"
    return lines


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
    data = edit_file(path)
    if comments:
        data = strip_comments(data)

    # Produce an error if the file was empty
    if not (allow_empty or data):
        raise EditorError("empty file - aborting")
    return data


def edit_commit_message(commit: Commit) -> Commit:
    """Launch an editor to edit the commit message of ``commit``, returning
    a modified commit"""
    repo = commit.repo
    comments = (
        "Please enter the commit message for your changes. Lines starting\n"
        "with '#' will be ignored, and an empty message aborts the commit.\n"
    )

    # If the target commit is not the initial commit, produce a diff --stat to
    # include in the commit message comments.
    if len(commit.parents()) == 1:
        tree_a = commit.parent().tree().persist().hex()
        tree_b = commit.tree().persist().hex()
        comments += "\n" + repo.git("diff-tree", "--stat", tree_a, tree_b).decode()

    message = run_editor(repo, "COMMIT_EDITMSG", commit.message, comments=comments)
    return commit.update(message=message)


def update_head(ref: Reference[Commit], new: Commit, expected: Optional[Tree]):
    # Update the HEAD commit to point to the new value.
    target_oid = ref.target.oid if ref.target else Oid.null()
    print(f"Updating {ref.name} ({target_oid} => {new.oid})")
    ref.update(new, "git-revise rewrite")

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
    """Perform a ``cut`` operation on the given commit, and return the
    modified commit."""

    repo = commit.repo

    # Create an environment with an explicit index file.
    temp_index = repo.get_tempdir() / "TEMP_INDEX"
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(temp_index)

    # Read the target tree into a temporary index.
    repo.git("read-tree", commit.tree().persist().hex())

    # Run an interactive git-reset to allow picking which pieces of the
    # patch should go into which part.
    repo.git("reset", "--patch", commit.parent().persist().hex())

    # Use write-tree to get the new intermediate tree state.
    written = repo.git("write-tree", env=env).decode()
    mid_tree = repo.get_tree(Oid.fromhex(written))

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
