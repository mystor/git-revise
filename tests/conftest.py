import pytest
import shutil
import os
from pathlib import Path
from zipfix import GitObj, Signature
from contextlib import contextmanager

@pytest.fixture(scope="session")
def res_path():
    """Location where test resources are stored on-disk"""
    return Path(__file__).parent / 'resources'


@pytest.fixture
def repo_env(tmp_path, res_path, monkeypatch):
    """Create a temporary git repository environment"""

    # Override which committer and author are used.
    user = Signature(b'Test Committer', b'committer@example.com',
                     b'1500000000', b'-0500')
    monkeypatch.setattr(Signature, 'default_author', lambda: user)
    monkeypatch.setattr(Signature, 'default_committer', lambda: user)

    class RepoEnv:
        workdir = tmp_path / 'repo'
        gitdir = workdir / '.git'

        @staticmethod
        @contextmanager
        def no_cache():
            with monkeypatch.context() as ctx:
                ctx.setattr(GitObj, 'o_cache', {})
                yield

        @classmethod
        def init(cls, name):
            """Copy a git repo from the resources directory, and chdir into it"""
            # Initalize the repository from template, renaming '_git' to '.git'
            shutil.copytree(res_path / name, cls.workdir)
            (cls.workdir / '_git').rename(cls.gitdir)

            # Switch context into the new repo, and out caches
            monkeypatch.chdir(cls.workdir)
            monkeypatch.setattr(GitObj, 'o_cache', {})
            monkeypatch.setattr(GitObj, 'catfile', None)

    return RepoEnv
