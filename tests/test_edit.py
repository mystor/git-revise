from gitrevise.odb import Repository

from .conftest import main


# pylint: disable=unused-argument
def test_edit_illegal_extra_argument(repo: Repository) -> None:
    process = main(["--edit", "HEAD", "HEAD"], check=False, capture_output=True)
    assert b"error: unrecognized arguments" in process.stderr
    assert process.returncode != 0
