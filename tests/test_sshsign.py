import re
from pathlib import Path
from subprocess import CalledProcessError
from typing import Generator

import pytest

from gitrevise.odb import Repository
from gitrevise.utils import sh_run

from .conftest import bash, main


@pytest.fixture(scope="function", name="ssh_private_key_path")
def fixture_ssh_private_key_path(
    short_tmpdir: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """
    Creates an SSH key and registers it with ssh-agent. De-registers it during cleanup.
    Yields the Path to the private key file. The corresponding public key file is that path
    with suffix ".pub".
    """
    short_tmpdir.chmod(0o700)
    private_key_path = short_tmpdir / "test_sshsign"
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

    assert private_key_path.is_file()
    pub_key_path = private_key_path.with_suffix(".pub")
    assert pub_key_path.is_file()

    # Start the SSH agent and register a private key to it.
    socket_path = short_tmpdir / "ssh-agent.sock"
    output = sh_run(
        ["ssh-agent", "-a", socket_path.as_posix(), "-s"],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(
        r"SSH_AGENT_PID=(?P<pid>\d+)",
        output.stdout,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "Failed to parse SSH_AGENT_PID from ssh-agent output"
    monkeypatch.setenv("SSH_AUTH_SOCK", socket_path.as_posix())
    monkeypatch.setenv("SSH_AGENT_PID", match.group("pid"))

    sh_run(["ssh-add", private_key_path.as_posix()], check=True)
    yield private_key_path
    sh_run(["ssh-add", "-d", private_key_path.as_posix()], check=True)

    sh_run(["ssh-agent", "-k"], check=True)


def test_sshsign(
    repo: Repository,
    ssh_private_key_path: Path,
) -> None:
    def commit_has_ssh_signature(refspec: str) -> bool:
        commit = repo.get_commit(refspec)
        assert commit is not None
        assert commit.gpgsig is not None
        assert commit.gpgsig.startswith(b"-----BEGIN SSH SIGNATURE-----")
        return True

    bash("git commit --allow-empty -m 'commit 1'")
    assert repo.get_commit("HEAD").gpgsig is None

    bash("git config gpg.format ssh")
    bash("git config commit.gpgSign true")

    sh_run(
        ["git", "config", "user.signingKey", ssh_private_key_path.as_posix()],
        check=True,
    )
    main(["HEAD"])
    assert commit_has_ssh_signature("HEAD"), "can ssh sign given key as path"

    pubkey = ssh_private_key_path.with_suffix(".pub").read_text().strip()
    sh_run(
        [
            "git",
            "config",
            "user.signingKey",
            pubkey,
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
