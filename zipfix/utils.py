from typing import Optional

from pathlib import Path
import tempfile

import subprocess
import textwrap
import sys

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
