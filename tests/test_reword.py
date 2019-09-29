# pylint: skip-file

import textwrap
from conftest import *


@pytest.fixture
def basic_repo(repo, bash):
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


def reword_helper(repo, main, flags, target, message):
    message = textwrap.dedent(message).encode()

    old = repo.get_commit(target)
    assert old.message != message
    assert old.persisted

    main(flags + [target])

    new = repo.get_commit(target)
    assert old != new, "commit was modified"
    assert old.tree() == new.tree(), "tree is unchanged"
    assert old.parents() == new.parents(), "parents are unchanged"

    assert new.message == message, "message set correctly"
    assert new.persisted, "commit persisted to disk"
    assert new.author == old.author, "author is unchanged"
    assert new.committer == repo.default_committer, "committer is updated"


def test_reword_head(basic_repo, main):
    reword_helper(
        basic_repo,
        main,
        ["--no-index", "-m", "reword_head test", "-m", "another line"],
        "HEAD",
        "reword_head test\n\nanother line\n",
    )


def test_reword_nonhead(basic_repo, main):
    reword_helper(
        basic_repo,
        main,
        ["--no-index", "-m", "reword_nonhead test", "-m", "another line"],
        "HEAD~",
        "reword_nonhead test\n\nanother line\n",
    )


def test_reword_head_editor(basic_repo, main):
    old = basic_repo.get_commit("HEAD")
    new_message = """\
        reword_head_editor test

        another line
        """

    with Editor() as ed, in_parallel(
        reword_helper, basic_repo, main, ["--no-index", "-e"], "HEAD", new_message
    ):
        with ed.next_file() as f:
            assert f.startswith(old.message)
            f.replace_dedent(new_message)


def test_reword_nonhead_editor(basic_repo, main):
    old = basic_repo.get_commit("HEAD~")
    new_message = """\
        reword_nonhead_editor test

        another line
        """

    with Editor() as ed, in_parallel(
        reword_helper, basic_repo, main, ["--no-index", "-e"], "HEAD~", new_message
    ):
        with ed.next_file() as f:
            assert f.startswith(old.message)
            f.replace_dedent(new_message)


def test_reword_root(repo, main, bash):
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

    main(["-m", "my new message", "HEAD~"])

    new = repo.get_commit("HEAD~")
    assert new.parents() == []
    assert new.message == b"my new message\n"
