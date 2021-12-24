from __future__ import annotations

from typing import Optional, List
from argparse import ArgumentParser, Namespace
from subprocess import CalledProcessError
import sys

from .odb import Repository, Commit, Reference
from .utils import (
    EditorError,
    commit_range,
    edit_commit_message,
    update_head,
    cut_commit,
    local_commits,
)
from .todo import apply_todos, build_todos, edit_todos, autosquash_todos
from .merge import MergeConflict
from . import __version__


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="""\
        Rebase staged changes onto the given commit, and rewrite history to
        incorporate these changes."""
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--root",
        action="store_true",
        help="revise starting at the root commit",
    )
    target_group.add_argument(
        "target",
        nargs="?",
        help="target commit to apply fixups to",
    )
    parser.add_argument("--ref", default="HEAD", help="reference to update")
    parser.add_argument(
        "--reauthor",
        action="store_true",
        help="reset the author of the targeted commit",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--edit",
        "-e",
        action="store_true",
        help="edit commit message of targeted commit(s)",
    )

    autosquash_group = parser.add_mutually_exclusive_group()
    autosquash_group.add_argument(
        "--autosquash",
        action="store_true",
        help="automatically apply fixup! and squash! commits to their targets",
    )
    autosquash_group.add_argument(
        "--no-autosquash",
        action="store_true",
        help="force disable revise.autoSquash behaviour",
    )

    index_group = parser.add_mutually_exclusive_group()
    index_group.add_argument(
        "--no-index",
        action="store_true",
        help="ignore the index while rewriting history",
    )
    index_group.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="stage all tracked files before running",
    )
    index_group.add_argument(
        "--patch",
        "-p",
        action="store_true",
        help="interactively stage hunks before running",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="interactively edit commit stack",
    )
    mode_group.add_argument(
        "--message",
        "-m",
        action="append",
        help="specify commit message on command line",
    )
    mode_group.add_argument(
        "--cut",
        "-c",
        action="store_true",
        help="interactively cut a commit into two smaller commits",
    )

    gpg_group = parser.add_mutually_exclusive_group()
    gpg_group.add_argument(
        "--gpg-sign",
        "-S",
        action="store_true",
        help="GPG sign commits",
    )
    gpg_group.add_argument(
        "--no-gpg-sign",
        action="store_true",
        help="do not GPG sign commits",
    )
    return parser


def interactive(
    args: Namespace, repo: Repository, staged: Optional[Commit], head: Reference[Commit]
) -> None:
    assert head.target is not None

    if args.target or args.root:
        base = repo.get_commit(args.target) if args.target else None
        to_rebase = commit_range(base, head.target)
    else:
        base, to_rebase = local_commits(repo, head.target)

    # Build up an initial todos list, edit that todos list.
    todos = original = build_todos(to_rebase, staged)

    if enable_autosquash(args, repo):
        todos = autosquash_todos(todos)

    if args.interactive:
        todos = edit_todos(repo, todos, msgedit=args.edit)

    if todos != original:
        # Perform the todo list actions.
        new_head = apply_todos(base, todos, reauthor=args.reauthor)

        # Update the value of HEAD to the new state.
        update_head(head, new_head, None)
    else:
        print("(warning) no changes performed", file=sys.stderr)


def enable_autosquash(args: Namespace, repo: Repository) -> bool:
    if args.autosquash:
        return True
    if args.no_autosquash:
        return False

    return repo.bool_config(
        "revise.autoSquash",
        default=repo.bool_config("rebase.autoSquash", default=False),
    )


def noninteractive(
    args: Namespace, repo: Repository, staged: Optional[Commit], head: Reference[Commit]
) -> None:
    assert head.target is not None

    if args.root:
        raise ValueError(
            "Incompatible option: "
            "--root may only be used with --autosquash or --interactive"
        )

    if args.target is None:
        raise ValueError("<target> is a required argument")

    head = repo.get_commit_ref(args.ref)
    if head.target is None:
        raise ValueError("Invalid target reference")

    current = replaced = repo.get_commit(args.target)
    to_rebase = commit_range(current, head.target)

    # Apply changes to the target commit.
    final = head.target.tree()
    if staged:
        print(f"Applying staged changes to '{args.target}'")
        current = current.update(tree=staged.rebase(current).tree())
        final = staged.rebase(head.target).tree()

    # Update the commit message on the target commit if requested.
    if args.message:
        message = b"\n".join(l.encode("utf-8") + b"\n" for l in args.message)
        current = current.update(message=message)

    # Prompt the user to edit the commit message if requested.
    if args.edit:
        current = edit_commit_message(current)

    # Rewrite the author to match the current user if requested.
    if args.reauthor:
        current = current.update(author=repo.default_author)

    # If the commit should be cut, prompt the user to perform the cut.
    if args.cut:
        current = cut_commit(current)

    # Add or remove GPG signatures.
    if repo.sign_commits != bool(current.gpgsig):
        current = current.update(recommit=True)
    change_signature = any(
        repo.sign_commits != bool(commit.gpgsig) for commit in to_rebase
    )

    if current != replaced or change_signature:
        print(f"{current.oid.short()} {current.summary()}")

        # Rebase commits atop the commit range.
        for commit in to_rebase:
            if repo.sign_commits != bool(commit.gpgsig):
                commit = commit.update(recommit=True)
            current = commit.rebase(current)
            print(f"{current.oid.short()} {current.summary()}")

        update_head(head, current, final)
    else:
        print("(warning) no changes performed", file=sys.stderr)


def inner_main(args: Namespace, repo: Repository) -> None:
    # If '-a' or '-p' was specified, stage changes.
    if args.all:
        repo.git("add", "-u")
    if args.patch:
        repo.git("add", "-p")

    if args.gpg_sign:
        repo.sign_commits = True
    if args.no_gpg_sign:
        repo.sign_commits = False

    # Create a commit with changes from the index
    staged = None
    if not args.no_index:
        staged = repo.index.commit(message=b"<git index>")
        if staged.tree() == staged.parent_tree():
            staged = None  # No changes, ignore the commit

    # Determine the HEAD reference which we're going to update.
    head = repo.get_commit_ref(args.ref)
    if head.target is None:
        raise ValueError("Head reference not found!")

    # Either enter the interactive or non-interactive codepath.
    if args.interactive or args.autosquash:
        interactive(args, repo, staged, head)
    else:
        noninteractive(args, repo, staged, head)


def main(argv: Optional[List[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        with Repository() as repo:
            inner_main(args, repo)
    except CalledProcessError as err:
        print(f"subprocess exited with non-zero status: {err.returncode}")
        sys.exit(1)
    except EditorError as err:
        print(f"editor error: {err}")
        sys.exit(1)
    except MergeConflict as err:
        print(f"merge conflict: {err}")
        sys.exit(1)
    except ValueError as err:
        print(f"invalid value: {err}")
        sys.exit(1)
