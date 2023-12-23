from subprocess import CalledProcessError

import pytest

from gitrevise.odb import Repository

from .conftest import main

def test_edit_illegal_extra_argument(repo: Repository) -> None:
    p = main(["--edit", "HEAD", "HEAD"], check=False, capture_output=True)
    assert b'error: unrecognized arguments' in p.stderr
    assert p.returncode != 0
