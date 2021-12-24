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

from __future__ import annotations

from typing import Iterator, Optional, Tuple, TypeVar
from pathlib import Path
from subprocess import CalledProcessError
import hashlib
import os
import sys

from .odb import Tree, Blob, Commit, Entry, Mode, Repository
from .utils import edit_file


T = TypeVar("T")  # pylint: disable=C0103


class MergeConflict(Exception):
    pass


def rebase(commit: Commit, new_parent: Optional[Commit]) -> Commit:
    repo = commit.repo

    orig_parent = commit.parent() if not commit.is_root else None

    if orig_parent == new_parent:
        return commit  # No need to do anything

    def get_summary(cmt: Optional[Commit]) -> str:
        return cmt.summary() if cmt is not None else "<root>"

    def get_tree(cmt: Optional[Commit]) -> Tree:
        return cmt.tree() if cmt is not None else Tree(repo, b"")

    tree = merge_trees(
        Path("/"),
        (get_summary(new_parent), get_summary(orig_parent), get_summary(commit)),
        get_tree(new_parent),
        get_tree(orig_parent),
        get_tree(commit),
    )

    new_parents = [new_parent] if new_parent is not None else []

    # NOTE: This omits commit.committer to pull it from the environment. This
    # means that created commits may vary between invocations, but due to
    # caching, should be consistent within a single process.
    return commit.update(tree=tree, parents=new_parents)


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
    print(f"  (2) {labels[2]}: {other_descr}")
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
            mode = conflict_prompt(
                path,
                "File mode",
                labels,
                current.mode,
                str(current.mode),
                other.mode,
                str(other.mode),
            )
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

    annotated_labels = (
        f"{path} (new parent): {labels[0]}",
        f"{path} (old parent): {labels[1]}",
        f"{path} (current): {labels[2]}",
    )
    (is_clean_merge, merged) = merge_files(
        repo,
        annotated_labels,
        current.body,
        base.body if base else b"",
        other.body,
        tmpdir,
    )

    if is_clean_merge:
        # No conflicts.
        return Blob(repo, merged)

    # At this point, we know that there are merge conflicts to resolve.
    # Prompt to try and trigger manual resolution.
    print(f"Conflict applying '{labels[2]}'")
    print(f"  Path: '{path}'")

    preimage = merged
    (normalized_preimage, conflict_id, merged_blob) = replay_recorded_resolution(
        repo, tmpdir, preimage
    )
    if merged_blob is not None:
        return merged_blob

    if input("  Edit conflicted file? (Y/n) ").lower() == "n":
        raise MergeConflict("user aborted")

    # Open the editor on the conflicted file. We ensure the relative path
    # matches the path of the original file for a better editor experience.
    conflicts = tmpdir / "conflict" / path.relative_to("/")
    conflicts.parent.mkdir(parents=True, exist_ok=True)
    conflicts.write_bytes(preimage)
    merged = edit_file(repo, conflicts)

    # Print warnings if the merge looks like it may have failed.
    if merged == preimage:
        print("(note) conflicted file is unchanged")

    if b"<<<<<<<" in merged or b"=======" in merged or b">>>>>>>" in merged:
        print("(note) conflict markers found in the merged file")

    # Was the merge successful?
    if input("  Merge successful? (y/N) ").lower() != "y":
        raise MergeConflict("user aborted")

    record_resolution(repo, conflict_id, normalized_preimage, merged)

    return Blob(current.repo, merged)


def merge_files(
    repo: Repository,
    labels: Tuple[str, str, str],
    current: bytes,
    base: bytes,
    other: bytes,
    tmpdir: Path,
) -> Tuple[bool, bytes]:
    (tmpdir / "current").write_bytes(current)
    (tmpdir / "base").write_bytes(base)
    (tmpdir / "other").write_bytes(other)

    # Try running git merge-file to automatically resolve conflicts.
    try:
        merged = repo.git(
            "merge-file",
            "-q",
            "-p",
            f"-L{labels[0]}",
            f"-L{labels[1]}",
            f"-L{labels[2]}",
            str(tmpdir / "current"),
            str(tmpdir / "base"),
            str(tmpdir / "other"),
            trim_newline=False,
        )

        return (True, merged)  # Successful merge
    except CalledProcessError as err:
        # The return code is the # of conflicts if there are conflicts, and
        # negative if there is an error.
        if err.returncode < 0:
            raise

        return (False, err.output)  # Conflicted merge


def replay_recorded_resolution(
    repo: Repository, tmpdir: Path, preimage: bytes
) -> Tuple[bytes, Optional[str], Optional[Blob]]:
    rr_cache = repo.git_path("rr-cache")
    if not repo.bool_config(
        "revise.rerere",
        default=repo.bool_config("rerere.enabled", default=rr_cache.is_dir()),
    ):
        return (b"", None, None)

    (normalized_preimage, conflict_id) = normalize_conflicted_file(preimage)
    conflict_dir = rr_cache / conflict_id
    if not conflict_dir.is_dir():
        return (normalized_preimage, conflict_id, None)
    if not repo.bool_config("rerere.autoUpdate", default=False):
        if input("  Apply recorded resolution? (y/N) ").lower() != "y":
            return (b"", None, None)

    postimage_path = conflict_dir / "postimage"
    preimage_path = conflict_dir / "preimage"
    try:
        recorded_postimage = postimage_path.read_bytes()
        recorded_preimage = preimage_path.read_bytes()
    except IOError as err:
        print(f"(warning) failed to read git-rerere cache: {err}", file=sys.stderr)
        return (normalized_preimage, conflict_id, None)

    (is_clean_merge, merged) = merge_files(
        repo,
        labels=("recorded postimage", "recorded preimage", "new preimage"),
        current=recorded_postimage,
        base=recorded_preimage,
        other=normalized_preimage,
        tmpdir=tmpdir,
    )
    if not is_clean_merge:
        # We could ask the user to merge this. However, that could be confusing.
        # Just fall back to letting them resolve the entire conflict.
        return (normalized_preimage, conflict_id, None)

    print("Successfully replayed recorded resolution")
    # Mark that "postimage" was used to help git gc. See merge() in Git's rerere.c.
    os.utime(postimage_path)
    return (normalized_preimage, conflict_id, Blob(repo, merged))


def record_resolution(
    repo: Repository,
    conflict_id: Optional[str],
    normalized_preimage: bytes,
    postimage: bytes,
) -> None:
    if conflict_id is None:
        return

    # TODO Lock {repo.gitdir}/MERGE_RR until everything is written.
    print("Recording conflict resolution")
    conflict_dir = repo.git_path("rr-cache") / conflict_id
    try:
        conflict_dir.mkdir(exist_ok=True, parents=True)
        (conflict_dir / "preimage").write_bytes(normalized_preimage)
        (conflict_dir / "postimage").write_bytes(postimage)
    except IOError as err:
        print(f"(warning) failed to write git-rerere cache: {err}", file=sys.stderr)


class ConflictParseFailed(Exception):
    pass


def normalize_conflict(
    lines: Iterator[bytes],
    hasher: Optional[hashlib._Hash],
) -> bytes:
    cur_hunk: Optional[bytes] = b""
    other_hunk: Optional[bytes] = None
    while True:
        line = next(lines, None)
        if line is None:
            raise ConflictParseFailed("unexpected eof")
        if line.startswith(b"<<<<<<<"):
            # parse recursive conflicts, including their processed output in the current hunk
            conflict = normalize_conflict(lines, None)
            if cur_hunk is not None:
                cur_hunk += conflict
        elif line.startswith(b"|||||||"):
            # ignore the diff3 original section. Must be still parsing the first hunk.
            if other_hunk is not None:
                raise ConflictParseFailed("unexpected ||||||| conflict marker")
            (other_hunk, cur_hunk) = (cur_hunk, None)
        elif line.startswith(b"======="):
            # switch into the second hunk
            # could be in either the diff3 original section or the first hunk
            if cur_hunk is not None:
                if other_hunk is not None:
                    raise ConflictParseFailed("unexpected ======= conflict marker")
                other_hunk = cur_hunk
            cur_hunk = b""
        elif line.startswith(b">>>>>>>"):
            # end of conflict. update hasher, and return a normalized conflict
            if cur_hunk is None or other_hunk is None:
                raise ConflictParseFailed("unexpected >>>>>>> conflict marker")

            (hunk1, hunk2) = sorted((cur_hunk, other_hunk))
            if hasher:
                hasher.update(hunk1 + b"\0")
                hasher.update(hunk2 + b"\0")
            return b"".join(
                (
                    b"<<<<<<<\n",
                    hunk1,
                    b"=======\n",
                    hunk2,
                    b">>>>>>>\n",
                )
            )
        elif cur_hunk is not None:
            # add non-marker lines to the current hunk (or discard if in
            # the diff3 original section)
            cur_hunk += line


def normalize_conflicted_file(body: bytes) -> Tuple[bytes, str]:
    hasher = hashlib.sha1()
    normalized = b""

    lines = iter(body.splitlines(keepends=True))
    while True:
        line = next(lines, None)
        if line is None:
            return (normalized, hasher.hexdigest())
        if line.startswith(b"<<<<<<<"):
            normalized += normalize_conflict(lines, hasher)
        else:
            normalized += line
