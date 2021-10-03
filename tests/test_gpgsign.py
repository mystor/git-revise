# pylint: skip-file

from conftest import *
from subprocess import CalledProcessError, run


def test_gpgsign(repo, short_tmpdir, monkeypatch):
    bash("git commit --allow-empty -m 'commit 1'")
    assert repo.get_commit("HEAD").gpgsig is None

    # On MacOS, pytest's temp paths are too long for gpg-agent.
    # See https://github.com/pytest-dev/pytest/issues/5802
    gnupghome = short_tmpdir
    monkeypatch.setenv("GNUPGHOME", str(gnupghome))
    gnupghome.chmod(0o700)
    (gnupghome / "gpg.conf").write("pinentry-mode loopback")
    user_ident = repo.default_author.signing_key
    run(
        ["gpg", "--batch", "--passphrase", "", "--quick-gen-key", user_ident],
        check=True,
    )

    bash("git config commit.gpgSign true")
    main(["HEAD"])
    assert (
        repo.get_commit("HEAD").gpgsig is not None
    ), "git config commit.gpgSign activates GPG signing"

    bash("git config revise.gpgSign false")
    main(["HEAD"])
    assert (
        repo.get_commit("HEAD").gpgsig is None
    ), "git config revise.gpgSign overrides commit.gpgSign"

    main(["HEAD", "--gpg-sign"])
    assert (
        repo.get_commit("HEAD").gpgsig is not None
    ), "commandline option overrides configuration"

    main(["HEAD", "--no-gpg-sign"])
    assert repo.get_commit("HEAD").gpgsig is None, "long option"

    main(["HEAD", "-S"])
    assert repo.get_commit("HEAD").gpgsig is not None, "short option"

    bash("git config gpg.program false")
    try:
        main(["HEAD", "--gpg-sign"])
        assert False, "Overridden gpg.program should fail"
    except CalledProcessError:
        pass
    bash("git config --unset gpg.program")

    # Check that we can sign multiple commits.
    bash(
        """
        git -c commit.gpgSign=false commit --allow-empty -m 'commit 2'
        git -c commit.gpgSign=false commit --allow-empty -m 'commit 3'
        git -c commit.gpgSign=false commit --allow-empty -m 'commit 4'
    """
    )
    main(["HEAD~~", "--gpg-sign"])
    assert repo.get_commit("HEAD~~").gpgsig is not None
    assert repo.get_commit("HEAD~").gpgsig is not None
    assert repo.get_commit("HEAD").gpgsig is not None

    # Check that we can remove signatures from multiple commits.
    main(["HEAD~", "--no-gpg-sign"])
    assert repo.get_commit("HEAD~").gpgsig is None
    assert repo.get_commit("HEAD").gpgsig is None

    # Check that we add signatures, even if the target commit already has one.
    assert repo.get_commit("HEAD~~").gpgsig is not None
    main(["HEAD~~", "--gpg-sign"])
    assert repo.get_commit("HEAD~").gpgsig is not None
    assert repo.get_commit("HEAD").gpgsig is not None
