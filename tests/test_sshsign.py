from pathlib import Path
from subprocess import CalledProcessError

from gitrevise.odb import Repository
from gitrevise.utils import sh_run

from .conftest import bash, main


def test_sshsign(
    repo: Repository,
    short_tmpdir: Path,
) -> None:
    def commit_has_ssh_signature(refspec: str) -> bool:
        commit = repo.get_commit(refspec)
        assert commit is not None
        assert commit.gpgsig is not None
        assert commit.gpgsig.startswith(b"-----BEGIN SSH SIGNATURE-----")
        return True

    bash("git commit --allow-empty -m 'commit 1'")
    assert repo.get_commit("HEAD").gpgsig is None

    short_tmpdir.chmod(0o700)
    private_key_path = short_tmpdir / "test_sshsign"
    # Writes to private_key_path and that plus .pub
    sh_run(["pwd"])
    sh_run(
        [
            "ssh-keygen",
            "-q",
            "-N",
            "",
            "-f",
            private_key_path.as_posix(),
            "-C",
            "git-revise: test_sshsign",
        ],
        check=True,
    )
    assert private_key_path.is_file(), "private ssh key file was successfully created"
    assert private_key_path.with_suffix(
        ".pub"
    ).is_file(), "public ssh key file was successfully created"

    bash("git config gpg.format ssh")
    bash("git config commit.gpgSign true")

    sh_run(
        ["git", "config", "user.signingKey", private_key_path.as_posix()],
        check=True,
    )
    main(["HEAD"])
    assert commit_has_ssh_signature("HEAD"), "can ssh sign given key as path"

    sh_run(["ssh-add", private_key_path.as_posix()], check=True)
    # todo: cleanup after with ssh-add -d PATH?
    sh_run(
        [
            "git",
            "config",
            "user.signingKey",
            private_key_path.with_suffix(".pub").read_text().strip(),
        ],
        check=True,
    )
    main(["HEAD"])
    assert commit_has_ssh_signature("HEAD"), "can ssh sign given literal pubkey"

    bash("git config gpg.ssh.program false")
    try:
        main(["HEAD", "--gpg-sign"])
        assert False, "Overridden gpg.ssh.program should fail"
    except CalledProcessError:
        pass
    bash("git config --unset gpg.ssh.program")

    # Check that we can sign multiple commits.
    bash(
        """
        git -c commit.gpgSign=false commit --allow-empty -m 'commit 2'
        git -c commit.gpgSign=false commit --allow-empty -m 'commit 3'
        git -c commit.gpgSign=false commit --allow-empty -m 'commit 4'
    """
    )
    main(["HEAD~~", "--gpg-sign"])
    assert commit_has_ssh_signature("HEAD~~")
    assert commit_has_ssh_signature("HEAD~")
    assert commit_has_ssh_signature("HEAD~")

    # Check that we can remove signatures from multiple commits.
    main(["HEAD~", "--no-gpg-sign"])
    assert repo.get_commit("HEAD~").gpgsig is None
    assert repo.get_commit("HEAD").gpgsig is None

    # Check that we add signatures, even if the target commit already has one.
    assert commit_has_ssh_signature("HEAD~~")
    main(["HEAD~~", "--gpg-sign"])
    assert commit_has_ssh_signature("HEAD~")
    assert commit_has_ssh_signature("HEAD")
