# pylint: disable=not-context-manager

from gitrevise.odb import Repository
from .conftest import bash, editor_main


def test_cut(repo: Repository) -> None:
    bash(
        """
        echo "Hello, World" >> file1
        git add file1
        git commit -m "commit 1"

        echo "Append f1" >> file1
        echo "Make f2" >> file2
        git add file1 file2
        git commit -m "commit 2"

        echo "Append f3" >> file2
        git add file2
        git commit -m "commit 3"
        """
    )

    prev = repo.get_commit("HEAD")
    prev_u = prev.parent()
    prev_uu = prev_u.parent()

    with editor_main(["--cut", "HEAD~"], input=b"y\nn\n") as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent("[1] commit 2\n")
            f.replace_dedent("part 1\n")

        with ed.next_file() as f:
            assert f.startswith_dedent("[2] commit 2\n")
            f.replace_dedent("part 2\n")

    new = repo.get_commit("HEAD")
    new_u2 = new.parent()
    new_u1 = new_u2.parent()
    new_uu = new_u1.parent()

    assert prev != new
    assert prev.message == new.message
    assert new_u2.message == b"part 2\n"
    assert new_u1.message == b"part 1\n"
    assert new_uu == prev_uu


def test_cut_root(repo: Repository) -> None:
    bash(
        """
        echo "Hello, World" >> file1
        echo "Make f2" >> file2
        git add file1 file2
        git commit -m "root commit"
        """
    )

    prev = repo.get_commit("HEAD")
    assert prev.is_root
    assert len(prev.parent_oids) == 0

    with editor_main(["--cut", "HEAD"], input=b"y\nn\n") as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent("[1] root commit\n")
            f.replace_dedent("part 1\n")

        with ed.next_file() as f:
            assert f.startswith_dedent("[2] root commit\n")
            f.replace_dedent("part 2\n")

    new = repo.get_commit("HEAD")
    assert new != prev
    assert new.message == b"part 2\n"

    assert not new.is_root
    assert len(new.parent_oids) == 1

    new_u = new.parent()
    assert new_u.message == b"part 1\n"
    assert new_u.is_root
    assert len(new_u.parent_oids) == 0
    assert new_u.parent_tree() == prev.parent_tree()

    assert new_u != new
    assert new_u != prev
