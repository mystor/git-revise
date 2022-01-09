# pylint: skip-file

import pytest
import shlex
import os
import sys
import tempfile
import textwrap
import subprocess
import traceback
from pathlib import Path
from gitrevise.odb import Repository
from gitrevise.utils import sh_path
from contextlib import contextmanager
from threading import Thread, Event
from http.server import HTTPServer, BaseHTTPRequestHandler
import dummy_editor


@pytest.fixture(autouse=True)
def hermetic_seal(tmp_path_factory, monkeypatch):
    # Lock down user git configuration
    home = tmp_path_factory.mktemp("home")
    xdg_config_home = home / ".config"
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "true")

    # Lock down commit/authoring time
    monkeypatch.setenv("GIT_AUTHOR_DATE", "1500000000 -0500")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "1500000000 -0500")

    # Install known configuration
    gitconfig = home / ".gitconfig"
    gitconfig.write_bytes(
        textwrap.dedent(
            """\
            [core]
                eol = lf
                autocrlf = input
            [user]
                email = test@example.com
                name = Test User
            """
        ).encode()
    )

    # If we are not expecting an editor to be launched, abort immediately.
    # (The `false` command always exits with failure).
    # This is overridden in editor_main.
    monkeypatch.setenv("GIT_EDITOR", "false")

    # Switch into a test workdir, and init our repo
    workdir = tmp_path_factory.mktemp("workdir")
    monkeypatch.chdir(workdir)
    bash("git init -q")


@pytest.fixture
def repo(hermetic_seal):
    with Repository() as repo:
        yield repo


@pytest.fixture
def short_tmpdir():
    with tempfile.TemporaryDirectory() as tdir:
        yield Path(tdir)


@contextmanager
def in_parallel(func, *args, **kwargs):
    class HelperThread(Thread):
        exception = None

        def run(self):
            try:
                func(*args, **kwargs)
            except Exception as exc:
                traceback.print_exc()
                self.exception = exc
                raise

    thread = HelperThread()
    thread.start()
    try:
        yield
    finally:
        thread.join()
    if thread.exception:
        raise thread.exception


def bash(command):
    # Use a custom environment for bash commands so commits with those commands
    # have unique names and emails.
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="Bash Author",
        GIT_AUTHOR_EMAIL="bash_author@example.com",
        GIT_COMMITTER_NAME="Bash Committer",
        GIT_COMMITTER_EMAIL="bash_committer@example.com",
    )
    subprocess.run([sh_path(), "-ec", textwrap.dedent(command)], check=True, env=env)


def changeline(path, lineno, newline):
    with open(path, "rb") as f:
        lines = f.readlines()
    lines[lineno] = newline
    with open(path, "wb") as f:
        f.write(b"".join(lines))


# Run the main entry point for git-revise in a subprocess.
def main(args, **kwargs):
    kwargs.setdefault("check", True)
    cmd = [sys.executable, "-m", "gitrevise", *args]
    print("Running", cmd, kwargs)
    return subprocess.run(cmd, **kwargs)


@contextmanager
def editor_main(args, **kwargs):
    with pytest.MonkeyPatch().context() as m, Editor() as ed:
        editor_cmd = " ".join(
            shlex.quote(p)
            for p in (
                sys.executable,
                dummy_editor.__file__,
                "http://{0}:{1}/".format(*ed.server_address[:2]),
            )
        )
        m.setenv("GIT_EDITOR", editor_cmd)

        def main_wrapper():
            try:
                return main(args, **kwargs)
            except Exception as e:
                ed.exception = e
            finally:
                if not ed.exception:
                    ed.exception = Exception(
                        "git-revise exited without invoking editor"
                    )
                ed.request_ready.set()

        with in_parallel(main_wrapper):
            yield ed


class EditorFile(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.response_ready = Event()
        self.indata = None
        self.outdata = None
        self.exception = None
        super().__init__(*args, **kwargs)

    def do_POST(self):
        length = int(self.headers.get("content-length"))
        self.indata = self.rfile.read(length)
        self.outdata = b""

        # The request is ready, tell our server, and wait for a reply.
        assert self.server.current is None
        self.server.current = self
        try:
            self.server.request_ready.set()
            if not self.response_ready.wait(timeout=self.server.timeout):
                raise Exception("timed out waiting for reply")
        finally:
            self.server.current = None

    def send_editor_reply(self, status, data):
        assert not self.response_ready.is_set(), "already replied?"
        self.send_response(status)
        self.send_header("content-length", len(data))
        self.end_headers()
        self.wfile.write(data)
        self.response_ready.set()

        # Ensure the handle thread has shut down
        self.server.handle_thread.join()
        self.server.handle_thread = None
        assert self.server.current is None

    def startswith(self, text):
        return self.indata.startswith(text)

    def startswith_dedent(self, text):
        return self.startswith(textwrap.dedent(text).encode())

    def equals(self, text):
        return self.indata == text

    def equals_dedent(self, text):
        return self.equals(textwrap.dedent(text).encode())

    def replace_dedent(self, text):
        if isinstance(text, str):
            text = textwrap.dedent(text).encode()
        self.outdata = text

    def __enter__(self):
        return self

    def __exit__(self, etype, evalue, tb):
        if etype is None:
            self.send_editor_reply(200, self.outdata)
        else:
            exc = "".join(traceback.format_exception(etype, evalue, tb)).encode()
            try:
                self.send_editor_reply(500, exc)
            except:
                pass

    def __repr__(self):
        return f"<EditorFile {self.indata!r}>"


class Editor(HTTPServer):
    def __init__(self):
        # Bind to a randomly-allocated free port.
        super().__init__(("127.0.0.1", 0), EditorFile)
        self.request_ready = Event()
        self.handle_thread = None
        self.current = None
        self.exception = None
        self.timeout = 10

    def next_file(self):
        assert self.handle_thread is None
        assert self.current is None

        # Spawn a thread to handle the single request.
        self.request_ready.clear()
        self.handle_thread = Thread(target=self.handle_request)
        self.handle_thread.start()
        if not self.request_ready.wait(timeout=self.timeout):
            raise Exception("timeout while waiting for request")

        if self.exception:
            raise self.exception

        # Return the request we received and were notified about.
        assert self.current
        return self.current

    def is_idle(self):
        return self.handle_thread is None and self.current is None

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        try:
            # Only assert if we're not already raising an exception.
            if etype is None:
                assert self.is_idle()
        finally:
            self.server_close()
            if self.current:
                self.current.send_editor_reply(500, b"editor server was shut down")
