"""
Helper classes for reading cached objects from Git's Object Database.
"""

import subprocess
import hashlib
import re
from typing import TypeVar, Type, Dict, Union, Sequence, Optional, Mapping, Tuple, cast
from enum import Enum


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

    _default_author: Optional['Signature'] = None
    _default_committer: Optional['Signature'] = None

    sig_re = re.compile(rb'''
        (?P<name>[^<>]+)<(?P<email>[^<>]+)>[ ]
        (?P<timestamp>[0-9]+)
        (?:[ ](?P<offset>[\+\-][0-9]+))?
        ''', re.X)

    @classmethod
    def parse(cls, spec: bytes) -> 'Signature':
        match = cls.sig_re.fullmatch(spec)
        assert match is not None, "Invalid Signature"

        return Signature(
            match.group('name').strip(),
            match.group('email').strip(),
            match.group('timestamp').strip(),
            match.group('offset').strip(),
        )

    @classmethod
    def default_author(cls) -> 'Signature':
        if Signature._default_author is None:
            rv = subprocess.run(['git', 'var', 'GIT_AUTHOR_IDENT'],
                                check=True, stdout=subprocess.PIPE)
            Signature._default_author = Signature.parse(rv.stdout.rstrip())
        return Signature._default_author

    @classmethod
    def default_committer(cls) -> 'Signature':
        if Signature._default_committer is None:
            rv = subprocess.run(['git', 'var', 'GIT_COMMITTER_IDENT'],
                                check=True, stdout=subprocess.PIPE)
            Signature._default_committer = Signature.parse(rv.stdout.rstrip())
        return Signature._default_committer

    def __init__(self, name: bytes, email: bytes, timestamp: bytes, offset: bytes):
        self.name = name
        self.email = email
        self.timestamp = timestamp
        self.offset = offset

    def raw(self) -> bytes:
        return self.name + b' <' + self.email + b'> ' + self.timestamp + b' ' + self.offset

    def __repr__(self):
        return f"<Signature {self.name}, {self.email}, {self.timestamp}, {self.offset}>"


GitObjT = TypeVar('GitObjT', bound='GitObj')


class GitObj:
    tag: str
    body: bytes
    oid: Oid
    persisted: bool

    __slots__ = ('tag', 'body', 'persisted', 'oid')

    o_cache: Dict[Oid, 'GitObj'] = {}
    catfile: Optional[subprocess.Popen] = None

    def __new__(cls, body: bytes):
        tag = cls.__name__.lower()
        oid = Oid.for_object(tag, body)
        if oid in GitObj.o_cache:
            return GitObj.o_cache[oid]

        self = super().__new__(cls)
        self.tag = tag
        self.body = body
        self.oid = oid
        self.persisted = False
        GitObj.o_cache[oid] = self
        self.parse_body()
        return self

    @classmethod
    def get(cls: Type[GitObjT], ref: Union[str, Oid]) -> GitObjT:
        # If we have an OID, check the cache first, otherwise, convert it to a
        # hex string for passing to cat-file.
        if isinstance(ref, Oid):
            if ref in GitObj.o_cache:
                obj: GitObj = GitObj.o_cache[ref]
                if not isinstance(obj, cls):
                    raise ValueError(f"Unexpected {type(obj).__name__} "
                                    f"{obj.oid} (expected {cls.__name__})")
                return obj

            ref = ref.hex()

        # Spawn cat-file subprocess if it isn't running already.
        if GitObj.catfile is None:
            GitObj.catfile = subprocess.Popen(['git', 'cat-file', '--batch'],
                                              bufsize=-1,
                                              stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE)
        catfile = GitObj.catfile

        # Write out an object descriptor.
        catfile.stdin.write(ref.encode('ascii') + b'\n')
        catfile.stdin.flush()

        # Read in the response.
        response = catfile.stdout.readline().split()
        if len(response) < 3:
            assert response[1] == b'missing'
            raise MissingObject(ref)

        oid_hex, kind, size = response
        oid = Oid.fromhex(oid_hex.decode('ascii'))
        body = catfile.stdout.read(int(size) + 1)[:-1]
        assert int(size) == len(body), "bad size?"

        # Create a corresponding git object. This will re-use the item in the
        # cache, if found, and add the item to the cache otherwise.
        if kind == b'commit':
            obj = Commit(body)
        elif kind == b'tree':
            obj = Tree(body)
        elif kind == b'blob':
            obj = Blob(body)
        else:
            raise ValueError(f"Unknown object kind: {kind}")

        obj.persisted = True
        assert obj.oid == oid, "miscomputed oid"
        if not isinstance(obj, cls):
            raise ValueError(f"Unexpected {type(obj).__name__} "
                             f"{obj.oid} (expected {cls.__name__})")
        return obj

    def persist(self):
        if self.persisted:
            return

        self.persist_deps()
        new_oid = subprocess.run(['git', 'hash-object', '--no-filters',
                                  '-t', self.tag, '-w', '--stdin'],
                                 input=self.body, check=True,
                                 stdout=subprocess.PIPE).stdout.rstrip()
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

    @classmethod
    def create(cls,
               tree_oid: Oid,
               parent_oids: Sequence[Oid],
               message: bytes,
               author: Optional[Signature] = None,
               committer: Optional[Signature] = None) -> 'Commit':
        """Directly create an in-memory commit object, without persisting it.
        If a commit object with these properties already exists, it will be
        returned instead."""
        if author is None:
            author = Signature.default_author()
        if committer is None:
            committer = Signature.default_committer()

        body = b'tree ' + tree_oid.hex().encode('ascii') + b'\n'
        for parent in parent_oids:
            body += b'parent ' + parent.hex().encode('ascii') + b'\n'
        body += b'author ' + author.raw() + b'\n'
        body += b'committer ' + committer.raw() + b'\n'
        body += b'\n'
        body += message
        return Commit(body)

    @classmethod
    def head(cls) -> 'Commit':
        return Commit.get('HEAD')

    @classmethod
    def from_index(cls, message: bytes = b'<git index>') -> 'Commit':
        return Commit.create(Tree.from_index().oid, [Commit.head().oid], message)

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
        return Tree.get(self.tree_oid)

    def parents(self) -> Sequence['Commit']:
        return [Commit.get(parent) for parent in self.parent_oids]

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
        tree_oid = tree.oid if tree else self.tree_oid
        parent_oids = [p.oid for p in parents] \
            if parents else self.parent_oids
        if message is None:
            message = self.message
        if author is None:
            author = self.author

        # Check if the commit was unchanged.
        unchanged = (tree_oid == self.tree_oid and
                     parent_oids == self.parent_oids and
                     message == self.message and
                     author == self.author)
        if unchanged:
            return self
        return Commit.create(tree_oid, parent_oids, message, author)

    def update_ref(self, ref: str, reason: str, current: Optional[Oid]):
        self.persist()
        args = ['git', 'update-ref', '-m', reason, ref, str(self.oid)]
        if current is not None:
            args.append(str(current))
        subprocess.run(args, check=True)

    def persist_deps(self):
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
    mode: Mode
    oid: Oid

    __slots__ = ('mode', 'oid')

    def __init__(self, mode: Mode, oid: Oid):
        self.mode = mode
        self.oid = oid

    def blob(self) -> 'Blob':
        if self.mode in (Mode.REGULAR, Mode.EXEC):
            return Blob.get(self.oid)
        return Blob.empty()

    def symlink(self) -> bytes:
        if self.mode == Mode.SYMLINK:
            return Blob.get(self.oid).body
        return b'<non-symlink>'

    def tree(self) -> 'Tree':
        if self.mode == Mode.DIR:
            return Tree.get(self.oid)
        return Tree.empty()

    def persist(self):
        if self.mode != Mode.GITLINK:
            GitObj.get(self.oid).persist()

    def __repr__(self):
        return f"<Entry {self.mode}, {self.oid}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Entry):
            return self.mode == other.mode and self.oid == other.oid
        return False


class Tree(GitObj):
    entries: Dict[bytes, Entry]

    __slots__ = ('entries',)

    @classmethod
    def create(cls, entries: Mapping[bytes, Entry]) -> 'Tree':
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
        return Tree(body)

    @classmethod
    def empty(cls) -> 'Tree':
        return Tree(b'')

    @classmethod
    def from_index(cls) -> 'Tree':
        written = subprocess.run(['git', 'write-tree'],
                                 check=True,
                                 stdout=subprocess.PIPE)
        oid = Oid.fromhex(written.stdout.rstrip().decode())
        return Tree.get(oid)

    def parse_body(self):
        self.entries = {}
        rest = self.body
        while len(rest) > 0:
            mode, rest = rest.split(b' ', maxsplit=1)
            name, rest = rest.split(b'\0', maxsplit=1)
            entry_oid = Oid(rest[:20])
            rest = rest[20:]
            self.entries[name] = Entry(Mode(mode), entry_oid)

    def persist_deps(self):
        for entry in self.entries.values():
            entry.persist()

    def __repr__(self) -> str:
        return f"<Tree {self.oid} ({len(self.entries)} entries)>"


class Blob(GitObj):
    __slots__ = ()

    @classmethod
    def empty(cls) -> 'Blob':
        return Blob(b'')

    def __repr__(self) -> str:
        return f"<Blob {self.oid} ({len(self.body)} bytes)>"
