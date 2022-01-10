# pylint: skip-file

import pytest
import shlex
import os
import py.path
import sys
import tempfile
import textwrap
import subprocess
import traceback
from types import TracebackType
from typing import (
    Any,
    Callable,
    Generator,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    TYPE_CHECKING,
)
from gitrevise.odb import Repository
from gitrevise.utils import sh_path
from contextlib import contextmanager
from threading import Thread, Event
from http.server import HTTPServer, BaseHTTPRequestHandler
import dummy_editor


if TYPE_CHECKING:
    from _typeshed import StrPath


@pytest.fixture(autouse=True)
def hermetic_seal(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
def repo(hermetic_seal: None) -> Generator[Repository, None, None]:
    with Repository() as repo:
        yield repo


@pytest.fixture
def short_tmpdir() -> Generator[py.path.local, None, None]:
    with tempfile.TemporaryDirectory() as tdir:
        yield py.path.local(tdir)


@contextmanager
def in_parallel(
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> "Generator[None, None, None]":
    class HelperThread(Thread):
        exception: Optional[Exception] = None

        def run(self) -> None:
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


def bash(command: str) -> None:
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


def changeline(path: "StrPath", lineno: int, newline: bytes) -> None:
    with open(path, "rb") as f:
        lines = f.readlines()
    lines[lineno] = newline
    with open(path, "wb") as f:
        f.write(b"".join(lines))


# Run the main entry point for git-revise in a subprocess.
def main(
    args: Sequence[str],
    cwd: Optional["StrPath"] = None,
    input: Optional[bytes] = None,
    check: bool = True,
) -> "subprocess.CompletedProcess[bytes]":
    cmd = [sys.executable, "-m", "gitrevise", *args]
    print("Running", cmd, dict(cwd=cwd, input=input, check=check))
    return subprocess.run(cmd, cwd=cwd, input=input, check=check)


@contextmanager
def editor_main(
    args: Sequence[str],
    cwd: Optional["StrPath"] = None,
    input: Optional[bytes] = None,
) -> "Generator[Editor, None, None]":
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

        def main_wrapper() -> Optional["subprocess.CompletedProcess[bytes]"]:
            try:
                return main(args, cwd=cwd, input=input)
            except Exception as e:
                ed.exception = e
                return None
            finally:
                if not ed.exception:
                    ed.exception = Exception(
                        "git-revise exited without invoking editor"
                    )
                ed.request_ready.set()

        with in_parallel(main_wrapper):
            yield ed


class EditorFile(BaseHTTPRequestHandler):
    indata: Optional[bytes]
    outdata: Optional[bytes]
    server: "Editor"

    def __init__(
        self,
        request: bytes,
        client_address: Tuple[str, int],
        server: "Editor",
    ) -> None:
        self.response_ready = Event()
        self.indata = None
        self.outdata = None
        self.exception = None
        super().__init__(request=request, client_address=client_address, server=server)

    def do_POST(self) -> None:
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

    def send_editor_reply(self, status: int, data: bytes) -> None:
        assert not self.response_ready.is_set(), "already replied?"
        self.send_response(status)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.response_ready.set()

        # Ensure the handle thread has shut down
        if self.server.handle_thread is not None:
            self.server.handle_thread.join()
            self.server.handle_thread = None
        assert self.server.current is None

    def startswith(self, text: bytes) -> bool:
        assert self.indata is not None
        return self.indata.startswith(text)

    def startswith_dedent(self, text: str) -> bool:
        return self.startswith(textwrap.dedent(text).encode())

    def equals(self, text: bytes) -> bool:
        return self.indata == text

    def equals_dedent(self, text: str) -> bool:
        return self.equals(textwrap.dedent(text).encode())

    def replace_dedent(self, text: Union[str, bytes]) -> None:
        if isinstance(text, str):
            text = textwrap.dedent(text).encode()
        self.outdata = text

    def __enter__(self) -> "EditorFile":
        return self

    def __exit__(
        self,
        etype: Optional[Type[BaseException]],
        evalue: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if etype is None:
            assert self.outdata
            self.send_editor_reply(200, self.outdata)
        else:
            exc = "".join(traceback.format_exception(etype, evalue, tb)).encode()
            try:
                self.send_editor_reply(500, exc)
            except:
                pass

    def __repr__(self) -> str:
        return f"<EditorFile {self.indata!r}>"


class Editor(HTTPServer):
    request_ready: Event
    handle_thread: Optional[Thread]
    current: Optional[EditorFile]
    exception: Optional[Exception]
    timeout: int

    def __init__(self) -> None:
        # Bind to a randomly-allocated free port.
        super().__init__(("127.0.0.1", 0), EditorFile)
        self.request_ready = Event()
        self.handle_thread = None
        self.current = None
        self.exception = None
        self.timeout = 10

    def next_file(self) -> EditorFile:
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

    def is_idle(self) -> bool:
        return self.handle_thread is None and self.current is None

    def __enter__(self) -> "Editor":
        return self

    def __exit__(
        self,
        etype: Optional[Type[BaseException]],
        value: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        try:
            # Only assert if we're not already raising an exception.
            if etype is None:
                assert self.is_idle()
        finally:
            self.server_close()
            if self.current:
                self.current.send_editor_reply(500, b"editor server was shut down")
