# pylint: skip-file

import textwrap


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


def interactive_autosquash_setup_repo(bash):
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


def interactive_helper_check_helper(extra_arg, repo, main, fake_editor, expected_msg):
    def editor(inq, outq):
        in_todo = inq.get()

        # Get the index tree to check it
        index = repo.index.commit()

        expected = textwrap.dedent(expected_msg).encode()
        assert in_todo.startswith(expected)

        outq.put(b"")

    with fake_editor(editor):
        main(["-i", extra_arg, "HEAD~~~"])


def interactive_helper_check_autosquash(extra_arg, repo, main, fake_editor):
    prev = repo.get_commit("HEAD")
    expected = f"""\
                pick {prev.parent().parent().oid.short()} commit two
                fixup {prev.oid.short()} fixup! commit two
                pick {prev.parent().oid.short()} commit three
                """
    interactive_helper_check_helper(extra_arg, repo, main, fake_editor, expected)


def interactive_helper_check_no_autosquash(extra_arg, repo, main, fake_editor):
    prev = repo.get_commit("HEAD")
    expected = f"""\
                pick {prev.parent().parent().oid.short()} commit two
                pick {prev.parent().oid.short()} commit three
                pick {prev.oid.short()} fixup! commit two
                """
    interactive_helper_check_helper(extra_arg, repo, main, fake_editor, expected)


def test_interactive_default_noautosquash_fixup(repo, bash, main, fake_editor):
    interactive_autosquash_setup_repo(bash)
    bash(
        """
        git config revise.autosquash 0
        git config rebase.autosquash 1
        """
    )
    interactive_helper_check_autosquash("--autosquash", repo, main, fake_editor)
    interactive_helper_check_no_autosquash("--no-autosquash", repo, main, fake_editor)
    interactive_helper_check_no_autosquash("", repo, main, fake_editor)


def test_interactive_default_autosquash_fixup(repo, bash, main, fake_editor):
    interactive_autosquash_setup_repo(bash)
    bash(
        """
        git config revise.autosquash 1
        git config rebase.autosquash 0
        """
    )
    interactive_helper_check_autosquash("--autosquash", repo, main, fake_editor)
    interactive_helper_check_no_autosquash("--no-autosquash", repo, main, fake_editor)
    interactive_helper_check_autosquash("", repo, main, fake_editor)


def test_interactive_default_fallback_autosquash_fixup(repo, bash, main, fake_editor):
    interactive_autosquash_setup_repo(bash)
    # if revise.autosquash is set globally, this test fails
    # - if set to false, the test fails
    # - if set to true, the test doesn't actually test the fallback mechanism
    bash(
        """
        git config rebase.autosquash 1
        """
    )
    interactive_helper_check_autosquash("--autosquash", repo, main, fake_editor)
    interactive_helper_check_no_autosquash("--no-autosquash", repo, main, fake_editor)
    interactive_helper_check_autosquash("", repo, main, fake_editor)


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
