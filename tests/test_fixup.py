# pylint: skip-file

from io import StringIO
from gitrevise.tui import main


def fixup_helper(repo, bash, flags, target, message=None):
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


def test_fixup_head(repo, bash):
    repo.load_template("basic")
    fixup_helper(repo, bash, [], "HEAD")


def test_fixup_nonhead(repo, bash):
    repo.load_template("basic")
    fixup_helper(repo, bash, [], "HEAD~")


def test_fixup_head_msg(repo, bash):
    repo.load_template("basic")
    fixup_helper(
        repo,
        bash,
        ["-m", "fixup_head test", "-m", "another line"],
        "HEAD",
        "fixup_head test\n\nanother line\n",
    )


def test_fixup_nonhead_msg(repo, bash):
    repo.load_template("basic")
    fixup_helper(
        repo,
        bash,
        ["-m", "fixup_nonhead test", "-m", "another line"],
        "HEAD~",
        "fixup_nonhead test\n\nanother line\n",
    )


def test_fixup_head_editor(repo, bash, fake_editor):
    repo.load_template("basic")

    old = repo.get_commit("HEAD")
    newmsg = "fixup_head_editor test\n\nanother line\n"

    def editor(inq, outq):
        assert inq.get().startswith(old.message)
        outq.put(newmsg.encode())

    with fake_editor(editor):
        fixup_helper(repo, bash, ["-e"], "HEAD", newmsg)


def test_fixup_nonhead_editor(repo, bash, fake_editor):
    repo.load_template("basic")

    old = repo.get_commit("HEAD~")
    newmsg = "fixup_nonhead_editor test\n\nanother line\n"

    def editor(inq, outq):
        assert inq.get().startswith(old.message)
        outq.put(newmsg.encode())

    with fake_editor(editor):
        fixup_helper(repo, bash, ["-e"], "HEAD~", newmsg)


def test_fixup_nonhead_conflict(repo, bash, fake_editor, monkeypatch):
    import textwrap

    repo.load_template("basic")
    bash('echo "conflict" > file1')
    bash("git add file1")

    old = repo.get_commit("HEAD~")
    assert old.persisted

    def editor(inq, outq):
        assert (
            textwrap.dedent(
                """\
                <<<<<<< /file1 (new parent)
                Hello, World!

                =======
                conflict
                >>>>>>> /file1 (incoming)
                """
            ).encode()
            == inq.get()
        )
        outq.put(b"conflict1\n")

        assert (
            textwrap.dedent(
                """\
                <<<<<<< /file1 (new parent)
                conflict1
                =======
                Hello, World!
                Oops, gotta add a new line!

                >>>>>>> /file1 (incoming)
                """
            ).encode()
            == inq.get()
        )
        outq.put(b"conflict2\n")

    with fake_editor(editor):
        monkeypatch.setattr("sys.stdin", StringIO("y\ny\ny\ny\n"))

        main(["HEAD~"])

        new = repo.get_commit("HEAD~")
        assert new.persisted
        assert new != old


def test_autosquash_nonhead(repo, bash):
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
