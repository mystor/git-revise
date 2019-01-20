import zipfix
from zipfix import Commit


def reword_helper(repo, flags, target, message):
    old = repo.get_commit(target)
    assert old.message != message.encode()
    assert old.persisted

    zipfix.main(flags + [target])

    new = repo.get_commit(target)
    assert old != new, "commit was modified"
    assert old.tree() == new.tree(), "tree is unchanged"
    assert old.parents() == new.parents(), "parents are unchanged"

    assert new.message == message.encode(), "message set correctly"
    assert new.persisted, "commit persisted to disk"
    assert new.author == old.author, "author is unchanged"
    assert new.committer == repo.default_committer, "committer is updated"


def test_reword_head(repo):
    repo.load_template("basic")
    reword_helper(
        repo,
        ["--no-index", "-m", "reword_head test", "-m", "another line"],
        "HEAD",
        "reword_head test\n\nanother line\n",
    )


def test_reword_nonhead(repo):
    repo.load_template("basic")
    reword_helper(
        repo,
        ["--no-index", "-m", "reword_nonhead test", "-m", "another line"],
        "HEAD~",
        "reword_nonhead test\n\nanother line\n",
    )


def test_reword_head_editor(repo, fake_editor):
    repo.load_template("basic")

    old = repo.get_commit("HEAD")

    def editor(inq, outq):
        assert inq.get().startswith(old.message)
        outq.put(b"reword_head_editor test\n\nanother line\n")

    with fake_editor(editor):
        reword_helper(
            repo,
            ["--no-index", "-e"],
            "HEAD",
            "reword_head_editor test\n\nanother line\n",
        )


def test_reword_nonhead_editor(repo, fake_editor):
    repo.load_template("basic")

    old = repo.get_commit("HEAD~")

    def editor(inq, outq):
        assert inq.get().startswith(old.message)
        outq.put(b"reword_nonhead_editor test\n\nanother line\n")

    with fake_editor(editor):
        reword_helper(
            repo,
            ["--no-index", "-e"],
            "HEAD~",
            "reword_nonhead_editor test\n\nanother line\n",
        )


def test_reword_root(repo, bash):
    bash(
        """
        echo "hello, world" > file1
        git add file1
        git commit -m "initial commit"
        echo "new line!" >> file1
        git add file1
        git commit -m "another commit"
        """
    )

    old = repo.get_commit("HEAD~")
    assert old.parents() == []
    assert old.message == b"initial commit\n"

    zipfix.main(["-m", "my new message", "HEAD~"])

    new = repo.get_commit("HEAD~")
    assert new.parents() == []
    assert new.message == b"my new message\n"
