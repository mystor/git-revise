"""
This module contains a basic implementation of an efficient, in-memory 3-way
git tree merge. This is used rather than traditional git mechanisms to avoid
needing to use the index file format, which can be slow to initialize for
large repositories.

The INDEX file for my local mozilla-central checkout, for reference, is 35MB.
While this isn't huge, it takes a perceptable amount of time to read the tree
files and generate. This algorithm, on the other hand, avoids looking at
unmodified trees and blobs when possible.
"""

from typing import Optional, Tuple, TypeVar
from pathlib import Path
from subprocess import CalledProcessError

from .odb import Tree, Blob, Commit, Entry, Mode
from .utils import edit_file


T = TypeVar("T")  # pylint: disable=C0103


class MergeConflict(Exception):
    pass


def rebase(commit: Commit, parent: Commit) -> Commit:
    if commit.parent() == parent:
        return commit  # No need to do anything

    tree = merge_trees(
        Path("/"),
        ("new parent", "old parent", "incoming"),
        parent.tree(),
        commit.parent().tree(),
        commit.tree(),
    )
    # NOTE: This omits commit.committer to pull it from the environment. This
    # means that created commits may vary between invocations, but due to
    # caching, should be consistent within a single process.
    return tree.repo.new_commit(tree, [parent], commit.message, commit.author)


def conflict_prompt(
    path: Path,
    descr: str,
    labels: Tuple[str, str, str],
    current: T,
    current_descr: str,
    other: T,
    other_descr: str,
) -> T:
    print(f"{descr} conflict for '{path}'")
    print(f"  (1) {labels[0]}: {current_descr}")
    print(f"  (2) {labels[1]}: {other_descr}")
    char = input("Resolution or (A)bort? ")
    if char == "1":
        return current
    if char == "2":
        return other
    raise MergeConflict("aborted")


def merge_trees(
    path: Path, labels: Tuple[str, str, str], current: Tree, base: Tree, other: Tree
) -> Tree:
    # Merge every named entry which is mentioned in any tree.
    names = set(current.entries.keys()).union(base.entries.keys(), other.entries.keys())
    entries = {}
    for name in names:
        merged = merge_entries(
            path / name.decode(errors="replace"),
            labels,
            current.entries.get(name),
            base.entries.get(name),
            other.entries.get(name),
        )
        if merged is not None:
            entries[name] = merged
    return current.repo.new_tree(entries)


def merge_entries(
    path: Path,
    labels: Tuple[str, str, str],
    current: Optional[Entry],
    base: Optional[Entry],
    other: Optional[Entry],
) -> Optional[Entry]:
    if base == current:
        return other  # no change from base -> current
    if base == other:
        return current  # no change from base -> other
    if current == other:
        return current  # base -> current & base -> other are identical

    # If one of the branches deleted the entry, and the other modified it,
    # report a merge conflict.
    if current is None:
        return conflict_prompt(
            path, "Deletion", labels, current, "deleted", other, "modified"
        )
    if other is None:
        return conflict_prompt(
            path, "Deletion", labels, current, "modified", other, "deleted"
        )

    # Determine which mode we're working with here.
    if current.mode == other.mode:
        mode = current.mode  # current & other agree
    elif current.mode.is_file() and other.mode.is_file():
        # File types support both Mode.EXEC and Mode.REGULAR, try to pick one.
        if base and base.mode == current.mode:
            mode = other.mode
        elif base and base.mode == other.mode:
            mode = current.mode
        else:
            mode = Mode.EXEC  # XXX: gross
    else:
        return conflict_prompt(
            path,
            "Entry type",
            labels,
            current,
            str(current.mode),
            other,
            str(other.mode),
        )

    # Time to merge the actual entries!
    if mode.is_file():
        baseblob = None
        if base and base.mode.is_file():
            baseblob = base.blob()
        return Entry(
            current.repo,
            mode,
            merge_blobs(path, labels, current.blob(), baseblob, other.blob()).oid,
        )
    if mode == Mode.DIR:
        basetree = current.repo.new_tree({})
        if base and base.mode == Mode.DIR:
            basetree = base.tree()
        return Entry(
            current.repo,
            mode,
            merge_trees(path, labels, current.tree(), basetree, other.tree()).oid,
        )
    if mode == Mode.SYMLINK:
        return conflict_prompt(
            path,
            "Symlink",
            labels,
            current,
            current.symlink().decode(),
            other,
            other.symlink().decode(),
        )
    if mode == Mode.GITLINK:
        return conflict_prompt(
            path, "Submodule", labels, current, str(current.oid), other, str(other.oid)
        )

    raise ValueError("unknown mode")


def merge_blobs(
    path: Path,
    labels: Tuple[str, str, str],
    current: Blob,
    base: Optional[Blob],
    other: Blob,
) -> Blob:
    repo = current.repo

    tmpdir = repo.get_tempdir()
    (tmpdir / "current").write_bytes(current.body)
    (tmpdir / "base").write_bytes(base.body if base else b"")
    (tmpdir / "other").write_bytes(other.body)

    # Try running git merge-file to automatically resolve conflicts.
    try:
        merged = repo.git(
            "merge-file",
            "-q",
            "-p",
            f"-L{path} ({labels[0]})",
            f"-L{path} ({labels[1]})",
            f"-L{path} ({labels[2]})",
            str(tmpdir / "current"),
            str(tmpdir / "base"),
            str(tmpdir / "other"),
            newline=False,
        )
    except CalledProcessError as err:
        # The return code is the # of conflicts if there are conflicts, and
        # negative if there is an error.
        if err.returncode < 0:
            raise

        # At this point, we know that there are merge conflicts to resolve.
        # Prompt to try and trigger manual resolution.
        print(f"Merge conflict for '{path}'")
        if input("  Edit conflicted file? (Y/n) ").lower() == "n":
            raise MergeConflict("user aborted")

        # Open the editor on the conflicted file. We ensure the relative path
        # matches the path of the original file for a better editor experience.
        conflicts = tmpdir / "conflict" / path.relative_to("/")
        conflicts.parent.mkdir(parents=True, exist_ok=True)
        conflicts.write_bytes(err.output)
        merged = edit_file(conflicts)

        # Print warnings if the merge looks like it may have failed.
        if merged == err.output:
            print("(note) conflicted file is unchanged")

        if b"<<<<<<<" in merged or b"=======" in merged or b">>>>>>>" in merged:
            print("(note) conflict markers found in the merged file")

        # Was the merge successful?
        if input("  Merge successful? (y/N) ").lower() != "y":
            raise MergeConflict("user aborted")

    return Blob(current.repo, merged)
