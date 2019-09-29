# pylint: skip-file

import pytest
import shutil
import shlex
import os
import sys
import textwrap
import subprocess
import traceback
import time
from pathlib import Path
from gitrevise.odb import Repository
from contextlib import contextmanager
from threading import Thread, Event
from http.server import HTTPServer, BaseHTTPRequestHandler


RESOURCES = Path(__file__).parent / "resources"


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


@pytest.fixture
def bash(repo):
    def run_bash(command, check=True, cwd=repo.workdir):
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


class WrappedRepo(Repository):
    """repository object with extra helper methods for writing tests"""

    def load_template(self, name):
        def renamer(path):
            # If a segment named _git is present, replace it with .git.
            return Path(*[".git" if p == "_git" else p for p in path.parts])

        _docopytree(RESOURCES / name, self.workdir, renamer=renamer)


@pytest.fixture
def repo(tmp_path_factory, monkeypatch):
    # Create a working directory, and start the repository in it.
    # We also change into a different temporary directory to make sure the code
    # doesn't require pwd to be the workdir.
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))

    workdir = tmp_path_factory.mktemp("repo")
    subprocess.run(["git", "init", "-q"], check=True, cwd=workdir)
    return WrappedRepo(workdir)


@pytest.fixture
def main(repo):
    # Run the main entry point for git-revise in a subprocess.
    def main(args, **kwargs):
        kwargs.setdefault("cwd", repo.workdir)
        kwargs.setdefault("check", True)
        cmd = [sys.executable, "-m", "gitrevise", *args]
        print("Running", cmd, kwargs)
        return subprocess.run(cmd, **kwargs)

    return main


EDITOR_SERVER_ADDR = ("127.0.0.1", 8190)


class EditorFile(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.response_ready = Event()
        self.indata = None
        self.outdata = None
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
        super().__init__(EDITOR_SERVER_ADDR, EditorFile)
        self.request_ready = Event()
        self.handle_thread = None
        self.current = None
        self.timeout = 5

    def next_file(self):
        assert self.handle_thread is None
        assert self.current is None

        # Spawn a thread to handle the single request.
        self.request_ready.clear()
        self.handle_thread = Thread(target=self.handle_request)
        self.handle_thread.start()
        if not self.request_ready.wait(timeout=self.timeout):
            raise Exception("timeout while waiting for request")

        # Return the request we received and were notified about.
        assert self.current
        return self.current

    def get(self):
        edit = self.next_file()
        assert self.current == edit
        return edit.indata

    def put(self, value):
        assert self.current
        self.current.send_editor_reply(200, value)
        assert self.current is None
        assert self.handle_thread is None

    def is_idle(self):
        return self.handle_thread is None and self.current is None

    def close(self):
        self.server_close()
        if self.current:
            self.current.send_editor_reply(500, b"editor server was shut down")

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        try:
            # Only assert if we're not already raising an exception.
            if etype is None:
                assert self.is_idle()
        finally:
            self.close()


@pytest.fixture(autouse=True)
def install_editor(monkeypatch):
    url = f"http://{EDITOR_SERVER_ADDR[0]}:{EDITOR_SERVER_ADDR[1]}/"
    # Use our fake editor as the `EDITOR` environment variable.
    editor = [
        sys.executable,
        "-c",
        textwrap.dedent(
            f"""\
            import sys
            from pathlib import Path
            from urllib.request import urlopen

            path = Path(sys.argv[1]).resolve()
            print("FAKE_EDITOR: Sending Edit Request", path)
            with urlopen('{url}', data=path.read_bytes(), timeout=5) as r:
                length = int(r.headers.get('content-length'))
                data = r.read(length)
                if r.status != 200:
                    raise Exception(data.decode())
            path.write_bytes(data)
            print("FAKE_EDITOR: Finished Edit", path)
            """
        ),
    ]
    quoted = " ".join(shlex.quote(part) for part in editor)
    assert shlex.split(quoted) == editor
    monkeypatch.setenv("EDITOR", quoted)
