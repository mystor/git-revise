"""
Helper classes for reading cached objects from Git's Object Database.
"""

import hashlib
import re
from typing import TypeVar, Type, Dict, Union, Sequence, Optional, Mapping, Tuple, cast
from pathlib import Path
from enum import Enum
from subprocess import Popen, run, PIPE


class MissingObject(Exception):
    def __init__(self, ref: str):
        Exception.__init__(self, f"Object {ref} does not exist")


class Oid(bytes):
    def __new__(cls, b: bytes) -> 'Oid':
        if len(b) != 20:
            raise ValueError("Expected 160-bit SHA1 hash")
        return super().__new__(cls, b)  # type: ignore

    @classmethod
    def fromhex(cls, hex: str) -> 'Oid':
        return Oid(bytes.fromhex(hex))

    @classmethod
    def null(cls) -> 'Oid':
        return cls(b'\0' * 20)

    @classmethod
    def for_object(cls, tag: str, body: bytes):
        m = hashlib.sha1()
        m.update(tag.encode('ascii') + b' ' + str(len(body)).encode('ascii') + b'\0' + body)
        return cls(m.digest())

    def __repr__(self) -> str:
        return self.hex()

    def __str__(self) -> str:
        return self.hex()


class Signature:
    name: bytes
    email: bytes
    timestamp: bytes
    offset: bytes

    __slots__ = ('name', 'email', 'timestamp', 'offset')

    sig_re = re.compile(rb'''
        (?P<name>[^<>]+)<(?P<email>[^<>]+)>[ ]
        (?P<timestamp>[0-9]+)
        (?:[ ](?P<offset>[\+\-][0-9]+))?
        ''', re.X)

    @classmethod
    def parse(cls, spec: bytes) -> 'Signature':
        match = cls.sig_re.fullmatch(spec)
        assert match is not None, "Invalid Signature"

        return Signature(match.group('name').strip(),
                         match.group('email').strip(),
                         match.group('timestamp').strip(),
                         match.group('offset').strip())

    def __init__(self, name: bytes, email: bytes, timestamp: bytes, offset: bytes):
        self.name = name
        self.email = email
        self.timestamp = timestamp
        self.offset = offset

    def raw(self) -> bytes:
        return self.name + b' <' + self.email + b'> ' + self.timestamp + b' ' + self.offset

    def __repr__(self):
        return f"<Signature {self.name}, {self.email}, {self.timestamp}, {self.offset}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Signature):
            return False
        return self.name == other.name and \
            self.email == other.email and \
            self.timestamp == other.timestamp and \
            self.offset == other.offset


class Repository:
    workdir: Path
    default_author: 'Signature'
    default_committer: 'Signature'
    objects: Dict[Oid, 'GitObj']
    catfile: Popen

    def __init__(self, workdir: Optional[Path] = None):
        self.workdir = Path.cwd() if workdir is None else workdir

        # XXX(nika): Does it make more sense to cache these or call every time?
        # Cache for length of time & invalidate?
        self.default_author = Signature.parse(run(
            ['git', 'var', 'GIT_AUTHOR_IDENT'],
            stdout=PIPE, cwd=self.workdir, check=True
        ).stdout.rstrip())
        self.default_committer = Signature.parse(run(
            ['git', 'var', 'GIT_COMMITTER_IDENT'],
            stdout=PIPE, cwd=self.workdir, check=True
        ).stdout.rstrip())

        self.catfile = Popen(['git', 'cat-file', '--batch'],
                             bufsize=-1, stdin=PIPE, stdout=PIPE,
                             cwd=self.workdir)
        self.objects = {}

    def new_commit(self,
                   tree: 'Tree',
                   parents: Sequence['Commit'],
                   message: bytes,
                   author: Optional[Signature] = None,
                   committer: Optional[Signature] = None) -> 'Commit':
        """Directly create an in-memory commit object, without persisting it.
        If a commit object with these properties already exists, it will be
        returned instead."""
        if author is None:
            author = self.default_author
        if committer is None:
            committer = self.default_committer

        body = b'tree ' + tree.oid.hex().encode('ascii') + b'\n'
        for parent in parents:
            body += b'parent ' + parent.oid.hex().encode('ascii') + b'\n'
        body += b'author ' + author.raw() + b'\n'
        body += b'committer ' + committer.raw() + b'\n'
        body += b'\n'
        body += message
        return Commit(self, body)

    def new_tree(self, entries: Mapping[bytes, 'Entry']) -> 'Tree':
        def entry_key(pair: Tuple[bytes, Entry]) -> bytes:
            name, entry = pair
            # Directories are sorted in the tree listing as though they have a
            # trailing slash in their name.
            if entry.mode == Mode.DIR:
                return name + b'/'
            return name

        body = b''
        for name, entry in sorted(entries.items(), key=entry_key):
            body += cast(bytes, entry.mode.value) + b' ' + name + b'\0' + entry.oid
        return Tree(self, body)

    def index_tree(self) -> 'Tree':
        written = run(['git', 'write-tree'],
                      check=True, stdout=PIPE, cwd=self.workdir)
        oid = Oid.fromhex(written.stdout.rstrip().decode())
        return self.gettree(oid)

    def commit_staged(self, message: bytes = b'<git index>') -> 'Commit':
        return self.new_commit(self.index_tree(), [self.getcommit('HEAD')], message)

    def getobj(self, ref: Union[Oid, str]) -> 'GitObj':
        print(type(ref), ref)
        if isinstance(ref, Oid):
            if ref in self.objects:
                return self.objects[ref]
            ref = ref.hex()

        # Write out an object descriptor.
        self.catfile.stdin.write(ref.encode('ascii') + b'\n')
        self.catfile.stdin.flush()

        # Read in the response.
        resp = self.catfile.stdout.readline().decode('ascii').split()
        if len(resp) < 3:
            assert resp[1] == 'missing'
            raise MissingObject(ref)

        oid, kind, size = Oid.fromhex(resp[0]), resp[1], int(resp[2])
        body = self.catfile.stdout.read(size + 1)[:-1]
        assert size == len(body), "bad size?"

        # Create a corresponding git object. This will re-use the item in the
        # cache, if found, and add the item to the cache otherwise.
        obj: GitObj
        if kind == 'commit':
            obj = Commit(self, body)
        elif kind == 'tree':
            obj = Tree(self, body)
        elif kind == 'blob':
            obj = Blob(self, body)
        else:
            raise ValueError(f"Unknown object kind: {kind}")

        obj.persisted = True
        assert obj.oid == oid, "miscomputed oid"
        return obj

    def getcommit(self, ref: Union[Oid, str]) -> 'Commit':
        obj = self.getobj(ref)
        if isinstance(obj, Commit):
            return obj
        raise ValueError(f"{type(obj).__name__} {ref} is not a Commit!")

    def gettree(self, ref: Union[Oid, str]) -> 'Tree':
        obj = self.getobj(ref)
        if isinstance(obj, Tree):
            return obj
        raise ValueError(f"{type(obj).__name__} {ref} is not a Tree!")

    def getblob(self, ref: Union[Oid, str]) -> 'Blob':
        obj = self.getobj(ref)
        if isinstance(obj, Blob):
            return obj
        raise ValueError(f"{type(obj).__name__} {ref} is not a Blob!")


GitObjT = TypeVar('GitObjT', bound='GitObj')


class GitObj:
    repo: Repository
    body: bytes
    oid: Oid
    persisted: bool

    __slots__ = ('repo', 'body', 'oid', 'persisted')

    def __new__(cls, repo: Repository, body: bytes):
        oid = Oid.for_object(cls.gittype(), body)
        if oid in repo.objects:
            return repo.objects[oid]

        self = super().__new__(cls)
        self.repo = repo
        self.body = body
        self.oid = oid
        self.persisted = False
        repo.objects[oid] = self
        self.parse_body()
        return self

    @classmethod
    def gittype(cls) -> str:
        return cls.__name__.lower()

    def persist(self) -> None:
        if self.persisted:
            return

        self.persist_deps()
        new_oid = run(['git', 'hash-object', '--no-filters',
                       '-t', self.gittype(), '-w', '--stdin'],
                      input=self.body,
                      stdout=PIPE,
                      cwd=self.repo.workdir,
                      check=True).stdout.rstrip()

        assert Oid.fromhex(new_oid.decode('ascii')) == self.oid
        self.persisted = True

    def persist_deps(self): ...

    def parse_body(self): ...

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GitObj):
            return self.oid == other.oid
        return False


class Commit(GitObj):
    tree_oid: Oid
    parent_oids: Sequence[Oid]
    author: Signature
    committer: Signature
    message: bytes

    __slots__ = ('tree_oid', 'parent_oids', 'author', 'committer', 'message')

    def parse_body(self):
        # Split the header from the core commit message.
        hdrs, self.message = self.body.split(b'\n\n', maxsplit=1)

        # Parse the header to populate header metadata fields.
        self.parent_oids = []
        for hdr in re.split(br'\n(?! )', hdrs):
            # Parse out the key-value pairs from the header, handling
            # continuation lines.
            key, value = hdr.split(maxsplit=1)
            value = value.replace(b'\n ', b'\n')

            if key == b'tree':
                self.tree_oid = Oid.fromhex(value.decode())
            elif key == b'parent':
                self.parent_oids.append(Oid.fromhex(value.decode()))
            elif key == b'author':
                self.author = Signature.parse(value)
            elif key == b'committer':
                self.committer = Signature.parse(value)
            else:
                raise ValueError('Unknown commit header: ' + key.decode())

    def tree(self) -> 'Tree':
        return self.repo.gettree(self.tree_oid)

    def parents(self) -> Sequence['Commit']:
        return [self.repo.getcommit(parent) for parent in self.parent_oids]

    def parent(self) -> 'Commit':
        if len(self.parents()) != 1:
            raise ValueError(
                f"Commit {self.oid} has {len(self.parents())} parents")
        return self.parents()[0]

    def rebase(self, parent: 'Commit') -> 'Commit':
        from .merge import rebase
        return rebase(self, parent)

    def update(self,
               tree: Optional['Tree'] = None,
               parents: Optional[Sequence['Commit']] = None,
               message: Optional[bytes] = None,
               author: Optional[Signature] = None) -> 'Commit':
        # Compute parameters used to create the new object.
        if tree is None:
            tree = self.tree()
        if parents is None:
            parents = self.parents()
        if message is None:
            message = self.message
        if author is None:
            author = self.author

        # Check if the commit was unchanged to avoid creating a new commit if
        # only the committer has changed.
        unchanged = (tree == self.tree() and
                     parents == self.parents() and
                     message == self.message and
                     author == self.author)
        if unchanged:
            return self
        return self.repo.new_commit(tree, parents, message, author)

    def update_ref(self, ref: str, reason: str, current: Optional[Oid]):
        self.persist()
        args = ['git', 'update-ref', '-m', reason, ref, str(self.oid)]
        if current is not None:
            args.append(str(current))
        run(args, check=True, cwd=self.repo.workdir)

    def persist_deps(self) -> None:
        self.tree().persist()
        for parent in self.parents():
            parent.persist()

    def __repr__(self) -> str:
        return (f"<Commit {self.oid} "
                f"tree={self.tree_oid}, parents={self.parent_oids}, "
                f"author={self.author}, committer={self.committer}>")


class Mode(Enum):
    GITLINK = b'160000'
    SYMLINK = b'120000'
    DIR = b'40000'
    REGULAR = b'100644'
    EXEC = b'100755'

    def is_file(self) -> bool:
        return self in (Mode.REGULAR, Mode.EXEC)


class Entry(object):
    repo: Repository
    mode: Mode
    oid: Oid

    __slots__ = ('repo', 'mode', 'oid')

    def __init__(self, repo: Repository, mode: Mode, oid: Oid):
        self.repo = repo
        self.mode = mode
        self.oid = oid

    def blob(self) -> 'Blob':
        if self.mode in (Mode.REGULAR, Mode.EXEC):
            return self.repo.getblob(self.oid)
        return Blob(self.repo, b'')

    def symlink(self) -> bytes:
        if self.mode == Mode.SYMLINK:
            return self.repo.getblob(self.oid).body
        return b'<non-symlink>'

    def tree(self) -> 'Tree':
        if self.mode == Mode.DIR:
            return self.repo.gettree(self.oid)
        return Tree(self.repo, b'')

    def persist(self) -> None:
        if self.mode != Mode.GITLINK:
            self.repo.getobj(self.oid).persist()

    def __repr__(self):
        return f"<Entry {self.mode}, {self.oid}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Entry):
            return self.mode == other.mode and self.oid == other.oid
        return False


class Tree(GitObj):
    entries: Dict[bytes, Entry]

    __slots__ = ('entries',)

    def parse_body(self):
        self.entries = {}
        rest = self.body
        while len(rest) > 0:
            mode, rest = rest.split(b' ', maxsplit=1)
            name, rest = rest.split(b'\0', maxsplit=1)
            entry_oid = Oid(rest[:20])
            rest = rest[20:]
            self.entries[name] = Entry(self.repo, Mode(mode), entry_oid)

    def persist_deps(self) -> None:
        for entry in self.entries.values():
            entry.persist()

    def __repr__(self) -> str:
        return f"<Tree {self.oid} ({len(self.entries)} entries)>"


class Blob(GitObj):
    __slots__ = ()

    def __repr__(self) -> str:
        return f"<Blob {self.oid} ({len(self.body)} bytes)>"
