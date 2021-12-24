from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple
from subprocess import CompletedProcess, run, CalledProcessError
from pathlib import Path
import textwrap
import sys
import os
import re

from .odb import Repository, Commit, Tree, Oid, Reference


class EditorError(Exception):
    pass


def commit_range(base: Optional[Commit], tip: Commit) -> List[Commit]:
    """Oldest-first iterator over the given commit range,
    not including the commit ``base``"""
    commits = []
    while tip != base:
        commits.append(tip)
        if tip.is_root and base is None:
            break
        tip = tip.parent()
    commits.reverse()
    return commits


def local_commits(repo: Repository, tip: Commit) -> Tuple[Commit, List[Commit]]:
    """Returns an oldest-first iterator over the local commits which are
    parents of the specified commit. May return an empty list. A commit is
    considered local if it is not present on any remote."""

    # Keep track of the current base commit we're expecting. This serves two
    # purposes. Firstly, it lets us return a base commit to our caller, and
    # secondly it allows us to ensure the commits ``git log`` is producing form
    # a single-parent chain from our initial commit.
    base = tip

    # Call `git log` to log out the OIDs of the commits in our specified range.
    log = repo.git("log", base.oid.hex(), "--not", "--remotes", "--pretty=%H")

    # Build a list of commits, validating each commit is part of a single-parent chain.
    commits = []
    for line in log.splitlines():
        commit = repo.get_commit(Oid.fromhex(line.decode()))

        # Ensure the commit we got is the parent of the previous logged commit.
        if len(commit.parents()) != 1 or commit != base:
            break
        base = commit.parent()

        # Add the commit to our list.
        commits.append(commit)

    # Reverse our list into oldest-first order.
    commits.reverse()
    return base, commits


def edit_file_with_editor(editor: str, path: Path) -> bytes:
    try:
        cmd = [sh_path(), "-ec", f'{editor} "$@"', editor, path.name]
        run(cmd, check=True, cwd=path.parent)
    except CalledProcessError as err:
        raise EditorError(f"Editor exited with status {err}") from err
    return path.read_bytes()


def get_commentchar(repo: Repository, text: bytes) -> bytes:
    commentchar = repo.config("core.commentChar", default=b"#")
    if commentchar == b"auto":
        chars = bytearray(b"#;@!$%^&|:")
        for line in text.splitlines():
            try:
                chars.remove(line[0])
            except (ValueError, IndexError):
                pass
        try:
            return chars[:1]
        except IndexError as err:
            raise EditorError(
                "Unable to automatically select a comment character"
            ) from err
    if commentchar == b"":
        raise EditorError("core.commentChar must not be empty")
    return commentchar


def strip_comments(
    data: bytes, commentchar: bytes, allow_preceding_whitespace: bool
) -> bytes:
    if allow_preceding_whitespace:
        pat_is_comment_line = re.compile(br"^\s*" + re.escape(commentchar))

        def is_comment_line(line: bytes) -> bool:
            return bool(re.match(pat_is_comment_line, line))

    else:

        def is_comment_line(line: bytes) -> bool:
            return line.startswith(commentchar)

    lines = b""
    for line in data.splitlines(keepends=True):
        if not is_comment_line(line):
            lines += line

    lines = lines.rstrip()
    if lines != b"":
        lines += b"\n"
    return lines


def run_specific_editor(
    editor: str,
    repo: Repository,
    filename: str,
    text: bytes,
    comments: Optional[str] = None,
    allow_empty: bool = False,
    allow_whitespace_before_comments: bool = False,
) -> bytes:
    """Run the editor configured for git to edit the given text"""
    path = repo.get_tempdir() / filename
    commentchar = get_commentchar(repo, text)
    with open(path, "wb") as handle:
        for line in text.splitlines():
            handle.write(line + b"\n")

        if comments:  # If comments were provided, write them after the text.
            handle.write(b"\n")
            for comment in textwrap.dedent(comments).splitlines():
                handle.write(commentchar)
                if comment:
                    handle.write(b" " + comment.encode("utf-8"))
                handle.write(b"\n")

    # Invoke the editor
    data = edit_file_with_editor(editor, path)
    if comments:
        data = strip_comments(
            data,
            commentchar,
            allow_preceding_whitespace=allow_whitespace_before_comments,
        )

    # Produce an error if the file was empty
    if not (allow_empty or data):
        raise EditorError("empty file - aborting")
    return data


def git_editor(repo: Repository) -> str:
    return repo.git("var", "GIT_EDITOR").decode()


def edit_file(repo: Repository, path: Path) -> bytes:
    return edit_file_with_editor(git_editor(repo), path)


def run_editor(
    repo: Repository,
    filename: str,
    text: bytes,
    comments: Optional[str] = None,
    allow_empty: bool = False,
) -> bytes:
    """Run the editor configured for git to edit the given text"""
    return run_specific_editor(
        editor=git_editor(repo),
        repo=repo,
        filename=filename,
        text=text,
        comments=comments,
        allow_empty=allow_empty,
    )


def git_sequence_editor(repo: Repository) -> str:
    # This lookup order replicates the one used by git itself.
    # See editor.c:sequence_editor.
    editor = os.getenv("GIT_SEQUENCE_EDITOR")
    if editor is None:
        editor_bytes = repo.config("sequence.editor", default=None)
        editor = editor_bytes.decode() if editor_bytes is not None else None
    if editor is None:
        editor = git_editor(repo)
    return editor


def run_sequence_editor(
    repo: Repository,
    filename: str,
    text: bytes,
    comments: Optional[str] = None,
    allow_empty: bool = False,
) -> bytes:
    """Run the editor configured for git to edit the given rebase/revise sequence"""
    return run_specific_editor(
        editor=git_sequence_editor(repo),
        repo=repo,
        filename=filename,
        text=text,
        comments=comments,
        allow_empty=allow_empty,
        allow_whitespace_before_comments=True,
    )


def edit_commit_message(commit: Commit) -> Commit:
    """Launch an editor to edit the commit message of ``commit``, returning
    a modified commit"""
    repo = commit.repo
    comments = (
        "Please enter the commit message for your changes. Lines starting\n"
        "with '#' will be ignored, and an empty message aborts the commit.\n"
    )

    # If the target commit is not a merge commit, produce a diff --stat to
    # include in the commit message comments.
    if len(commit.parents()) < 2:
        tree_a = commit.parent_tree().persist().hex()
        tree_b = commit.tree().persist().hex()
        comments += "\n" + repo.git("diff-tree", "--stat", tree_a, tree_b).decode()

    message = run_editor(repo, "COMMIT_EDITMSG", commit.message, comments=comments)
    return commit.update(message=message)


def update_head(ref: Reference[Commit], new: Commit, expected: Optional[Tree]) -> None:
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

    print(f"Cutting commit {commit.oid.short()}")
    print("Select changes to be included in part [1]:")

    base_tree = commit.parent_tree()
    final_tree = commit.tree()

    # Create an environment with an explicit index file and the base tree.
    #
    # NOTE: The use of `skip_worktree` is only necessary due to `git reset
    # --patch` unnecessarily invoking `git update-cache --refresh`. Doing the
    # extra work to set the bit greatly improves the speed of the unnecessary
    # refresh operation.
    index = base_tree.to_index(
        commit.repo.get_tempdir() / "TEMP_INDEX", skip_worktree=True
    )

    # Run an interactive git-reset to allow picking which pieces of the
    # patch should go into the first part.
    index.git("reset", "--patch", final_tree.persist().hex(), "--", ".", nocapture=True)

    # Write out the newly created tree.
    mid_tree = index.tree()

    # Check if one or the other of the commits will be empty
    if mid_tree == base_tree:
        raise ValueError("cut part [1] is empty - aborting")

    if mid_tree == final_tree:
        raise ValueError("cut part [2] is empty - aborting")

    # Build the first commit
    part1 = commit.update(tree=mid_tree, message=b"[1] " + commit.message)
    part1 = edit_commit_message(part1)

    # Build the second commit
    part2 = commit.update(parents=[part1], message=b"[2] " + commit.message)
    part2 = edit_commit_message(part2)

    return part2


def sh_path() -> str:
    if os.name == "nt":
        # On Windows, git is installed using Git for Windows, which installs
        # into the "Git" directory in "%ProgramFiles%". Use the `sh.exe` file
        # from that directory to perform shell operations, so they're executed
        # in the expected environment.
        return os.path.join(os.environ["PROGRAMFILES"], "Git", "bin", "sh.exe")
    return "/bin/sh"


def sh_run(
    cmd: Sequence[Any],
    *args: Any,
    **kwargs: Any,
) -> CompletedProcess[Any]:
    """Run a command within git's shell environment. This is the same as
    subprocess.run on most platforms, but will enter the git-bash mingw
    environment on Windows."""
    if os.name == "nt":
        cmd = (sh_path(), "-ec", 'exec "$0" "$@"', *cmd)
    return run(cmd, *args, **kwargs)  # pylint: disable=subprocess-run-check
