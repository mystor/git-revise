import pytest
import shutil
import os
import sys
import textwrap
import subprocess
from pathlib import Path
from zipfix import Repository
from contextlib import contextmanager


RESOURCES = Path(__file__).parent / "resources"


@pytest.fixture(scope="session")
def bash():
    def run_bash(command, check=True, cwd=None):
        subprocess.run(["bash", "-ec", textwrap.dedent(command)], check=check, cwd=cwd)

    return run_bash


def _docopytree(source, dest, renamer=lambda x: x):
    for dirpath, _, filenames in os.walk(source):
        srcdir = Path(dirpath)
        reldir = srcdir.relative_to(source)

        for name in filenames:
            srcf = srcdir / name
            destf = dest / renamer(reldir / name)
            destf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(srcf, destf)


class TestRepo(Repository):
    """repository object with extra helper methods for writing tests"""

    def load_template(self, name):
        def renamer(path):
            # If a segment named _git is present, replace it with .git.
            return Path(*[".git" if p == "_git" else p for p in path.parts])

        _docopytree(RESOURCES / name, self.workdir, renamer=renamer)


@pytest.fixture
def repo(tmp_path_factory, monkeypatch, bash):
    # Create a working directory, change into it, and run 'git init -q' to
    # create a git repo there.
    workdir = tmp_path_factory.mktemp("repo")
    monkeypatch.chdir(workdir)
    bash("git init -q", cwd=workdir)
    return TestRepo()


@pytest.fixture
def fake_editor(tmp_path_factory, monkeypatch):
    @contextmanager
    def fake_editor(text):
        tmpdir = tmp_path_factory.mktemp("editor")
        out = tmpdir / "out"
        flag = tmpdir / "flag"

        # Build the script to be run as "editor"
        script = tmpdir / "fake_editor"
        with open(script, "w") as scriptf:
            scriptf.write(
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import sys
                    with open(sys.argv[1], 'rb+') as f:
                        # Stash old value
                        with open({repr(str(out))}, 'wb') as oldf:
                            oldf.write(f.read())

                        # Replace file contents
                        f.seek(0)
                        f.truncate()
                        f.write({repr(text)})

                        # Create a file with the given name
                        open({repr(str(flag))}, 'wb').close()
                    """
                )
            )
        script.chmod(0o755)

        with monkeypatch.context() as cx, open(out, "wb+") as outf:
            cx.setenv("EDITOR", str(script))
            assert not flag.exists(), "Editor shouldn't have been run yet"
            yield outf
            assert flag.exists(), "Editor should have been run"

    return fake_editor
