import zipfix
from zipfix import Commit


def test_reword_head(repo_env):
    repo_env.init("basic")

    old_head = Commit.get('HEAD')
    assert old_head.message != b'my new message\n'
    assert old_head.persisted

    zipfix.main(['--no-index', '-m', 'my new message', 'HEAD'])

    head = Commit.get('HEAD')
    assert head.message == b'my new message\n'
    assert head.persisted
