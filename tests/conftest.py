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
from queue import Queue, Empty


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


class TestRepo(Repository):
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
    return TestRepo(workdir)


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


def install_editor(monkeypatch):
    # Use our fake editor as the `EDITOR` environment variable.
    editor = [
        sys.executable,
        "-c",
        textwrap.dedent(
            """\
            import sys
            from pathlib import Path
            from urllib.request import urlopen

            path = Path(sys.argv[1]).resolve()
            print("FAKE_EDITOR: Sending Edit Request", path)
            resp = urlopen(
                'http://127.0.0.1:8190/',
                data=path.read_bytes(),
                timeout=5,
            )

            print("FAKE_EDITOR: Reading Edit Reply", path)
            length = int(resp.headers.get('content-length'))
            path.write_bytes(resp.read(length))

            print("FAKE_EDITOR: Finished Edit", path)
            """
        ),
    ]
    quoted = " ".join(shlex.quote(part) for part in editor)
    assert shlex.split(quoted) == editor
    monkeypatch.setenv("EDITOR", quoted)


class EditorHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # The request is ready, tell our server.
        assert self.server.current is None
        self.server.current = self
        self.server.request_ready.set()

        # Wait for the response to become ready
        self.server.response_ready.wait()
        self.server.response_ready.clear()
        self.server.current = None


class EditorServer(HTTPServer):
    def __init__(self, server_address):
        super().__init__(server_address, EditorHandler)
        self.request_ready = Event()
        self.response_ready = Event()
        self.handle_thread = None
        self.current = None
        self.timeout = 5

    def get(self):
        assert self.handle_thread is None
        assert self.current is None

        # Spawn a thread to handle the single request
        self.handle_thread = Thread(target=self.handle_request)
        self.handle_thread.start()

        # Wait for the request to be ready
        if not self.request_ready.wait(timeout=self.timeout):
            raise Exception("timeout while waiting for request")
        self.request_ready.clear()

        assert self.current
        length = int(self.current.headers.get("content-length"))
        return self.current.rfile.read(length)

    def put(self, value):
        assert self.handle_thread
        assert self.current

        # Send the response
        self.current.send_response(200)
        self.current.send_header("content-length", len(value))
        self.current.end_headers()
        self.current.wfile.write(value)
        self.current = None

        # Notify handler the response is ready, and wait for it to exit.
        self.response_ready.set()
        self.handle_thread.join()
        self.handle_thread = None

    def is_idle(self):
        return self.handle_thread is None and self.current is None

    def close(self):
        self.server_close()
        self.response_ready.set()


@pytest.fixture
def fake_editor(monkeypatch):
    install_editor(monkeypatch)

    @contextmanager
    def fake_editor(handler):
        server = EditorServer(("127.0.0.1", 8190))
        try:
            with in_parallel(handler, server, server):
                yield
            assert server.is_idle()
        finally:
            server.close()

    return fake_editor
