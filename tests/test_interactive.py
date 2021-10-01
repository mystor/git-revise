# pylint: disable=redefined-outer-name
# pylint: disable=wildcard-import
# pylint: disable=unused-wildcard-import
# pylint: disable=not-context-manager

import pytest
from conftest import *


def interactive_reorder_helper(repo, cwd):
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
        """
    )

    prev = repo.get_commit("HEAD")
    prev_u = prev.parent()
    prev_uu = prev_u.parent()

    with editor_main(["-i", "HEAD~~"], cwd=cwd) as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent(
                f"""\
                pick {prev.parent().oid.short()} commit two
                pick {prev.oid.short()} commit three
                """
            )
            f.replace_dedent(
                f"""\
                pick {prev.oid.short()} commit three
                pick {prev.parent().oid.short()} commit two
                """
            )

    curr = repo.get_commit("HEAD")
    curr_u = curr.parent()
    curr_uu = curr_u.parent()

    assert curr != prev
    assert curr.tree() == prev.tree()
    assert curr_u.message == prev.message
    assert curr.message == prev_u.message
    assert curr_uu == prev_uu

    assert b"file2" in prev_u.tree().entries
    assert b"file2" not in curr_u.tree().entries

    assert prev_u.tree().entries[b"file2"] == curr.tree().entries[b"file2"]
    assert prev_u.tree().entries[b"file1"] == curr_uu.tree().entries[b"file1"]
    assert prev.tree().entries[b"file1"] == curr_u.tree().entries[b"file1"]


def test_interactive_reorder(repo):
    interactive_reorder_helper(repo, cwd=repo.workdir)


def test_interactive_reorder_subdir(repo):
    bash("mkdir subdir")
    interactive_reorder_helper(repo, cwd=repo.workdir / "subdir")


def test_interactive_on_root(repo):
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
        """
    )

    orig_commit3 = prev = repo.get_commit("HEAD")
    orig_commit2 = prev_u = prev.parent()
    orig_commit1 = prev_u.parent()

    index_tree = repo.index.tree()

    with editor_main(["-i", "--root"]) as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent(
                f"""\
                pick {prev.parent().parent().oid.short()} commit one
                pick {prev.parent().oid.short()} commit two
                pick {prev.oid.short()} commit three
                """
            )
            f.replace_dedent(
                f"""\
                pick {prev.parent().oid.short()} commit two
                pick {prev.parent().parent().oid.short()} commit one
                pick {prev.oid.short()} commit three
                """
            )

    new_commit3 = curr = repo.get_commit("HEAD")
    new_commit1 = curr_u = curr.parent()
    new_commit2 = curr_u.parent()

    assert curr != prev
    assert curr.tree() == index_tree
    assert new_commit1.message == orig_commit1.message
    assert new_commit2.message == orig_commit2.message
    assert new_commit3.message == orig_commit3.message

    assert new_commit2.is_root
    assert new_commit1.parent() == new_commit2
    assert new_commit3.parent() == new_commit1

    assert new_commit1.tree().entries[b"file1"] == orig_commit1.tree().entries[b"file1"]
    assert new_commit2.tree().entries[b"file2"] == orig_commit2.tree().entries[b"file2"]
    assert new_commit3.tree() == orig_commit3.tree()


def test_interactive_fixup(repo):
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

        echo "extra" >> file3
        git add file3
        """
    )

    prev = repo.get_commit("HEAD")
    prev_u = prev.parent()
    prev_uu = prev_u.parent()

    index_tree = repo.index.tree()

    with editor_main(["-i", "HEAD~~"]) as ed:
        with ed.next_file() as f:
            index = repo.index.commit()

            assert f.startswith_dedent(
                f"""\
                pick {prev.parent().oid.short()} commit two
                pick {prev.oid.short()} commit three
                index {index.oid.short()} <git index>
                """
            )
            f.replace_dedent(
                f"""\
                pick {prev.oid.short()} commit three
                fixup {index.oid.short()} <git index>
                pick {prev.parent().oid.short()} commit two
                """
            )

    curr = repo.get_commit("HEAD")
    curr_u = curr.parent()
    curr_uu = curr_u.parent()

    assert curr != prev
    assert curr.tree() == index_tree
    assert curr_u.message == prev.message
    assert curr.message == prev_u.message
    assert curr_uu == prev_uu

    assert b"file2" in prev_u.tree().entries
    assert b"file2" not in curr_u.tree().entries

    assert b"file3" not in prev.tree().entries
    assert b"file3" not in prev_u.tree().entries
    assert b"file3" not in prev_uu.tree().entries

    assert b"file3" in curr.tree().entries
    assert b"file3" in curr_u.tree().entries
    assert b"file3" not in curr_uu.tree().entries

    assert curr.tree().entries[b"file3"].blob().body == b"extra\n"
    assert curr_u.tree().entries[b"file3"].blob().body == b"extra\n"

    assert prev_u.tree().entries[b"file2"] == curr.tree().entries[b"file2"]
    assert prev_u.tree().entries[b"file1"] == curr_uu.tree().entries[b"file1"]
    assert prev.tree().entries[b"file1"] == curr_u.tree().entries[b"file1"]


@pytest.mark.parametrize(
    "rebase_config,revise_config,expected",
    [
        (None, None, False),
        ("1", "0", False),
        ("0", "1", True),
        ("1", None, True),
        (None, "1", True),
    ],
)
def test_autosquash_config(repo, rebase_config, revise_config, expected):
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

    if rebase_config is not None:
        bash(f"git config rebase.autoSquash '{rebase_config}'")
    if revise_config is not None:
        bash(f"git config revise.autoSquash '{revise_config}'")

    head = repo.get_commit("HEAD")
    headu = head.parent()
    headuu = headu.parent()

    disabled = f"""\
        pick {headuu.oid.short()} commit two
        pick {headu.oid.short()} commit three
        pick {head.oid.short()} fixup! commit two

        """
    enabled = f"""\
        pick {headuu.oid.short()} commit two
        fixup {head.oid.short()} fixup! commit two
        pick {headu.oid.short()} commit three

        """

    def subtest(args, expected_todos):
        with editor_main(args + ["-i", "HEAD~3"]) as ed:
            with ed.next_file() as f:
                assert f.startswith_dedent(expected_todos)
                f.replace_dedent(disabled)  # don't mutate state

        assert repo.get_commit("HEAD") == head

    subtest([], enabled if expected else disabled)
    subtest(["--autosquash"], enabled)
    subtest(["--no-autosquash"], disabled)


def test_interactive_reword(repo):
    bash(
        """
        echo "hello, world" > file1
        git add file1
        git commit -m "commit one" -m "extended1"

        echo "second file" > file2
        git add file2
        git commit -m "commit two" -m "extended2"

        echo "new line!" >> file1
        git add file1
        git commit -m "commit three" -m "extended3"
        """
    )

    prev = repo.get_commit("HEAD")
    prev_u = prev.parent()
    prev_uu = prev_u.parent()

    with editor_main(["-ie", "HEAD~~"]) as ed:
        with ed.next_file() as f:
            assert f.startswith_dedent(
                f"""\
                ++ pick {prev.parent().oid.short()}
                commit two

                extended2

                ++ pick {prev.oid.short()}
                commit three

                extended3
                """
            )
            f.replace_dedent(
                f"""\
                ++ pick {prev.oid.short()}
                updated commit three

                extended3 updated

                ++ pick {prev.parent().oid.short()}
                updated commit two

                extended2 updated
                """
            )

    curr = repo.get_commit("HEAD")
    curr_u = curr.parent()
    curr_uu = curr_u.parent()

    assert curr != prev
    assert curr.tree() == prev.tree()
    assert curr_u.message == b"updated commit three\n\nextended3 updated\n"
    assert curr.message == b"updated commit two\n\nextended2 updated\n"
    assert curr_uu == prev_uu

    assert b"file2" in prev_u.tree().entries
    assert b"file2" not in curr_u.tree().entries

    assert prev_u.tree().entries[b"file2"] == curr.tree().entries[b"file2"]
    assert prev_u.tree().entries[b"file1"] == curr_uu.tree().entries[b"file1"]
    assert prev.tree().entries[b"file1"] == curr_u.tree().entries[b"file1"]
