"""

"""

from typing import Union
from enum import Enum

from .odb import Signature, Commit


class Index(object):
    # XXX(nika): Handle different indexes
    __slots__ = ()


class Action(Enum):
    COMMIT = 'commit'
    AMEND = 'amend'


class Change(object):
    __slots__ = ('action', 'author', 'message', 'source')

    def __init__(self, action: Action, author: Signature,
                 message: bytes, source: Union[Commit, Index]):
        self.action = action
        self.author = author
        self.message = message
        self.source = source
