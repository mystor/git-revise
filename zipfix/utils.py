from typing import List, Optional

from pathlib import Path
import tempfile

import subprocess
import textwrap
import sys

from .odb import Commit, Tree


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
    filename: str,
    text: bytes,
    comments: Optional[str] = None,
    allow_empty: bool = False,
) -> bytes:
    """Run the editor configured for git to edit the given text"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / filename
        with open(path, "wb") as f:
            for line in text.splitlines():
                f.write(line + b"\n")

            if comments:  # If comments were provided, write them after the text.
                f.write(b"\n")
                for comment in textwrap.dedent(comments).splitlines():
                    f.write(b"# " + comment.encode("utf-8") + b"\n")

        # Invoke the editor
        proc = subprocess.run(["bash", "-c", f"exec $(git var GIT_EDITOR) '{path}'"])
        if proc.returncode != 0:
            print("editor exited with a non-zero exit code", file=sys.stderr)
            sys.exit(1)

        # Read in all lines from the edited file.
        lines = []
        with open(path, "rb") as of:
            for line in of.readlines():
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
    message = run_editor(
        "COMMIT_EDITMSG",
        commit.message,
        comments="""\
        Please enter the commit message for your changes. Lines starting
        with '#' will be ignored, and an empty message aborts the commit.
        """,
    )
    return commit.update(message=message)


def update_head(ref: str, old: Commit, new: Commit, expected: Optional[Tree]):
    # Update the HEAD commit to point to the new value.
    print(f"Updating {ref} ({old.oid} => {new.oid})")
    new.update_ref(ref, "git-zipfix rewrite", old.oid)

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
