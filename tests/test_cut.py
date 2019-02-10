# pylint: skip-file

from io import StringIO
from gitrevise.tui import main


def test_cut(repo, bash, fake_editor, monkeypatch):
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

    monkeypatch.setattr("sys.stdin", StringIO("y\nn\n"))

    def editor(inq, outq):
        assert inq.get().startswith(b"[1] commit 2\n")
        outq.put(b"part 1\n")

        assert inq.get().startswith(b"[2] commit 2\n")
        outq.put(b"part 2\n")

    with fake_editor(editor):
        main(["--cut", "HEAD~"])

    new = repo.get_commit("HEAD")
    new_u2 = new.parent()
    new_u1 = new_u2.parent()
    new_uu = new_u1.parent()

    assert prev != new
    assert prev.message == new.message
    assert new_u2.message == b"part 2\n"
    assert new_u1.message == b"part 1\n"
    assert new_uu == prev_uu
