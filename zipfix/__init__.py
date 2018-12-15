"""
"""

from argparse import ArgumentParser
from .odb import Commit


def arg_parser():
    parser = ArgumentParser('git-change-edit',
                            description='Efficiently edit historical changes')
    parser.add_argument('-r', '--ref', help='Reference to update', default='HEAD')
    parser.add_argument('revspec', help='Range or single commit to replace')
    parser.add_argument('-c', '--command', action='append', help='Provide commands at commandline rather than through stdin')
    return parser


def main(argv):
    matches = arg_parser().parse_args(args=argv)
    print(matches)



    a = Commit.get('HEAD')
    print(a)
    print(a.raw_hash())
    print(a.raw_hash_call())
    print(a.raw_hash_many())

    import timeit
    number = 1000
    print(timeit.timeit('a.raw_hash()', globals=dict(a=a), number=number))
    print(timeit.timeit('a.raw_hash_call()', globals=dict(a=a), number=number))
    print(timeit.timeit('a.raw_hash_many()', globals=dict(a=a), number=number))

    b = Commit.get('HEAD')
    print(b)

    print(b)
    print(b.tree())
    for entry in b.tree().entries:
        print(entry)
        print(entry.obj())

    # c = Commit.get('0deedf7')
    # print(c)
    # print(c.tree())
    # for entry in c.tree().entries:
    #     print(entry)
    #     print(entry.obj())

