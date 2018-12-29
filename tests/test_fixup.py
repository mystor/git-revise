import zipfix
from zipfix import Commit

import zipfix
from zipfix import Commit


def fixup_helper(repo, bash, flags, target, message=None):
    old = repo.getcommit(target)
    assert old.persisted

    bash('''
        echo "extra line" >> file1
        git add file1
        ''')

    zipfix.main(flags + [target])

    new = repo.getcommit(target)
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
    repo.load_template('basic')
    fixup_helper(repo, bash, [], 'HEAD')


def test_fixup_nonhead(repo, bash):
    repo.load_template('basic')
    fixup_helper(repo, bash, [], 'HEAD~')

def test_fixup_head_msg(repo, bash):
    repo.load_template('basic')
    fixup_helper(
        repo,
        bash,
        ['-m', 'fixup_head test', '-m', 'another line'],
        'HEAD',
        'fixup_head test\n\nanother line\n')


def test_fixup_nonhead_msg(repo, bash):
    repo.load_template('basic')
    fixup_helper(
        repo,
        bash,
        ['-m', 'fixup_nonhead test', '-m', 'another line'],
        'HEAD~',
        'fixup_nonhead test\n\nanother line\n')


def test_fixup_head_editor(repo, bash, fake_editor):
    repo.load_template('basic')

    old = repo.getcommit('HEAD')
    with fake_editor(b'fixup_head_editor test\n\nanother line\n') as f:
        fixup_helper(
            repo,
            bash,
            ['-e'],
            'HEAD',
            'fixup_head_editor test\n\nanother line\n')
        assert f.read().startswith(old.message)


def test_fixup_nonhead_editor(repo, bash, fake_editor):
    repo.load_template('basic')

    old = repo.getcommit('HEAD~')
    with fake_editor(b'fixup_nonhead_editor test\n\nanother line\n') as f:
        fixup_helper(
            repo,
            bash,
            ['-e'],
            'HEAD~',
            'fixup_nonhead_editor test\n\nanother line\n')
        assert f.read().startswith(old.message)
