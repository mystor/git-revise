"""
Helper classes for reading cached objects from Git's Object Database.
"""

import subprocess
import hashlib
import tempfile
import re
from typing import TypeVar, Type, Dict, List, Union, NewType, Sequence, Optional
from abc import ABC, abstractmethod


class MissingObject(Exception):
    def __init__(self, ref: str):
        Exception.__init__(self, f"Object {ref} does not exist")


VALID_MODES = (b'100644', b'100755', b'040000', b'120000')


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

    def __repr__(self) -> str:
        return self.hex()

    def __str__(self) -> str:
        return self.hex()


class Signature(object):
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

        return Signature(
            match.group('name').strip(),
            match.group('email').strip(),
            match.group('timestamp').strip(),
            match.group('offset').strip(),
        )

    def __init__(self, name: bytes, email: bytes, timestamp: bytes, offset: bytes):
        self.name = name
        self.email = email
        self.timestamp = timestamp
        self.offset = offset

    def raw(self) -> bytes:
        return self.name + b' <' + self.email + b'> ' + self.timestamp + b' ' + self.offset

    def __repr__(self):
        return f"<Signature {self.name}, {self.email}, {self.timestamp}, {self.offset}>"


class Entry(object):
    __slots__ = ('mode', 'name', 'obj_')

    def __init__(self, mode: bytes, name: bytes, obj: Union[Oid, 'GitObj']):
        self.mode = mode
        self.name = name
        self.obj_ = obj

    def obj(self) -> 'GitObj':
        if isinstance(self.obj_, GitObj):
            return self.obj_
        return GitObj.get(self.obj_)

    def oid(self) -> Oid:
        if isinstance(self.obj_, GitObj):
            return self.obj_.oid
        return self.obj_

    def __repr__(self):
        return f"<Entry {self.mode}, {self.name}, {self.obj_}>"


GitObjT = TypeVar('GitObjT', bound='GitObj')

class GitObj(ABC):
    __slots__ = ('oid',)

    cf_proc = None
    ho_proc: Dict[str, Optional[subprocess.Popen]] = {
        'commit': None,
        'tree': None,
        'blob': None,
    }
    o_cache: Dict[Oid, 'GitObj'] = {}

    @classmethod
    def _get_existing(cls: Type[GitObjT], key: Oid) -> GitObjT:
        obj = GitObj.o_cache[key]
        if not isinstance(obj, cls):
            raise ValueError(f"Unexpected {type(obj).__name__} "
                             f"{obj.oid} (expected {cls.__name__})")
        return obj

    @classmethod
    def get(cls: Type[GitObjT], ref: Union[str, Oid]) -> GitObjT:
        # If we have an OID, check the cache first, otherwise, convert it to a
        # hex string for passing to cat-file.
        if isinstance(ref, Oid):
            try:
                return cls._get_existing(ref)
            except KeyError:
                ref = ref.hex()

        # Spawn cat-file subprocess if it isn't running already.
        if GitObj.cf_proc is None:
            GitObj.cf_proc = subprocess.Popen(
                ['git', 'cat-file', '--batch'],
                bufsize=-1,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )

        # Write out an object descriptor.
        GitObj.cf_proc.stdin.write(ref.encode('ascii') + b'\n')
        GitObj.cf_proc.stdin.flush()

        # Read in the response.
        response = GitObj.cf_proc.stdout.readline().split()
        if len(response) < 3:
            assert response[1] == b'missing'
            raise MissingObject(ref)

        oid_bytes, kind, size = response
        body = GitObj.cf_proc.stdout.read(int(size) + 1)[:-1]
        assert int(size) == len(body), "bad size?"

        oid = Oid.fromhex(oid_bytes.decode('ascii'))

        # If the retrieved object is not in the cache, add it.
        if oid not in GitObj.o_cache:
            if kind == b'commit':
                GitObj.o_cache[oid] = Commit.parse(oid, body)
            elif kind == b'tree':
                GitObj.o_cache[oid] = Tree.parse(oid, body)
            elif kind == b'blob':
                GitObj.o_cache[oid] = Blob.parse(oid, body)
            else:
                raise ValueError(f"Unknown object kind: {kind}")

        obj = cls._get_existing(oid)
        obj.persisted = True
        return obj

    def raw_hash(self) -> Oid:
        m = hashlib.sha1()
        m.update(self.raw())
        oid = Oid(m.digest())
        assert self.oid == Oid.null() or \
            self.oid == oid, "bad round-trip"
        return oid

    def raw_hash_call(self) -> Oid:
        tag = self.__class__.__name__.lower().encode('ascii')
        proc = subprocess.run(
            ['git', 'hash-object', '-t', tag, '--stdin'],
            check=True, input=self.raw_body(),
            stdout=subprocess.PIPE,
        )
        return Oid.fromhex(proc.stdout.rstrip().decode('ascii'))

    def raw_hash_many(self) -> Oid:
        tag = self.__class__.__name__.lower()

        proc = GitObj.ho_proc[tag]
        if proc is None:
            proc = GitObj.ho_proc[tag] = subprocess.Popen(
                ['git', 'hash-object', '-t', tag, '--stdin-paths', '--no-filters'],
                bufsize=-1,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )

        with tempfile.NamedTemporaryFile() as tf:
            tf.write(self.raw_body())
            tf.flush()
            proc.stdin.write(tf.name.encode() + b'\n')
            proc.stdin.flush()
            return Oid.fromhex(proc.stdout.readline().rstrip().decode('ascii'))

    def raw(self) -> bytes:
        tag = self.__class__.__name__.lower().encode('ascii')
        assert tag in (b'commit', b'tree', b'blob')

        body = self.raw_body()
        len_bytes = str(len(body)).encode('ascii')
        return tag + b' ' + len_bytes + b'\0' + body

    @abstractmethod
    def raw_body(self) -> bytes:
        pass

    def __init__(self, oid: Oid):
        self.oid = oid
        self.persisted = False


class Commit(GitObj):
    __slots__ = ('tree_', 'parents_', 'author', 'committer', 'message')

    def __init__(self,
                 tree: Union[Oid, 'Tree'],
                 parents: Sequence[Union[Oid, 'Commit']],
                 author: Signature,
                 committer: Signature,
                 message: bytes,
                 oid: Oid = Oid.null()):
        GitObj.__init__(self, oid)
        self.tree_ = tree
        self.parents_ = parents
        self.author = author
        self.committer = committer
        self.message = message

    @classmethod
    def parse(cls, oid: Oid, body: bytes) -> 'Commit':
        # Split the header from the core commit message.
        hdrs, msg = body.split(b'\n\n', maxsplit=1)

        # Parse the header to populate header metadata fields.
        parents: List[Oid] = []

        for hdr in re.split(br'\n(?! )', hdrs):
            # Parse out the key-value pairs from the header, handling
            # continuation lines.
            key, value = hdr.split(maxsplit=1)
            value = value.replace(b'\n ', b'\n')

            if key == b'tree':
                tree = Oid.fromhex(value.decode())
            elif key == b'parent':
                parents.append(Oid.fromhex(value.decode()))
            elif key == b'author':
                author = Signature.parse(value)
            elif key == b'committer':
                committer = Signature.parse(value)
            else:
                raise ValueError('Unknown commit header: ' + key.decode())

        return Commit(tree, parents, author, committer, msg, oid)

    def tree(self) -> 'Tree':
        if isinstance(self.tree_, Tree):
            return self.tree_
        return Tree.get(self.tree_)

    def parents(self) -> Sequence['Commit']:
        return [
            parent if isinstance(parent, Commit) else Commit.get(parent)
            for parent in self.parents_
        ]

    def parent(self) -> 'Commit':
        if len(self.parents()) != 1:
            raise ValueError(f"Commit {self.oid} does not have a single parent")
        return self.parents()[0]

    def raw_body(self) -> bytes:
        body = b'tree ' + self.tree().oid.hex().encode('ascii') + b'\n'
        for parent in self.parents():
            body += b'parent ' + parent.oid.hex().encode('ascii') + b'\n'
        body += b'author ' + self.author.raw() + b'\n'
        body += b'committer ' + self.committer.raw() + b'\n'

        body += b'\n'
        body += self.message
        return body

    def __repr__(self) -> str:
        return (f"<Commit {self.oid} "
                f"tree={self.tree_}, parents={self.parents_}, "
                f"author={self.author}, committer={self.committer}>")


class Tree(GitObj):
    __slots__ = ('entries',)

    def __init__(self, entries: Sequence[Entry], oid: Oid = Oid.null()):
        GitObj.__init__(self, oid)
        self.entries = entries

    @classmethod
    def parse(cls, oid: Oid, body: bytes) -> 'Tree':
        entries: List[Entry] = []
        while len(body) > 0:
            mode, body = body.split(b' ', maxsplit=1)
            path, body = body.split(b'\0', maxsplit=1)
            entry_oid = Oid(body[:20])
            body = body[20:]
            entries.append(Entry(mode, path, entry_oid))
        return Tree(entries, oid)

    def raw_body(self) -> bytes:
        body = b''
        for entry in sorted(self.entries, key=lambda e: e.name):
            assert b'\0' not in entry.name, "Name cannot contain null byte"
            assert entry.mode in VALID_MODES, "Mode is not valid"
            body += entry.mode + b' ' + entry.name + b'\0' + entry.oid()
        return body

    def __repr__(self) -> str:
        return f"<Tree {self.oid} ({len(self.entries)} entries)>"


class Blob(GitObj):
    __slots__ = ('body',)

    def __init__(self, body: bytes, oid: Oid = Oid.null()):
        GitObj.__init__(self, oid)
        self.body = body

    @classmethod
    def parse(cls, oid: Oid, body: bytes) -> 'Blob':
        return Blob(body, oid)

    def raw_body(self) -> bytes:
        return self.body

    def __repr__(self) -> str:
        return f"<Blob {self.oid} ({len(self.body)} bytes)>"

