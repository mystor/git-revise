# pylint: skip-file

import textwrap


def test_interactive_reorder(repo, bash, main, fake_editor):
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
        main(["-i", "HEAD~~"])

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
