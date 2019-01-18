"""
zipfix is a library for efficiently working with changes in git repositories.
It holds an in-memory copy of the object database and supports efficient
in-memory merges and rebases.
"""

from typing import Tuple, List, Optional
from argparse import ArgumentParser
from pathlib import Path
import subprocess
import textwrap
import sys

# Re-export primitives from the odb module to expose them at the root.
from .odb import MissingObject, Oid, Signature, Repository, GitObj, Commit, Mode, Entry, Tree, Blob

from .utils import run_editor

__version__ = '0.1'


def commit_range(base: Commit, tip: Commit) -> List[Commit]:
    """Oldest-first iterator over the given commit range,
    not including the commit |base|"""
    commits = []
    while tip != base:
        commits.append(tip)
        tip = tip.parent()
    commits.reverse()
    return commits


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
    msg_group.add_argument('--edit', '-e', action='store_true',
                           help='edit commit message of targeted commit')
    msg_group.add_argument('--message', '-m', action='append',
                           help='specify commit message on command line')
    return parser


def main(argv):
    args = parser().parse_args(argv)

    repo = Repository()

    final = head = repo.getcommit(args.ref)
    current = replaced = repo.getcommit(args.target)
    to_rebase = commit_range(current, head)

    if args.all:
        print("Staging all changes")
        if subprocess.run(["git", "add", "-u"]).returncode != 0:
            print("Couldn't stage changes", file=sys.stderr)
            sys.exit(1)

    # If --no-index was not supplied, apply staged changes to the target.
    if not args.no_index:
        final = repo.commit_staged(b"<git index>")
        if final.tree() != head.tree():
            print(f"Applying staged changes to '{args.target}'")
            current = current.update(tree=final.rebase(current).tree())

    # Update the commit message on the target commit if requested.
    if args.message:
        message = b'\n'.join(l.encode('utf-8') + b'\n' for l in args.message)
        current = current.update(message=message)

    # Prompt the user to edit the commit message if requested.
    if args.edit:
        message = run_editor('COMMIT_EDITMSG', current.message, comments="""\
            Please enter the commit message for your changes. Lines starting
            with '#' will be ignored, and an empty message aborts the commit.
            """)
        current = current.update(message=message)

    # Rewrite the author to match the current user if requested.
    if args.reauthor:
        current = current.update(author=repo.default_author)

    if current != replaced:
        print(f"{str(current.oid)[:16]} {current.summary()}")

        # Rebase commits atop the commit range.
        for commit in to_rebase:
            current = commit.rebase(current)
            print(f"{str(current.oid)[:16]} {current.summary()}")

        # Update the HEAD commit to point to the new value.
        print(f"Updating {args.ref} ({head.oid} => {current.oid})")
        current.update_ref(args.ref, "git-zipfix rewrite", head.oid)

        # We expect our tree to match the tree we started with (including index
        # changes). If it does not, print out a warning.
        if current.tree() != final.tree():
            print("(warning) unexpected final tree\n"
                  f"(note) expected: {final.tree().oid}\n"
                  f"(note) actual: {current.tree().oid}\n"
                  "(note) working directory & index have not been updated.\n"
                  "(note) use `git status` to see what has changed.",
                  file=sys.stderr)
            sys.exit(1)
    else:
        print(f"(warning) no changes performed", file=sys.stderr)
