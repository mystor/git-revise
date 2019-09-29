# pylint: skip-file

from conftest import *
import os


@pytest.fixture
def basic_repo(repo):
    bash(
        """
        cat <<EOF >file1
        Hello, World!
        How are things?
        EOF
        git add file1
        git commit -m "commit1"

        cat <<EOF >file1
        Hello, World!
        Oops, gotta add a new line!
        How are things?
        EOF
        git add file1
        git commit -m "commit2"
        """
    )
    return repo


def fixup_helper(repo, flags, target, message=None):
    old = repo.get_commit(target)
    assert old.persisted

    bash(
        """
        echo "extra line" >> file1
        git add file1
        """
    )

    main(flags + [target])

    new = repo.get_commit(target)
    assert old != new, "commit was modified"
    assert old.parents() == new.parents(), "parents are unchanged"

    assert old.tree() != new.tree(), "tree is changed"

    if message is None:
        assert new.message == old.message, "message should not be changed"
    else:
        assert new.message == message.encode(), "message set correctly"

    assert new.persisted, "commit persisted to disk"
    assert new.author == old.author, "author is unchanged"
    assert new.committer == repo.default_committer, "committer is updated"


def test_fixup_head(basic_repo):
    fixup_helper(basic_repo, [], "HEAD")


def test_fixup_nonhead(basic_repo):
    fixup_helper(basic_repo, [], "HEAD~")


def test_fixup_head_msg(basic_repo):
    fixup_helper(
        basic_repo,
        ["-m", "fixup_head test", "-m", "another line"],
        "HEAD",
        "fixup_head test\n\nanother line\n",
    )


def test_fixup_nonhead_msg(basic_repo):
    fixup_helper(
        basic_repo,
        ["-m", "fixup_nonhead test", "-m", "another line"],
        "HEAD~",
        "fixup_nonhead test\n\nanother line\n",
    )


def test_fixup_head_editor(basic_repo):
    old = basic_repo.get_commit("HEAD")
    newmsg = "fixup_head_editor test\n\nanother line\n"

    with Editor() as ed, in_parallel(fixup_helper, basic_repo, ["-e"], "HEAD", newmsg):
        with ed.next_file() as f:
            assert f.startswith(old.message)
            f.replace_dedent(newmsg)


def test_fixup_nonhead_editor(basic_repo):
    old = basic_repo.get_commit("HEAD~")
    newmsg = "fixup_nonhead_editor test\n\nanother line\n"

    with Editor() as ed, in_parallel(fixup_helper, basic_repo, ["-e"], "HEAD~", newmsg):
        with ed.next_file() as f:
            assert f.startswith(old.message)
            f.replace_dedent(newmsg)


def test_fixup_nonhead_conflict(basic_repo):
    import textwrap

    bash('echo "conflict" > file1')
    bash("git add file1")

    old = basic_repo.get_commit("HEAD~")
    assert old.persisted

    with Editor() as ed, in_parallel(main, ["HEAD~"], input=b"y\ny\ny\ny\n"):
        with ed.next_file() as f:
            assert f.equals_dedent(
                f"""\
                <<<<<<< {os.sep}file1 (new parent)
                Hello, World!
                How are things?
                =======
                conflict
                >>>>>>> {os.sep}file1 (incoming)
                """
            )
            f.replace_dedent("conflict1\n")

        with ed.next_file() as f:
            assert f.equals_dedent(
                f"""\
                <<<<<<< {os.sep}file1 (new parent)
                conflict1
                =======
                Hello, World!
                Oops, gotta add a new line!
                How are things?
                >>>>>>> {os.sep}file1 (incoming)
                """
            )
            f.replace_dedent("conflict2\n")

    new = basic_repo.get_commit("HEAD~")
    assert new.persisted
    assert new != old


def test_autosquash_nonhead(repo):
    bash(
        """
        echo "hello, world" > file1
        git add file1
        git commit -m "commit one"

        echo "second file" > file2
        git add file2
        git commit -m "commit two"

        echo "new line!" >> file1
        git add file1
        git commit -m "commit three"

        echo "extra line" >> file2
        git add file2
        git commit --fixup=HEAD~
        """
    )

    old = repo.get_commit("HEAD~~")
    assert old.persisted

    main(["--autosquash", str(old.parent().oid)])

    new = repo.get_commit("HEAD~")
    assert old != new, "commit was modified"
    assert old.parents() == new.parents(), "parents are unchanged"

    assert old.tree() != new.tree(), "tree is changed"

    assert new.message == old.message, "message should not be changed"

    assert new.persisted, "commit persisted to disk"
    assert new.author == old.author, "author is unchanged"
    assert new.committer == repo.default_committer, "committer is updated"
