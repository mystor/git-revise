# pylint: skip-file

import textwrap

from conftest import *
from gitrevise.merge import normalize_conflicted_file


def history_with_two_conflicting_commits():
    bash(
        """
        git config rerere.enabled true
        git config rerere.autoUpdate true
        echo > file; git add file; git commit -m 'initial commit'
        echo one > file; git commit -am 'commit one'
        echo two > file; git commit -am 'commit two'
        """
    )


def test_reuse_recorded_resolution(repo):
    history_with_two_conflicting_commits()

    with editor_main(("-i", "HEAD~~"), input=b"y\ny\ny\ny\n") as ed:
        flip_last_two_commits(repo, ed)
        with ed.next_file() as f:
            f.replace_dedent("resolved two\n")
        with ed.next_file() as f:
            f.replace_dedent("resolved one\n")

    tree_after_resolving_conflicts = repo.get_commit("HEAD").tree()
    bash("git reset --hard HEAD@{1}")

    # Now we can change the order of the two commits and reuse the recorded conflict resolution.
    with editor_main(("-i", "HEAD~~")) as ed:
        flip_last_two_commits(repo, ed)

    assert tree_after_resolving_conflicts == repo.get_commit("HEAD").tree()
    leftover_index = hunks(repo.git("diff", "-U0", "HEAD"))
    assert leftover_index == dedent(
        """\
        @@ -1 +1 @@
        -resolved one
        +two"""
    )

    # When we fail to read conflict data from the cache, we fall back to
    # letting the user resolve the conflict.
    bash("git reset --hard HEAD@{1}")
    bash("rm .git/rr-cache/*/preimage")
    with editor_main(("-i", "HEAD~~"), input=b"y\ny\ny\ny\n") as ed:
        flip_last_two_commits(repo, ed)
        with ed.next_file() as f:
            f.replace_dedent("resolved two\n")
        with ed.next_file() as f:
            f.replace_dedent("resolved one\n")


def test_rerere_merge(repo):
    the_file = repo.workdir / "file"
    the_file.write_bytes(10 * b"x\n")
    bash(
        """
        git config rerere.enabled true
        git config rerere.autoUpdate true
        git add file; git commit -m 'initial commit'
        """
    )
    the_file.write_bytes(b"original1\n" + 9 * b"x\n")
    repo.git("commit", "-am", "commit1")
    the_file.write_bytes(b"original2\n" + 9 * b"x\n")
    repo.git("commit", "-am", "commit2")

    # Record a resolution for changing the order of two commits.
    with editor_main(("-i", "HEAD~~"), input=b"y\ny\ny\ny\n") as ed:
        flip_last_two_commits(repo, ed)
        with ed.next_file() as f:
            f.replace_dedent(b"resolved1\n" + 9 * b"x\n")
        with ed.next_file() as f:
            f.replace_dedent(b"resolved2\n" + 9 * b"x\n")
    # Go back to the old history so we can try replaying the resolution.
    bash("git reset --hard HEAD@{1}")

    # Introduce an unrelated change that will not conflict to check that we can
    # merge the file contents, and not just use the recorded postimage as is.
    the_file.write_bytes(
        b"original2\n" + 8 * b"x\n" + b"unrelated change, present in all commits\n"
    )
    repo.git("add", "file")
    main(["HEAD~2"])

    with editor_main(("-i", "HEAD~~")) as ed:
        flip_last_two_commits(repo, ed)

    assert hunks(repo.git("show", "-U0", "HEAD~")) == dedent(
        """\
            @@ -1 +1 @@
            -x
            +resolved1"""
    )
    assert hunks(repo.git("show", "-U0", "HEAD")) == dedent(
        """\
            @@ -1 +1 @@
            -resolved1
            +resolved2"""
    )
    leftover_index = hunks(repo.git("diff", "-U0", "HEAD"))
    assert leftover_index == dedent(
        """\
        @@ -1 +1 @@
        -resolved2
        +original2"""
    )


def test_replay_resolution_recorded_by_git(repo):
    history_with_two_conflicting_commits()
    # Switch the order of the last two commits, recording the conflict
    # resolution with Git itself.
    bash(
        r"""
        one=$(git rev-parse HEAD~)
        two=$(git rev-parse HEAD)
        git reset --hard HEAD~~
        git cherry-pick "$two" 2>&1 | grep 'could not apply'
        echo resolved two > file; git add file; GIT_EDITOR=: git cherry-pick --continue
        git cherry-pick "$one" 2>&1 | grep 'could not apply'
        echo resolved one > file; git add file; GIT_EDITOR=: git cherry-pick --continue --no-edit
        git reset --hard "$two"
        """
    )

    # Now let's try to do the same thing with git-revise, reusing the recorded resolution.
    with editor_main(("-i", "HEAD~~")) as ed:
        flip_last_two_commits(repo, ed)

    assert repo.git("log", "-p", trim_newline=False) == dedent(
        """\
        commit dc50430ecbd2d0697ee9266ba6057e0e0b511d7f
        Author: Bash Author <bash_author@example.com>
        Date:   Thu Jul 13 21:40:00 2017 -0500

            commit one

        diff --git a/file b/file
        index 474b904..936bcfd 100644
        --- a/file
        +++ b/file
        @@ -1 +1 @@
        -resolved two
        +resolved one

        commit e51ab202e87f0557df78e5273dcedf51f408a468
        Author: Bash Author <bash_author@example.com>
        Date:   Thu Jul 13 21:40:00 2017 -0500

            commit two

        diff --git a/file b/file
        index 8b13789..474b904 100644
        --- a/file
        +++ b/file
        @@ -1 +1 @@
        -
        +resolved two

        commit d72132e74176624d6c3e5b6b4f5ef774ff23a1b3
        Author: Bash Author <bash_author@example.com>
        Date:   Thu Jul 13 21:40:00 2017 -0500

            initial commit

        diff --git a/file b/file
        new file mode 100644
        index 0000000..8b13789
        --- /dev/null
        +++ b/file
        @@ -0,0 +1 @@
        +
        """
    )


def test_normalize_conflicted_file():
    # Normalize conflict markers and labels.
    assert normalize_conflicted_file(
        dedent(
            """\
            <<<<<<< HEAD
            a
            =======
            b
            >>>>>>> original thingamabob

            unrelated line

            <<<<<<<<<< HEAD
            c
            ==========
            d
            >>>>>>>>>> longer conflict marker, to be trimmed
            """
        )
    ) == (
        dedent(
            """\
            <<<<<<<
            a
            =======
            b
            >>>>>>>

            unrelated line

            <<<<<<<
            c
            =======
            d
            >>>>>>>
            """
        ),
        "3d7cdc2948951408412cc64f3816558407f77e18",
    )

    # Discard original-text-marker from merge.conflictStyle diff3.
    assert (
        normalize_conflicted_file(
            dedent(
                """\
            <<<<<<< theirs
            a
            ||||||| common origin
            b
            =======
            c
            >>>>>>> ours
            """
            )
        )[0]
        == dedent(
            """\
            <<<<<<<
            a
            =======
            c
            >>>>>>>
            """
        )
    )

    # The two sides of the conflict are ordered.
    assert (
        normalize_conflicted_file(
            dedent(
                """\
                <<<<<<< this way round
                b
                =======
                a
                >>>>>>> (unsorted)
                """
            )
        )[0]
        == dedent(
            """\
            <<<<<<<
            a
            =======
            b
            >>>>>>>
            """
        )
    )

    # Nested conflict markers.
    assert (
        normalize_conflicted_file(
            dedent(
                """\
            <<<<<<<
            outer left
            <<<<<<<<<<<
            inner left
            |||||||||||
            inner diff3 original section
            ===========
            inner right
            >>>>>>>>>>>
            =======
            outer right
            >>>>>>>
            """
            )
        )[0]
        == dedent(
            """\
            <<<<<<<
            outer left
            <<<<<<<
            inner left
            =======
            inner right
            >>>>>>>
            =======
            outer right
            >>>>>>>
            """
        )
    )


def flip_last_two_commits(repo: Repository, ed: Editor):
    head = repo.get_commit("HEAD")
    with ed.next_file() as f:
        lines = f.indata.splitlines()
        assert lines[0].startswith(b"pick " + head.parent().oid.short().encode())
        assert lines[1].startswith(b"pick " + head.oid.short().encode())
        assert not lines[2], "expect todo list with exactly two items"

        f.replace_dedent(
            f"""\
            pick {head.oid.short()}
            pick {head.parent().oid.short()}
            """
        )


def dedent(text: str) -> bytes:
    return textwrap.dedent(text).encode()


def hunks(diff: bytes) -> bytes:
    return diff[diff.index(b"@@") :]
