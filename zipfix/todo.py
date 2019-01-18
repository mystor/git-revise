from enum import Enum
from typing import List
from .odb import Commit

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


class Step:
    # pick SHA1... Commit Message Text FOr Helpy Stuff
    kind: StepKind
    commit: Commit

    def __str__(self):
        return f"{self.kind} {self.commit.tree_oid.short()} {self.commit.summary()}"



def thingy(list: List[Commit], include_index: bool) -> List[Step]:
    # Prompt the user
    # Produce list of steps?
    pass
