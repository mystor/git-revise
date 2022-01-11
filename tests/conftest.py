import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
import traceback
from concurrent.futures import CancelledError, Future
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from types import TracebackType
from typing import TYPE_CHECKING, Generator, Optional, Sequence, Type, Union

import pytest

from gitrevise.odb import Repository
from gitrevise.utils import sh_path

from . import dummy_editor

if TYPE_CHECKING:
    from typing import Any, Tuple

    from _typeshed import StrPath


@pytest.fixture(name="hermetic_seal", autouse=True)
def fixture_hermetic_seal(
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


@pytest.fixture(name="repo")
# pylint: disable=unused-argument
def fixture_repo(hermetic_seal: None) -> Generator[Repository, None, None]:
    with Repository() as repo:
        yield repo


@pytest.fixture(name="short_tmpdir")
def fixture_short_tmpdir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tdir:
        yield Path(tdir)


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
    # pylint: disable=redefined-builtin
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
    # pylint: disable=redefined-builtin
    input: Optional[bytes] = None,
) -> "Generator[Editor, None, subprocess.CompletedProcess[bytes]]":
    with pytest.MonkeyPatch().context() as monkeypatch, Editor() as ed, ThreadPoolExecutor() as tpe:
        host, port = ed.server_address
        editor_cmd = " ".join(
            shlex.quote(p)
            for p in (
                sys.executable,
                dummy_editor.__file__,
                f"http://{host}:{port}/",
            )
        )
        monkeypatch.setenv("GIT_EDITOR", editor_cmd)

        # Run the command asynchronously.
        future = tpe.submit(main, args, cwd=cwd, input=input)

        # If it fails, cancel anything waiting on `ed.next_file()`.
        def cancel_on_error(future: "Future[Any]") -> None:
            exc = future.exception()
            if exc:
                ed.cancel_all_pending_edits(exc)

        future.add_done_callback(cancel_on_error)

        # Yield the editor, so that tests can process incoming requests via `ed.next_file()`.
        yield ed

        return future.result()


class EditorFile:
    indata: bytes
    outdata: Optional[bytes]

    def __init__(self, indata: bytes) -> None:
        self.indata = indata
        self.outdata = None

    def startswith(self, text: bytes) -> bool:
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

    def __repr__(self) -> str:
        return f"<EditorFile {self.indata!r}>"


class EditorFileRequestHandler(BaseHTTPRequestHandler):
    server: "Editor"

    # pylint: disable=invalid-name
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length"))
        in_data = self.rfile.read(length)

        try:
            # The request is ready. Tell our server, and wait for a reply.
            status, out_data = 200, self.server.await_edit(in_data)
        except Exception:  # pylint: disable=broad-except
            status, out_data = 500, traceback.format_exc().encode()
        finally:
            self.send_response(status)
            self.send_header("content-length", str(len(out_data)))
            self.end_headers()
            self.wfile.write(out_data)


class Editor(HTTPServer):
    pending_edits: "Queue[Tuple[bytes, Future[bytes]]]"
    handle_thread: Thread
    timeout: int

    def __init__(self) -> None:
        # Bind to a randomly-allocated free port.
        super().__init__(("127.0.0.1", 0), EditorFileRequestHandler)
        self.pending_edits = Queue()
        self.timeout = 10
        self.handle_thread = Thread(
            name="editor-server",
            target=lambda: self.serve_forever(poll_interval=0.01),
        )

    def await_edit(self, in_data: bytes) -> bytes:
        """Enqueues an edit and then synchronously waits for it to be processed."""
        result_future: "Future[bytes]" = Future()
        # Add the request to be picked up when the test calls `next_file`.
        self.pending_edits.put((in_data, result_future))
        # Wait for the result and return it (or throw).
        return result_future.result(timeout=self.timeout)

    @contextmanager
    def next_file(self) -> Generator[EditorFile, None, None]:
        try:
            in_data, result_future = self.pending_edits.get(timeout=self.timeout)
        except Empty as e:
            raise Exception("timeout while waiting for request") from e

        if result_future.done() or not result_future.set_running_or_notify_cancel():
            raise result_future.exception() or CancelledError()

        try:
            editor_file = EditorFile(in_data)

            # Yield the request we received and were notified about.
            # The test can modify the contents.
            yield editor_file

            assert editor_file.outdata
            result_future.set_result(editor_file.outdata)
        except Exception as e:
            result_future.set_exception(e)
            raise
        finally:
            self.pending_edits.task_done()

    def cancel_all_pending_edits(self, exc: Optional[BaseException] = None) -> None:
        if self.handle_thread.is_alive():
            self.shutdown()

        # Cancel all of the pending edit requests.
        while True:
            try:
                _body, task = self.pending_edits.get_nowait()
            except Empty:
                break
            if task.cancel():
                self.pending_edits.task_done()

        # If there were no edit requests, the main test thread may be blocked on `next_file`.
        # Give that thread a canceled future to wake it up.
        canceled_future: "Future[bytes]" = Future()
        canceled_future.set_exception(exc or CancelledError())
        self.pending_edits.put_nowait((b"cancelled", canceled_future))

    def server_close(self) -> None:
        self.handle_thread.join()
        super().server_close()

    def __enter__(self) -> "Editor":
        super().__enter__()
        self.handle_thread.start()
        return self

    # The super class just defines this as *args.
    # pylint: disable=arguments-differ
    def __exit__(
        self,
        etype: Optional[Type[BaseException]],
        value: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        try:
            # Only assert if we're not already raising an exception.
            if etype is None:
                assert self.pending_edits.empty()
        finally:
            self.cancel_all_pending_edits(value)
            super().__exit__(etype, value, tb)


__all__ = (
    "bash",
    "changeline",
    "editor_main",
    "main",
    "Editor",
)
