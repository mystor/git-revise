# pylint: skip-file

import textwrap
from conftest import *


@pytest.mark.parametrize("target", ["HEAD", "HEAD~", "HEAD~~"])
@pytest.mark.parametrize("use_editor", [True, False])
def test_reword(repo: Repository, target: str, use_editor: bool) -> None:
    bash(
        """
        echo "hello, world" > file1
        git add file1
        git commit -m "commit 1"
        echo "new line!" >> file1
        git add file1
        git commit -m "commit 2"
        echo "yet another line!" >> file1
        git add file1
        git commit -m "commit 3"
        """
    )

    message = textwrap.dedent(
        """\
        reword test

        another line
        """
    ).encode()

    old = repo.get_commit(target)
    assert old.message != message
    assert old.persisted

    if use_editor:
        with editor_main(["--no-index", "-e", target]) as ed:
            with ed.next_file() as f:
                assert f.startswith(old.message)
                f.replace_dedent(message)
    else:
        main(["--no-index", "-m", "reword test", "-m", "another line", target])

    new = repo.get_commit(target)
    assert old != new, "commit was modified"
    assert old.tree() == new.tree(), "tree is unchanged"
    assert old.parents() == new.parents(), "parents are unchanged"

    assert new.message == message, "message set correctly"
    assert new.persisted, "commit persisted to disk"
    assert new.author == old.author, "author is unchanged"
