import zipfix
from zipfix import Commit


def test_reword_head(repo):
    repo.load_template('basic')

    old_head = repo.getcommit('HEAD')
    assert old_head.message != b'my new message\n'
    assert old_head.persisted

    zipfix.main(['--no-index', '-m', 'my new message', 'HEAD'])

    head = repo.getcommit('HEAD')
    assert head.message == b'my new message\n'
    assert head.persisted
    assert head.committer != repo.default_committer


def test_reword_head_editor(repo, fake_editor):
    repo.load_template('basic')

    old_head = repo.getcommit('HEAD')
    assert old_head.message != b'my new message\n'
    assert old_head.persisted

    with fake_editor(b'my new message\n') as f:
        zipfix.main(['--no-index', '-e', 'HEAD'])
        assert f.read().startswith(old_head.message)

    head = repo.getcommit('HEAD')
    assert head.message == b'my new message\n'
    assert head.persisted
    assert head.committer != repo.default_committer


def test_reword_root(repo, bash):
    bash(
        '''
        echo "hello, world" > file1
        git add file1
        git commit -m "initial commit"
        echo "new line!" >> file1
        git add file1
        git commit -m "another commit"
        ''')

    old = repo.getcommit('HEAD~')
    assert old.parents() == []
    assert old.message == b'initial commit\n'

    zipfix.main(['-m', 'my new message', 'HEAD~'])

    new = repo.getcommit('HEAD~')
    assert new.parents() == []
    assert new.message == b'my new message\n'
