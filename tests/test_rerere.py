from textwrap import dedent
from typing import Optional, Tuple

import pytest

from gitrevise.merge import normalize_conflicted_file
from gitrevise.odb import Repository

from .conftest import Editor, bash, changeline, editor_main, main


def history_with_two_conflicting_commits(auto_update: bool = False) -> None:
    bash(
        f"""
        git config rerere.enabled true
        git config rerere.autoUpdate {"true" if auto_update else "false"}
        echo > file; git add file; git commit -m 'initial commit'
        echo eggs > file; git commit -am 'add eggs'
        echo eggs spam > file; git commit -am 'add spam'
        """
    )


@pytest.mark.parametrize(
    "auto_update,custom_resolution",
    [
        (True, None),
        (False, None),
        (False, "only spam"),
    ],
)
def test_reuse_recorded_resolution(
    repo: Repository,
    auto_update: bool,
    custom_resolution: Optional[str],
) -> None:
    history_with_two_conflicting_commits(auto_update=auto_update)

    # Uncached case: Record the user's resolution (in .git/rr-cache/*/preimage).
    with editor_main(("-i", "HEAD~~"), input=b"y\n" * 4) as ed:
        flip_last_two_commits(repo, ed)
        with ed.next_file() as f:
            f.replace_dedent("spam\n")
        with ed.next_file() as f:
            f.replace_dedent("eggs spam\n")

    tree_after_resolving_conflicts = repo.get_commit("HEAD").tree()
    bash("git reset --hard HEAD@{1}")

    # Cached case: Test auto-using, accepting or declining the recorded resolution.
    acceptance_input = None
    intermediate_state = "spam"
    if not auto_update:
        acceptance_input = b"y\n" * 2
        if custom_resolution is not None:
            acceptance_input = b"n\n" + b"y\n" * 4
            intermediate_state = custom_resolution

    with editor_main(("-i", "HEAD~~"), input=acceptance_input) as ed:
        flip_last_two_commits(repo, ed)
        if custom_resolution is not None:
            with ed.next_file() as f:
                f.replace_dedent(custom_resolution + "\n")
            with ed.next_file() as f:
                f.replace_dedent("eggs spam\n")

    assert tree_after_resolving_conflicts == repo.get_commit("HEAD").tree()

    assert hunks(repo.git("show", "-U0", "HEAD~")) == dedent(
        f"""\
            @@ -1 +1 @@
            -
            +{intermediate_state}"""
    )
    assert hunks(repo.git("show", "-U0", "HEAD")) == dedent(
        f"""\
            @@ -1 +1 @@
            -{intermediate_state}
            +eggs spam"""
    )
    assert uncommitted_changes(repo) == ""


def test_rerere_merge(repo: Repository) -> None:
    (repo.workdir / "file").write_bytes(10 * b"x\n")
    bash(
        """
        git config rerere.enabled true
        git config rerere.autoUpdate true
        git add file; git commit -m 'initial commit'
        """
    )
    changeline("file", 0, b"original1\n")
    bash("git commit -am 'commit 1'")
    changeline("file", 0, b"original2\n")
    bash("git commit -am 'commit 2'")

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
    changeline("file", 9, b"unrelated change, present in all commits\n")
    bash("git add file")
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


def test_replay_resolution_recorded_by_git(repo: Repository) -> None:
    history_with_two_conflicting_commits(auto_update=True)
    # Switch the order of the last two commits, recording the conflict
    # resolution with Git itself.
    bash(
        r"""
        one=$(git rev-parse HEAD~)
        two=$(git rev-parse HEAD)
        git reset --hard HEAD~~
        git cherry-pick "$two" 2>&1 | grep 'could not apply'
        echo intermediate state > file
        git add file; GIT_EDITOR=: git cherry-pick --continue
        git cherry-pick "$one" 2>&1 | grep 'could not apply'
        echo something completely different > file
        git add file; GIT_EDITOR=: git cherry-pick --continue --no-edit
        git reset --hard "$two"
        """
    )

    # Now let's try to do the same thing with git-revise, reusing the recorded resolution.
    with editor_main(("-i", "HEAD~~")) as ed:
        flip_last_two_commits(repo, ed)

    assert repo.git("log", "-p", trim_newline=False).decode() == dedent(
        """\
        commit 44fdce0cf7ae75ed5edac5f3defed83cddf3ec4a
        Author: Bash Author <bash_author@example.com>
        Date:   Thu Jul 13 21:40:00 2017 -0500

            add eggs

        diff --git a/file b/file
        index 5d0f8a8..cb90548 100644
        --- a/file
        +++ b/file
        @@ -1 +1 @@
        -intermediate state
        +something completely different

        commit 1fa5135a6cce1f63dc2f5584ee68e15a4de3a99c
        Author: Bash Author <bash_author@example.com>
        Date:   Thu Jul 13 21:40:00 2017 -0500

            add spam

        diff --git a/file b/file
        index 8b13789..5d0f8a8 100644
        --- a/file
        +++ b/file
        @@ -1 +1 @@
        -
        +intermediate state

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


def test_normalize_conflicted_file() -> None:
    # Normalize conflict markers and labels.
    assert (
        normalize_conflict_dedent(
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
            >>>>>>>>>> longer conflict marker, to be ignored
            """
        )
        == (
            dedent(
                """\
                <<<<<<<
                a
                =======
                b
                >>>>>>>

                unrelated line

                <<<<<<<<<< HEAD
                c
                ==========
                d
                >>>>>>>>>> longer conflict marker, to be ignored
                """
            ),
            "0630df854874fc5ffb92a197732cce0d8928e898",
        )
    )

    # Discard original-text-marker from merge.conflictStyle diff3.
    assert (
        normalize_conflict_dedent(
            """\
            <<<<<<< theirs
            a
            ||||||| common origin
            b
            =======
            c
            >>>>>>> ours
            """
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
        normalize_conflict_dedent(
            """\
            <<<<<<< this way round
            b
            =======
            a
            >>>>>>> (unsorted)
            """
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
        normalize_conflict_dedent(
            """\
            <<<<<<< ours (outer)
            outer left
            <<<<<<< ours (inner)
            inner left
            |||||||
            inner diff3 original section
            =======
            inner right
            >>>>>>> theirs (inner)
            =======
            outer right
            >>>>>>> theirs (outer)
            """
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


def flip_last_two_commits(repo: Repository, ed: Editor) -> None:
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


def normalize_conflict_dedent(indented_conflict: str) -> Tuple[str, str]:
    intended_conflict = dedent(indented_conflict).encode()
    normalized, hexdigest = normalize_conflicted_file(intended_conflict)
    return (normalized.decode(), hexdigest)


def hunks(diff: bytes) -> str:
    return diff[diff.index(b"@@") :].decode()


def uncommitted_changes(repo: Repository) -> str:
    return repo.git("diff", "-U0", "HEAD").decode()
