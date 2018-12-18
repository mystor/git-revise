"""
zipfix is a library for efficiently working with changes in git repositories.
It holds an in-memory copy of the object database and supports efficient
in-memory merges and rebases.
"""

from typing import Tuple, List, Optional
from pathlib import Path
import subprocess
import tempfile
import textwrap
import sys

# Re-export primitives from the odb module to expose them at the root.
from .odb import MissingObject, Oid, Signature, GitObj, Commit, Mode, Entry, Tree, Blob

def commit_range(base: Commit, tip: Commit) -> List[Commit]:
    """Oldest-first iterator over the given commit range,
    not including the commit |base|"""
    commits = []
    while tip != base:
        commits.append(tip)
        tip = tip.parent()
    commits.reverse()
    return commits

def run_editor(filename: str, text: bytes,
               comments: Optional[str] = None,
               allow_empty: bool = False) -> bytes:
    """Run the editor configured for git to edit the given text"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / filename
        with open(path, 'wb') as f:
            for line in text.splitlines():
                f.write(line + b'\n')

            if comments:  # If comments were provided, write them after the text.
                f.write(b'\n')
                for comment in textwrap.dedent(comments).splitlines():
                    f.write(b'# ' + comment.encode('utf-8') + b'\n')

        # Invoke the editor
        proc = subprocess.run([
            "bash", "-c", f"exec $(git var GIT_EDITOR) '{path}'"])
        if proc.returncode != 0:
            print("editor exited with a non-zero exit code", file=sys.stderr)
            sys.exit(1)

        # Read in all lines from the edited file.
        lines = []
        with open(path, 'rb') as of:
            for line in of.readlines():
                if comments and line.startswith(b'#'):
                    continue
                lines.append(line)

        # Concatenate parsed lines, stripping trailing newlines.
        data = b''.join(lines).rstrip() + b'\n'
        if data == b'\n' and not allow_empty:
            print("empty file - aborting", file=sys.stderr)
            sys.exit(1)
        return data
