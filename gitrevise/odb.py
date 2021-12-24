"""
Helper classes for reading cached objects from Git's Object Database.
"""

from __future__ import annotations

import hashlib
import re
import os
from typing import (
    TypeVar,
    Type,
    Dict,
    Union,
    Sequence,
    Optional,
    Mapping,
    Generic,
    Tuple,
    cast,
)
import sys
from types import TracebackType
from pathlib import Path
from enum import Enum
from subprocess import Popen, run, PIPE, CalledProcessError
from collections import defaultdict
from tempfile import TemporaryDirectory


class MissingObject(Exception):
    """Exception raised when a commit cannot be found in the ODB"""

    def __init__(self, ref: str) -> None:
        Exception.__init__(self, f"Object {ref} does not exist")


class GPGSignError(Exception):
    """Exception raised when we fail to sign a commit"""

    def __init__(self, stderr: str) -> None:
        Exception.__init__(self, f"unable to sign object: {stderr}")


T = TypeVar("T")  # pylint: disable=invalid-name


class Oid(bytes):
    """Git object identifier"""

    __slots__ = ()

    def __new__(cls, b: bytes) -> Oid:
        if len(b) != 20:
            raise ValueError("Expected 160-bit SHA1 hash")
        return super().__new__(cls, b)  # type: ignore

    @classmethod
    def fromhex(cls, instr: str) -> Oid:
        """Parse an ``Oid`` from a hexadecimal string"""
        return Oid(bytes.fromhex(instr))

    @classmethod
    def null(cls) -> Oid:
        """An ``Oid`` consisting of entirely 0s"""
        return cls(b"\0" * 20)

    def short(self) -> str:
        """A shortened version of the Oid's hexadecimal form"""
        return str(self)[:12]

    @classmethod
    def for_object(cls, tag: str, body: bytes) -> Oid:
        """Hash an object with the given type tag and body to determine its Oid"""
        hasher = hashlib.sha1()
        hasher.update(tag.encode() + b" " + str(len(body)).encode() + b"\0" + body)
        return cls(hasher.digest())

    def __repr__(self) -> str:
        return self.hex()

    def __str__(self) -> str:
        return self.hex()


class Signature(bytes):
    """Git user signature"""

    __slots__ = ()

    sig_re = re.compile(
        rb"""
        (?P<signing_key>
            (?P<name>[^<>]+)<(?P<email>[^<>]+)>
        )
        [ ]
        (?P<timestamp>[0-9]+)
        (?:[ ](?P<offset>[\+\-][0-9]+))?
        """,
        re.X,
    )

    @property
    def name(self) -> bytes:
        """user name"""
        match = self.sig_re.fullmatch(self)
        assert match, "invalid signature"
        return match.group("name").strip()

    @property
    def email(self) -> bytes:
        """user email"""
        match = self.sig_re.fullmatch(self)
        assert match, "invalid signature"
        return match.group("email").strip()

    @property
    def signing_key(self) -> bytes:
        """user name <email>"""
        match = self.sig_re.fullmatch(self)
        assert match, "invalid signature"
        return match.group("signing_key").strip()

    @property
    def timestamp(self) -> bytes:
        """unix timestamp"""
        match = self.sig_re.fullmatch(self)
        assert match, "invalid signature"
        return match.group("timestamp").strip()

    @property
    def offset(self) -> bytes:
        """timezone offset from UTC"""
        match = self.sig_re.fullmatch(self)
        assert match, "invalid signature"
        return match.group("offset").strip()


class Repository:
    """Main entry point for a git repository"""

    workdir: Path
    """working directory for this repository"""

    gitdir: Path
    """.git directory for this repository"""

    default_author: Signature
    """author used by default for new commits"""

    default_committer: Signature
    """committer used by default for new commits"""

    index: Index
    """current index state"""

    sign_commits: bool
    """sign commits with gpg"""

    gpg: bytes
    """path to GnuPG binary"""

    _objects: Dict[int, Dict[Oid, GitObj]]
    _catfile: Popen
    _tempdir: Optional[TemporaryDirectory]

    __slots__ = [
        "workdir",
        "gitdir",
        "default_author",
        "default_committer",
        "index",
        "sign_commits",
        "gpg",
        "_objects",
        "_catfile",
        "_tempdir",
    ]

    def __init__(self, cwd: Optional[Path] = None) -> None:
        self._tempdir = None

        self.workdir = Path(self.git("rev-parse", "--show-toplevel", cwd=cwd).decode())
        self.gitdir = self.workdir / Path(self.git("rev-parse", "--git-dir").decode())

        # XXX(nika): Does it make more sense to cache these or call every time?
        # Cache for length of time & invalidate?
        self.default_author = Signature(self.git("var", "GIT_AUTHOR_IDENT"))
        self.default_committer = Signature(self.git("var", "GIT_COMMITTER_IDENT"))

        self.index = Index(self)

        self.sign_commits = self.bool_config(
            "revise.gpgSign", default=self.bool_config("commit.gpgSign", default=False)
        )

        self.gpg = self.config("gpg.program", default=b"gpg")

        # Pylint 2.8 emits a false positive; fixed in 2.9.
        self._catfile = Popen(  # pylint: disable=consider-using-with
            ["git", "cat-file", "--batch"],
            bufsize=-1,
            stdin=PIPE,
            stdout=PIPE,
            cwd=self.workdir,
        )
        self._objects = defaultdict(dict)

        # Check that cat-file works OK
        try:
            self.get_obj(Oid.null())
            raise IOError("cat-file backend failure")
        except MissingObject:
            pass

    def git(
        self,
        *cmd: str,
        cwd: Optional[Path] = None,
        stdin: Optional[bytes] = None,
        trim_newline: bool = True,
        env: Dict[str, str] = None,
        nocapture: bool = False,
    ) -> bytes:
        if cwd is None:
            cwd = getattr(self, "workdir", None)

        cmd = ("git",) + cmd
        prog = run(
            cmd,
            stdout=None if nocapture else PIPE,
            cwd=cwd,
            env=env,
            input=stdin,
            check=True,
        )

        if nocapture:
            return b""
        if trim_newline and prog.stdout.endswith(b"\n"):
            return prog.stdout[:-1]
        return prog.stdout

    def config(self, setting: str, default: T) -> Union[bytes, T]:
        try:
            return self.git("config", "--get", setting)
        except CalledProcessError:
            return default

    def bool_config(self, config: str, default: T) -> Union[bool, T]:
        try:
            return self.git("config", "--get", "--bool", config) == b"true"
        except CalledProcessError:
            return default

    def int_config(self, config: str, default: T) -> Union[int, T]:
        try:
            return int(self.git("config", "--get", "--int", config))
        except CalledProcessError:
            return default

    def __enter__(self) -> Repository:
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[Exception],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._tempdir:
            self._tempdir.__exit__(exc_type, exc_val, exc_tb)

        self._catfile.terminate()
        self._catfile.wait()

    def get_tempdir(self) -> Path:
        """Return a temporary directory to use for modifications to this repository"""
        if self._tempdir is None:
            # Pylint 2.8 emits a false positive; fixed in 2.9.
            self._tempdir = TemporaryDirectory(  # pylint: disable=consider-using-with
                prefix="revise.", dir=str(self.gitdir)
            )
        return Path(self._tempdir.name)

    def git_path(self, path: Union[str, Path]) -> Path:
        """Get the path to a file in the .git directory, respecting the environment"""
        return self.workdir / self.git("rev-parse", "--git-path", str(path)).decode()

    def new_commit(
        self,
        tree: Tree,
        parents: Sequence[Commit],
        message: bytes,
        author: Optional[Signature] = None,
        committer: Optional[Signature] = None,
    ) -> Commit:
        """Directly create an in-memory commit object, without persisting it.
        If a commit object with these properties already exists, it will be
        returned instead."""
        if author is None:
            author = self.default_author
        if committer is None:
            committer = self.default_committer

        body = b"tree " + tree.oid.hex().encode() + b"\n"
        for parent in parents:
            body += b"parent " + parent.oid.hex().encode() + b"\n"
        body += b"author " + author + b"\n"
        body += b"committer " + committer + b"\n"

        body_tail = b"\n" + message
        body += self.sign_buffer(body + body_tail)
        body += body_tail

        return Commit(self, body)

    def sign_buffer(self, buffer: bytes) -> bytes:
        """Return the text of the signed commit object."""
        from .utils import sh_run  # pylint: disable=import-outside-toplevel

        if not self.sign_commits:
            return b""

        key_id = self.config(
            "user.signingKey", default=self.default_committer.signing_key
        )
        gpg = None
        try:
            gpg = sh_run(
                (self.gpg, "--status-fd=2", "-bsau", key_id),
                stdout=PIPE,
                stderr=PIPE,
                input=buffer,
                check=True,
            )
        except CalledProcessError as gpg:
            print(gpg.stderr.decode(), file=sys.stderr, end="")
            print("gpg failed to sign commit", file=sys.stderr)
            raise

        if b"\n[GNUPG:] SIG_CREATED " not in gpg.stderr:
            raise GPGSignError(gpg.stderr.decode())

        signature = b"gpgsig"
        for line in gpg.stdout.splitlines():
            signature += b" " + line + b"\n"
        return signature

    def new_tree(self, entries: Mapping[bytes, Entry]) -> Tree:
        """Directly create an in-memory tree object, without persisting it.
        If a tree object with these entries already exists, it will be
        returned instead."""

        def entry_key(pair: Tuple[bytes, Entry]) -> bytes:
            name, entry = pair
            # Directories are sorted in the tree listing as though they have a
            # trailing slash in their name.
            if entry.mode == Mode.DIR:
                return name + b"/"
            return name

        body = b""
        for name, entry in sorted(entries.items(), key=entry_key):
            body += cast(bytes, entry.mode.value) + b" " + name + b"\0" + entry.oid
        return Tree(self, body)

    def get_obj(self, ref: Union[Oid, str]) -> GitObj:
        """Get the identified git object from this repository. If given an
        :class:`Oid`, the cache will be checked before asking git."""
        if isinstance(ref, Oid):
            cache = self._objects[ref[0]]
            if ref in cache:
                return cache[ref]
            ref = ref.hex()

        # Satisfy mypy: otherwise these are Optional[IO[Any]].
        (stdin, stdout) = (self._catfile.stdin, self._catfile.stdout)
        assert stdin is not None
        assert stdout is not None

        # Write out an object descriptor.
        stdin.write(ref.encode() + b"\n")
        stdin.flush()

        # Read in the response.
        resp = stdout.readline().decode()
        if resp.endswith("missing\n"):
            # If we have an abbreviated hash, check for in-memory commits.
            try:
                abbrev = bytes.fromhex(ref)
                for oid, obj in self._objects[abbrev[0]].items():
                    if oid.startswith(abbrev):
                        return obj
            except (ValueError, IndexError):
                pass

            # Not an abbreviated hash, the entry is missing.
            raise MissingObject(ref)

        parts = resp.rsplit(maxsplit=2)
        oid, kind, size = Oid.fromhex(parts[0]), parts[1], int(parts[2])
        body = stdout.read(size + 1)[:-1]
        assert size == len(body), "bad size?"

        # Create a corresponding git object. This will re-use the item in the
        # cache, if found, and add the item to the cache otherwise.
        if kind == "commit":
            obj = Commit(self, body)
        elif kind == "tree":
            obj = Tree(self, body)
        elif kind == "blob":
            obj = Blob(self, body)
        else:
            raise ValueError(f"Unknown object kind: {kind}")

        obj.persisted = True
        assert obj.oid == oid, "miscomputed oid"
        return obj

    def get_commit(self, ref: Union[Oid, str]) -> Commit:
        """Like :py:meth:`get_obj`, but returns a :class:`Commit`"""
        obj = self.get_obj(ref)
        if isinstance(obj, Commit):
            return obj
        raise ValueError(f"{type(obj).__name__} {ref} is not a Commit!")

    def get_tree(self, ref: Union[Oid, str]) -> Tree:
        """Like :py:meth:`get_obj`, but returns a :class:`Tree`"""
        obj = self.get_obj(ref)
        if isinstance(obj, Tree):
            return obj
        raise ValueError(f"{type(obj).__name__} {ref} is not a Tree!")

    def get_blob(self, ref: Union[Oid, str]) -> Blob:
        """Like :py:meth:`get_obj`, but returns a :class:`Blob`"""
        obj = self.get_obj(ref)
        if isinstance(obj, Blob):
            return obj
        raise ValueError(f"{type(obj).__name__} {ref} is not a Blob!")

    def get_obj_ref(self, ref: str) -> Reference[GitObj]:
        """Get a :class:`Reference` to a :class:`GitObj`"""
        return Reference(GitObj, self, ref)

    def get_commit_ref(self, ref: str) -> Reference[Commit]:
        """Get a :class:`Reference` to a :class:`Commit`"""
        return Reference(Commit, self, ref)

    def get_tree_ref(self, ref: str) -> Reference[Tree]:
        """Get a :class:`Reference` to a :class:`Tree`"""
        return Reference(Tree, self, ref)

    def get_blob_ref(self, ref: str) -> Reference[Blob]:
        """Get a :class:`Reference` to a :class:`Blob`"""
        return Reference(Blob, self, ref)


GitObjT = TypeVar("GitObjT", bound="GitObj")


class GitObj:
    """In-memory representation of a git object. Instances of this object
    should be one of :class:`Commit`, :class:`Tree` or :class:`Blob`"""

    repo: Repository
    """:class:`Repository` object is associated with"""

    body: bytes
    """Raw body of object in bytes"""

    oid: Oid
    """:class:`Oid` of this git object"""

    persisted: bool
    """If ``True``, the object has been persisted to disk"""

    __slots__ = ("repo", "body", "oid", "persisted")

    def __new__(cls: Type[GitObjT], repo: Repository, body: bytes) -> GitObjT:
        oid = Oid.for_object(cls._git_type(), body)
        cache = repo._objects[oid[0]]  # pylint: disable=protected-access
        if oid in cache:
            cached = cache[oid]
            assert isinstance(cached, cls)
            return cached

        self = super().__new__(cls)
        self.repo = repo
        self.body = body
        self.oid = oid
        self.persisted = False
        cache[oid] = self
        self._parse_body()  # pylint: disable=protected-access
        return cast(GitObjT, self)

    @classmethod
    def _git_type(cls) -> str:
        return cls.__name__.lower()

    def persist(self) -> Oid:
        """If this object has not been persisted to disk yet, persist it"""
        if self.persisted:
            return self.oid

        self._persist_deps()
        new_oid = self.repo.git(
            "hash-object",
            "--no-filters",
            "-t",
            self._git_type(),
            "-w",
            "--stdin",
            stdin=self.body,
        )

        assert Oid.fromhex(new_oid.decode()) == self.oid
        self.persisted = True
        return self.oid

    def _persist_deps(self) -> None:
        pass

    def _parse_body(self) -> None:
        pass

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GitObj):
            return self.oid == other.oid
        return False


class Commit(GitObj):
    """In memory representation of a git ``commit`` object"""

    tree_oid: Oid
    """:class:`Oid` of this commit's ``tree`` object"""

    parent_oids: Sequence[Oid]
    """List of :class:`Oid` for this commit's parents"""

    author: Signature
    """:class:`Signature` of this commit's author"""

    committer: Signature
    """:class:`Signature` of this commit's committer"""

    gpgsig: Optional[bytes]
    """GPG signature of this commit"""

    message: bytes
    """Body of this commit's message"""

    __slots__ = ("tree_oid", "parent_oids", "author", "committer", "gpgsig", "message")

    def _parse_body(self) -> None:
        # Split the header from the core commit message.
        hdrs, self.message = self.body.split(b"\n\n", maxsplit=1)

        # Parse the header to populate header metadata fields.
        self.parent_oids = []
        for hdr in re.split(br"\n(?! )", hdrs):
            # Parse out the key-value pairs from the header, handling
            # continuation lines.
            key, value = hdr.split(maxsplit=1)
            value = value.replace(b"\n ", b"\n")

            self.gpgsig = None
            if key == b"tree":
                self.tree_oid = Oid.fromhex(value.decode())
            elif key == b"parent":
                self.parent_oids.append(Oid.fromhex(value.decode()))
            elif key == b"author":
                self.author = Signature(value)
            elif key == b"committer":
                self.committer = Signature(value)
            elif key == b"gpgsig":
                self.gpgsig = value

    def tree(self) -> Tree:
        """``tree`` object corresponding to this commit"""
        return self.repo.get_tree(self.tree_oid)

    def parent_tree(self) -> Tree:
        """``tree`` object corresponding to the first parent of this commit,
        or the null tree if this is a root commit"""
        if self.is_root:
            return Tree(self.repo, b"")
        return self.parents()[0].tree()

    @property
    def is_root(self) -> bool:
        """Whether this commit has no parents"""
        return not self.parent_oids

    def parents(self) -> Sequence[Commit]:
        """List of parent commits"""
        return [self.repo.get_commit(parent) for parent in self.parent_oids]

    def parent(self) -> Commit:
        """Helper method to get the single parent of a commit. Raises
        :class:`ValueError` if the incorrect number of parents are
        present."""
        if len(self.parents()) != 1:
            raise ValueError(f"Commit {self.oid} has {len(self.parents())} parents")
        return self.parents()[0]

    def summary(self) -> str:
        """The summary line of the commit message. Returns the summary
        as a single line, even if it spans multiple lines."""
        summary_paragraph = self.message.split(b"\n\n", maxsplit=1)[0].decode(
            errors="replace"
        )
        return " ".join(summary_paragraph.splitlines())

    def rebase(self, parent: Optional[Commit]) -> Commit:
        """Create a new commit with the same changes, except with ``parent``
        as its parent. If ``parent`` is ``None``, this becomes a root commit."""
        from .merge import rebase  # pylint: disable=import-outside-toplevel

        return rebase(self, parent)

    def update(
        self,
        tree: Optional[Tree] = None,
        parents: Optional[Sequence[Commit]] = None,
        message: Optional[bytes] = None,
        author: Optional[Signature] = None,
        recommit: bool = False,
    ) -> Commit:
        """Create a new commit with specific properties updated or replaced"""
        # Compute parameters used to create the new object.
        if tree is None:
            tree = self.tree()
        if parents is None:
            parents = self.parents()
        if message is None:
            message = self.message
        if author is None:
            author = self.author

        if not recommit:
            # Check if the commit was unchanged to avoid creating a new commit if
            # only the committer has changed.
            unchanged = (
                tree == self.tree()
                and parents == self.parents()
                and message == self.message
                and author == self.author
            )
            if unchanged:
                return self

        return self.repo.new_commit(tree, parents, message, author)

    def _persist_deps(self) -> None:
        self.tree().persist()
        for parent in self.parents():
            parent.persist()

    def __repr__(self) -> str:
        return (
            f"<Commit {repr(self.oid)} "
            f"tree={repr(self.tree_oid)}, parents={repr(self.parent_oids)}, "
            f"author={repr(self.author)}, committer={repr(self.committer)}>"
        )


class Mode(Enum):
    """Mode for an entry in a ``tree``"""

    GITLINK = b"160000"
    """submodule entry"""

    SYMLINK = b"120000"
    """symlink entry"""

    DIR = b"40000"
    """directory entry"""

    REGULAR = b"100644"
    """regular entry"""

    EXEC = b"100755"
    """executable entry"""

    def is_file(self) -> bool:
        return self in (Mode.REGULAR, Mode.EXEC)

    def comparable_to(self, other: Mode) -> bool:
        return self == other or (self.is_file() and other.is_file())


class Entry:
    """In memory representation of a single ``tree`` entry"""

    repo: Repository
    """:class:`Repository` this entry originates from"""

    mode: Mode
    """:class:`Mode` of the entry"""

    oid: Oid
    """:class:`Oid` of this entry's object"""

    __slots__ = ("repo", "mode", "oid")

    def __init__(self, repo: Repository, mode: Mode, oid: Oid) -> None:
        self.repo = repo
        self.mode = mode
        self.oid = oid

    def blob(self) -> Blob:
        """Get the data for this entry as a :class:`Blob`"""
        if self.mode in (Mode.REGULAR, Mode.EXEC):
            return self.repo.get_blob(self.oid)
        return Blob(self.repo, b"")

    def symlink(self) -> bytes:
        """Get the data for this entry as a symlink"""
        if self.mode == Mode.SYMLINK:
            return self.repo.get_blob(self.oid).body
        return b"<non-symlink>"

    def tree(self) -> Tree:
        """Get the data for this entry as a :class:`Tree`"""
        if self.mode == Mode.DIR:
            return self.repo.get_tree(self.oid)
        return Tree(self.repo, b"")

    def persist(self) -> None:
        """:py:meth:`GitObj.persist` the git object referenced by this entry"""
        if self.mode != Mode.GITLINK:
            self.repo.get_obj(self.oid).persist()

    def __repr__(self) -> str:
        return f"<Entry {self.mode}, {self.oid}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Entry):
            return self.mode == other.mode and self.oid == other.oid
        return False


class Tree(GitObj):
    """In memory representation of a git ``tree`` object"""

    entries: Dict[bytes, Entry]
    """mapping from entry names to entry objects in this tree"""

    __slots__ = ("entries",)

    def _parse_body(self) -> None:
        self.entries = {}
        rest = self.body
        while rest:
            mode, rest = rest.split(b" ", maxsplit=1)
            name, rest = rest.split(b"\0", maxsplit=1)
            entry_oid = Oid(rest[:20])
            rest = rest[20:]
            self.entries[name] = Entry(self.repo, Mode(mode), entry_oid)

    def _persist_deps(self) -> None:
        for entry in self.entries.values():
            entry.persist()

    def to_index(self, path: Path, skip_worktree: bool = False) -> Index:
        """Read tree into a temporary index. If skip_workdir is ``True``, every
        entry in the index will have its "Skip Workdir" bit set."""

        index = Index(self.repo, path)
        self.repo.git("read-tree", "--index-output=" + str(path), self.persist().hex())

        # If skip_worktree is set, mark every file as --skip-worktree.
        if skip_worktree:
            # XXX(nika): Could be done with a pipe, which might improve perf.
            files = index.git("ls-files")
            index.git("update-index", "--skip-worktree", "--stdin", stdin=files)

        return index

    def __repr__(self) -> str:
        return f"<Tree {self.oid} ({len(self.entries)} entries)>"


class Blob(GitObj):
    """In memory representation of a git ``blob`` object"""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"<Blob {self.oid} ({len(self.body)} bytes)>"


class Index:
    """Handle on an index file"""

    repo: Repository
    """"""

    index_file: Path
    """Index file being referenced"""

    def __init__(self, repo: Repository, index_file: Optional[Path] = None) -> None:
        self.repo = repo

        if index_file is None:
            index_file = self.repo.git_path("index")
        self.index_file = index_file

        assert self.git("rev-parse", "--git-path", "index").decode() == str(index_file)

    def git(
        self,
        *cmd: str,
        cwd: Optional[Path] = None,
        stdin: Optional[bytes] = None,
        trim_newline: bool = True,
        env: Optional[Mapping[str, str]] = None,
        nocapture: bool = False,
    ) -> bytes:
        """Invoke git with the given index as active"""
        env = dict(**env) if env is not None else dict(**os.environ)
        env["GIT_INDEX_FILE"] = str(self.index_file)
        return self.repo.git(
            *cmd,
            cwd=cwd,
            stdin=stdin,
            trim_newline=trim_newline,
            env=env,
            nocapture=nocapture,
        )

    def tree(self) -> Tree:
        """Get a :class:`Tree` object for this index's state"""
        oid = Oid.fromhex(self.git("write-tree").decode())
        return self.repo.get_tree(oid)

    def commit(
        self, message: bytes = b"<git index>", parent: Optional[Commit] = None
    ) -> Commit:
        """Get a :class:`Commit` for this index's state. If ``parent`` is
        ``None``, use the current ``HEAD``"""

        if parent is None:
            parent = self.repo.get_commit("HEAD")

        return self.repo.new_commit(self.tree(), [parent], message)


class Reference(Generic[GitObjT]):  # pylint: disable=unsubscriptable-object
    """A git reference"""

    shortname: str
    """Short unresolved reference name, e.g. 'HEAD' or 'master'"""

    name: str
    """Resolved reference name, e.g. 'refs/tags/1.0.0' or 'refs/heads/master'"""

    target: Optional[GitObjT]
    """Referenced git object"""

    repo: Repository
    """Repository reference is attached to"""

    _type: Type[GitObjT]

    # FIXME: On python 3.6, pylint doesn't know what to do with __slots__ here.
    # __slots__ = ("name", "target", "repo", "_type")

    def __init__(self, obj_type: Type[GitObjT], repo: Repository, name: str) -> None:
        self._type = obj_type
        self.name = repo.git("rev-parse", "--symbolic-full-name", name).decode()
        self.repo = repo
        self.refresh()

    def refresh(self) -> None:
        """Re-read the target of this reference from disk"""
        try:
            obj = self.repo.get_obj(self.name)

            if not isinstance(obj, self._type):
                raise ValueError(
                    f"{type(obj).__name__} {self.name} is not a {self._type.__name__}!"
                )

            self.target = obj
        except MissingObject:
            self.target = None

    def update(self, new: GitObjT, reason: str) -> None:
        """Update this refreence to point to a new object.
        An entry with the reason ``reason`` will be added to the reflog."""
        new.persist()
        args = ["update-ref", "-m", reason, self.name, str(new.oid)]
        if self.target is not None:
            args.append(str(self.target.oid))

        self.repo.git(*args)
        self.target = new
