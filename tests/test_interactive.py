# pylint: skip-file

import textwrap
import pytest


def interactive_reorder_helper(repo, bash, main, fake_editor, cwd):
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

    def editor(inq, outq):
        in_todo = inq.get()
        expected = textwrap.dedent(
            f"""\
            pick {prev.parent().oid.short()} commit two
            pick {prev.oid.short()} commit three
            """
        ).encode()
        assert in_todo.startswith(expected)

        outq.put(
            textwrap.dedent(
                f"""\
                pick {prev.oid.short()} commit three
                pick {prev.parent().oid.short()} commit two
                """
            ).encode()
        )

    with fake_editor(editor):
        main(["-i", "HEAD~~"], cwd=cwd)

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


def test_interactive_reorder(repo, bash, main, fake_editor):
    interactive_reorder_helper(repo, bash, main, fake_editor, cwd=repo.workdir)


def test_interactive_reorder_subdir(repo, bash, main, fake_editor):
    bash("mkdir subdir")
    interactive_reorder_helper(
        repo, bash, main, fake_editor, cwd=repo.workdir / "subdir"
    )


def test_interactive_fixup(repo, bash, main, fake_editor):
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

    def editor(inq, outq):
        in_todo = inq.get()

        # Get the index tree to check it
        index = repo.index.commit()

        expected = textwrap.dedent(
            f"""\
            pick {prev.parent().oid.short()} commit two
            pick {prev.oid.short()} commit three
            index {index.oid.short()} <git index>
            """
        ).encode()
        assert in_todo.startswith(expected)

        outq.put(
            textwrap.dedent(
                f"""\
                pick {prev.oid.short()} commit three
                fixup {index.oid.short()} <git index>
                pick {prev.parent().oid.short()} commit two
                """
            ).encode()
        )

    with fake_editor(editor):
        main(["-i", "HEAD~~"])

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
def test_autosquash_config(
    repo, bash, main, fake_editor, rebase_config, revise_config, expected
):
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

    disabled = textwrap.dedent(
        f"""\
        pick {headuu.oid.short()} commit two
        pick {headu.oid.short()} commit three
        pick {head.oid.short()} fixup! commit two

        """
    ).encode()
    enabled = textwrap.dedent(
        f"""\
        pick {headuu.oid.short()} commit two
        fixup {head.oid.short()} fixup! commit two
        pick {headu.oid.short()} commit three

        """
    ).encode()

    def subtest(args, expected_todos):
        def editor(inq, outq):
            in_todo = inq.get()
            assert in_todo.startswith(expected_todos)
            outq.put(disabled)  # ensure repo state is unchanged

        with fake_editor(editor):
            main(args + ["-i", "HEAD~3"])

        assert repo.get_commit("HEAD") == head

    subtest([], enabled if expected else disabled)
    subtest(["--autosquash"], enabled)
    subtest(["--no-autosquash"], disabled)


def test_interactive_reword(repo, bash, main, fake_editor):
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

    def editor(inq, outq):
        in_todo = inq.get()
        expected = textwrap.dedent(
            f"""\
            ++ pick {prev.parent().oid.short()}
            commit two

            extended2

            ++ pick {prev.oid.short()}
            commit three

            extended3
            """
        ).encode()
        assert in_todo.startswith(expected)

        outq.put(
            textwrap.dedent(
                f"""\
                ++ pick {prev.oid.short()}
                updated commit three

                extended3 updated

                ++ pick {prev.parent().oid.short()}
                updated commit two

                extended2 updated
                """
            ).encode()
        )

    with fake_editor(editor):
        main(["-ie", "HEAD~~"])

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
