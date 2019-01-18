from enum import Enum
from typing import List, Optional
from .odb import Commit, Repository
from .utils import run_editor
import re

class StepKind(Enum):
    PICK = 1
    FIXUP = 2
    REWORD = 3
    INDEX = 4

    def __str__(self):
        if self == StepKind.PICK:
            return 'pick'
        elif self == StepKind.FIXUP:
            return 'fixup'
        elif self == StepKind.REWORD:
            return 'reword'
        elif self == StepKind.INDEX:
            return 'index'
        raise TypeError()

    @staticmethod
    def parse(s: str) -> StepKind:
        if len(s) < 1:
            raise ValueError()
        if 'pick'.startswith(s):
            return StepKind.PICK
        if 'fixup'.startswith(s):
            return StepKind.FIXUP
        if 'reword'.startswith(s):
            return StepKind.REWORD
        if 'index'.startswith(s):
            return StepKind.INDEX
        raise ValueError(f"step kind '{s}' must be one of: pick, fixup, reword, or index")


class Step:
    # pick SHA1... Commit Message Text FOr Helpy Stuff
    kind: StepKind
    commit: Commit

    def __str__(self):
        return f"{self.kind} {self.commit.tree_oid.short()} {self.commit.summary()}"

    def __init__(self, kind: StepKind, commit: Commit):
        self.kind = kind
        self.commit = commit

    @staticmethod
    def parse(repo: Repository, s: str) -> Step:
        parsed = re.match('(?P<command>\S+)\s(?P<hash>\S+)', s)
        if not parsed:
            raise ValueError(f"todo entry '{s}' must follow format <keyword> <sha> <optional message>")
        kind = StepKind.parse(parsed.group('command'))
        commit = repo.getcommit(parsed.group('hash'))
        return Step(kind, commit)

def thingy(repo: Repository, list: List[Commit], index: Optional[Commit]) -> List[Step]:
    s = ""
    for commit in list:
        s += f"{Step(StepKind.PICK, commit)}\n"

    response = run_editor("git-zipfix-todo", s.encode())
    result = []
    for line in response.splitlines():
        if line.isspace():
            continue
        result.append(Step.parse(repo, line.decode(errors='replace').strip()))

    return result
