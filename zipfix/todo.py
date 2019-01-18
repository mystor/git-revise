from enum import Enum

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
    thing: Thing
    commit: Commit



def thingy(List[Commit], include_index: bool) -> list[Step]:
    # Prompt the user
    # Produce list of steps?
    ...
