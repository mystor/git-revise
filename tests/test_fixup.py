from contextlib import contextmanager
from typing import Generator, Optional, Sequence

import pytest

from gitrevise.odb import Repository
from gitrevise.todo import StepKind, autosquash_todos, build_todos
from gitrevise.utils import commit_range

from .conftest import Editor, bash, editor_main, main


@pytest.fixture(name="basic_repo")
def fixture_basic_repo(repo: Repository) -> Repository:
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


def fixup_helper(
    repo: Repository,
    flags: Sequence[str],
    target: str,
    message: Optional[str] = None,
) -> None:
    with fixup_helper_editor(repo=repo, flags=flags, target=target, message=message):
        pass


@contextmanager
def fixup_helper_editor(
    repo: Repository,
    flags: Sequence[str],
    target: str,
    message: Optional[str] = None,
) -> Generator[Editor, None, None]:
    old = repo.get_commit(target)
    assert old.persisted

    bash(
        """
        echo "extra line" >> file1
        git add file1
        """
    )

    with editor_main((*flags, target)) as ed:
        yield ed

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


def test_fixup_head(basic_repo: Repository) -> None:
    fixup_helper(basic_repo, [], "HEAD")


def test_fixup_nonhead(basic_repo: Repository) -> None:
    fixup_helper(basic_repo, [], "HEAD~")


def test_fixup_head_msg(basic_repo: Repository) -> None:
    fixup_helper(
        basic_repo,
        ["-m", "fixup_head test", "-m", "another line"],
        "HEAD",
        "fixup_head test\n\nanother line\n",
    )


def test_fixup_nonhead_msg(basic_repo: Repository) -> None:
    fixup_helper(
        basic_repo,
        ["-m", "fixup_nonhead test", "-m", "another line"],
        "HEAD~",
        "fixup_nonhead test\n\nanother line\n",
    )


def test_fixup_head_editor(basic_repo: Repository) -> None:
    old = basic_repo.get_commit("HEAD")
    newmsg = "fixup_head_editor test\n\nanother line\n"

    with fixup_helper_editor(basic_repo, ["-e"], "HEAD", newmsg) as ed:
        with ed.next_file() as f:
            assert f.startswith(old.message)
            f.replace_dedent(newmsg)


def test_fixup_nonhead_editor(basic_repo: Repository) -> None:
    old = basic_repo.get_commit("HEAD~")
    newmsg = "fixup_nonhead_editor test\n\nanother line\n"

    with fixup_helper_editor(basic_repo, ["-e"], "HEAD~", newmsg) as ed:
        with ed.next_file() as f:
            assert f.startswith(old.message)
            f.replace_dedent(newmsg)


def test_fixup_nonhead_conflict(basic_repo: Repository) -> None:
    bash('echo "conflict" > file1')
    bash("git add file1")

    old = basic_repo.get_commit("HEAD~")
    assert old.persisted

    with editor_main(["HEAD~"], input=b"y\ny\ny\ny\n") as ed:
        with ed.next_file() as f:
            assert f.equals_dedent(
                """\
                <<<<<<< file1 (new parent): commit1
                Hello, World!
                How are things?
                =======
                conflict
                >>>>>>> file1 (current): <git index>
                """
            )
            f.replace_dedent("conflict1\n")

        with ed.next_file() as f:
            assert f.equals_dedent(
                """\
                <<<<<<< file1 (new parent): commit1
                conflict1
                =======
                Hello, World!
                Oops, gotta add a new line!
                How are things?
                >>>>>>> file1 (current): commit2
                """
            )
            f.replace_dedent("conflict2\n")

    new = basic_repo.get_commit("HEAD~")
    assert new.persisted
    assert new != old


def test_autosquash_nonhead(repo: Repository) -> None:
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

    file1 = new.tree().entries[b"file1"].blob().body
    assert file1 == b"hello, world\n"
    file2 = new.tree().entries[b"file2"].blob().body
    assert file2 == b"second file\nextra line\n"


def test_fixup_of_fixup(repo: Repository) -> None:
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

        echo "even more" >> file2
        git add file2
        git commit --fixup=HEAD
        """
    )

    old = repo.get_commit("HEAD~~~")
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

    file1 = new.tree().entries[b"file1"].blob().body
    assert file1 == b"hello, world\n"
    file2 = new.tree().entries[b"file2"].blob().body
    assert file2 == b"second file\nextra line\neven more\n"


def test_fixup_by_id(repo: Repository) -> None:
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
        git commit -m "fixup! $(git rev-parse HEAD~)"
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

    file1 = new.tree().entries[b"file1"].blob().body
    assert file1 == b"hello, world\n"
    file2 = new.tree().entries[b"file2"].blob().body
    assert file2 == b"second file\nextra line\n"


def test_fixup_order(repo: Repository) -> None:
    bash(
        """
        git commit --allow-empty -m 'old'
        git commit --allow-empty -m 'target commit'
        git commit --allow-empty -m 'first fixup'  --fixup=HEAD
        git commit --allow-empty -m 'second fixup' --fixup=HEAD~
        """
    )

    old = repo.get_commit("HEAD~3")
    assert old.persisted
    tip = repo.get_commit("HEAD")
    assert tip.persisted

    todos = build_todos(commit_range(old, tip), index=None)
    [target, first, second] = autosquash_todos(todos)

    assert b"target commit" in target.commit.message
    assert b"first fixup" in first.commit.message
    assert b"second fixup" in second.commit.message


def test_fixup_order_transitive(repo: Repository) -> None:
    bash(
        """
        git commit --allow-empty -m 'old'
        git commit --allow-empty -m 'target commit'
        git commit --allow-empty -m '1.0' --fixup=HEAD
        git commit --allow-empty -m '1.1' --fixup=HEAD
        git commit --allow-empty -m '2.0' --fixup=HEAD~2
        """
    )

    old = repo.get_commit("HEAD~4")
    assert old.persisted
    tip = repo.get_commit("HEAD")
    assert tip.persisted

    todos = build_todos(commit_range(old, tip), index=None)
    [target, a, b, c] = autosquash_todos(todos)  # pylint: disable=invalid-name

    assert b"target commit" in target.commit.message
    assert b"1.0" in a.commit.message
    assert b"1.1" in b.commit.message
    assert b"2.0" in c.commit.message


def test_fixup_order_cycle(repo: Repository) -> None:
    bash(
        """
        git commit --allow-empty -m 'old'
        git commit --allow-empty -m 'fixup! fixup!' # Cannot fixup self.
        git commit --allow-empty -m 'fixup! future commit' # Cannot fixup future commit.
        git commit --allow-empty -m 'future commit'
        """
    )

    old = repo.get_commit("HEAD~3")
    assert old.persisted
    tip = repo.get_commit("HEAD")
    assert tip.persisted

    todos = build_todos(commit_range(old, tip), index=None)

    new_todos = autosquash_todos(todos)
    assert len(new_todos) == 3
    assert all(step.kind == StepKind.PICK for step in new_todos)


def test_autosquash_multiline_summary(repo: Repository) -> None:
    bash(
        """
        git commit --allow-empty -m 'initial commit'
        git commit --allow-empty -m 'multi
        line
        summary

        body goes here
        '

        echo >file
        git add file
        git commit --fixup=HEAD
        """
    )

    old = repo.get_commit("HEAD~")
    assert old.persisted

    main(["--autosquash"])

    new = repo.get_commit("HEAD")
    assert old != new, "commit was modified"
    assert old.parents() == new.parents(), "parents are unchanged"


def test_autosquash_multiple_squashes() -> None:
    bash(
        """
        git commit --allow-empty -m 'initial commit'
        git commit --allow-empty -m 'target'
        git commit --allow-empty --squash :/^target --no-edit
        git commit --allow-empty --squash :/^target --no-edit
        """
    )

    with editor_main([":/^init", "--autosquash"], input=b"") as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent(
                """\
                # This is a combination of 3 commits.
                # This is the 1st commit message:

                target

                # This is the commit message #2:

                squash! target

                # This is the commit message #3:

                squash! target
                """
            )
            f.replace_dedent("two squashes")


def test_autosquash_squash_and_fixup() -> None:
    bash(
        """
        git commit --allow-empty -m 'initial commit'
        git commit --allow-empty -m 'fixup-target'
        git commit --allow-empty --fixup :/^fixup-target --no-edit
        git commit --allow-empty -m 'squash-target'
        git commit --allow-empty --squash :/^squash-target --no-edit
        """
    )

    with editor_main([":/^init", "--autosquash"], input=b"") as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent(
                """\
                # This is a combination of 2 commits.
                # This is the 1st commit message:

                squash-target

                # This is the commit message #2:

                squash! squash-target
                """
            )
            f.replace_dedent("squash + fixup")


def test_autosquash_multiple_squashes_with_fixup() -> None:
    bash(
        """
        git commit --allow-empty -m 'initial commit'
        git commit --allow-empty -m 'target'
        git commit --allow-empty --squash :/^target --no-edit
        git commit --allow-empty --fixup :/^target --no-edit
        git commit --allow-empty --squash :/^target --no-edit
        git commit --allow-empty -m 'unrelated'
        """
    )
    with editor_main([":/^init", "--autosquash"], input=b"") as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent(
                """\
                # This is a combination of 4 commits.
                # This is the 1st commit message:

                target

                # This is the commit message #2:

                squash! target

                # The commit message #3 will be skipped:

                # fixup! target

                # This is the commit message #4:

                squash! target
                """
            )
            f.replace_dedent("squashes + fixup")


def test_autosquash_multiple_independent_squashes() -> None:
    bash(
        """
        git commit --allow-empty -m 'initial commit'
        git commit --allow-empty -m 'target1'
        git commit --allow-empty -m 'target2'
        git commit --allow-empty --squash :/^target1 --no-edit
        git commit --allow-empty --squash :/^target2 --no-edit
        """
    )

    with editor_main([":/^init", "--autosquash"], input=b"") as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent("# This is a combination of 2 commits.")
            f.replace_dedent("squash 1")
        with ed.next_file() as f:
            assert f.startswith_dedent("# This is a combination of 2 commits.")
            f.replace_dedent("squash 2")
