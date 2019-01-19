"""
zipfix is a library for efficiently working with changes in git repositories.
It holds an in-memory copy of the object database and supports efficient
in-memory merges and rebases.
"""

from typing import Tuple, List, Optional
from argparse import ArgumentParser, Namespace
from pathlib import Path
import subprocess
import textwrap
import sys

from .odb import Repository, Commit
from .utils import commit_range, run_editor, edit_commit_message, update_head
from .todo import apply_todos, build_todos, edit_todos, StepKind

__version__ = '0.1'


def parser() -> ArgumentParser:
    parser = ArgumentParser(description='''\
        Rebase staged changes onto the given commit, and rewrite history to
        incorporate these changes.''')
    parser.add_argument('target', help='target commit to apply fixups to')
    parser.add_argument('--ref', default='HEAD', help='reference to update')
    parser.add_argument('--reauthor', action='store_true',
                        help='reset the author of the targeted commit')
    parser.add_argument('--version', action='version', version=__version__)

    index_group = parser.add_mutually_exclusive_group()
    index_group.add_argument('--no-index', action='store_true',
                             help='ignore the index while rewriting history')
    index_group.add_argument('--all', '-a', action='store_true',
                             help='stage all tracked files before running')

    msg_group = parser.add_mutually_exclusive_group()
    msg_group.add_argument('--interactive', '-i', action='store_true',
                           help='interactively edit commit stack')
    msg_group.add_argument('--edit', '-e', action='store_true',
                           help='edit commit message of targeted commit')
    msg_group.add_argument('--message', '-m', action='append',
                           help='specify commit message on command line')
    return parser


def interactive(args: Namespace, repo: Repository, staged: Optional[Commit]):
    head = repo.get_commit(args.ref)
    target = repo.get_commit(args.target)
    to_rebase = commit_range(target, head)

    # Build up an initial todos list, edit that todos list.
    current = build_todos(to_rebase, staged)
    todos = edit_todos(repo, current)
    if current == todos:
        print("(warning) no changes performed", file=sys.stderr)
        return

    # Perform the todo list actions.
    new_head = apply_todos(target, todos, reauthor=args.reauthor)

    # Update the value of HEAD to the new state.
    update_head(args.ref, head, new_head, None)


def noninteractive(args: Namespace, repo: Repository, staged: Optional[Commit]):
    head = repo.get_commit(args.ref)
    current = replaced = repo.get_commit(args.target)
    to_rebase = commit_range(current, head)

    # Apply changes to the target commit.
    final = head.tree()
    if staged:
        print(f"Applying staged changes to '{args.target}'")
        current = current.update(tree=staged.rebase(current).tree())
        final = staged.rebase(head).tree()

    # Update the commit message on the target commit if requested.
    if args.message:
        message = b'\n'.join(l.encode('utf-8') + b'\n' for l in args.message)
        current = current.update(message=message)

    # Prompt the user to edit the commit message if requested.
    if args.edit:
        current = edit_commit_message(current)

    # Rewrite the author to match the current user if requested.
    if args.reauthor:
        current = current.update(author=repo.default_author)

    if current != replaced:
        print(f"{current.oid.short()} {current.summary()}")

        # Rebase commits atop the commit range.
        for commit in to_rebase:
            current = commit.rebase(current)
            print(f"{current.oid.short()} {current.summary()}")

        update_head(args.ref, head, current, final)
    else:
        print(f"(warning) no changes performed", file=sys.stderr)


def main(argv):
    args = parser().parse_args(argv)
    repo = Repository()

    # If '-a' was specified, stage all changes.
    if args.all:
        print("Staging all changes")
        if subprocess.run(["git", "add", "-u"]).returncode != 0:
            print("Couldn't stage changes", file=sys.stderr)
            sys.exit(1)

    # Create a commit with changes from the index
    staged = None if args.no_index else repo.commit_staged(b"<git index>")
    if staged and staged.tree() == staged.parent().tree():
        staged = None  # No changes, ignore the commit

    # Either enter the interactive or non-interactive codepath.
    if args.interactive:
        interactive(args, repo, staged)
    else:
        noninteractive(args, repo, staged)

