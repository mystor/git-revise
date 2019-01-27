# git revise
[![Build Status](https://travis-ci.org/mystor/git-revise.svg?branch=master)](https://travis-ci.org/mystor/git-revise)
[![PyPi](https://img.shields.io/pypi/v/git-revise.svg)](https://pypi.org/project/git-revise)
[![Documentation Status](https://readthedocs.org/projects/git-revise/badge/?version=latest)](https://git-revise.readthedocs.io/en/latest/?badge=latest)


`git revise` is a `git` subcommand to efficiently update, split, and rearrange
commits. It is heavily inspired by `git rebase`, however tries to be more
efficient and ergonomic for patch-stack oriented workflows.

By default, `git revise` will apply staged changes to a target commit,
updating `HEAD` to point at the revised history. It also supports splitting
commits, and rewording commit messages.

Unlike `git-rebase`, `git revise` avoids modifying working directory and
index state, performing all merges in-memory, and only writing them when
necessary. This allows it to be significantly faster on large codebases, and
avoid invalidating builds.

## Documentation

Documentation, including usage and examples, is hosted on [Read the Docs].

[Read the Docs]: https://git-revise.readthedocs.io/en/latest

## Performance

> **NOTE**: These numbers are from an earlier version, and may not reflect
> the current state of `git-revise`.

With large repositories such as mozilla-central, `git-revise` is often
significantly faster incremental targeted changes, due to not needing to
update either the index or working directory during rebases.

I did a simple test, applying a single-line change to a commit 11 patches up
the stack. The following are my extremely non-scientific time measurements:

| Command                      | Real Time |
| ---------------------------- | --------- |
| `git rebase -i --autosquash` | 16.931s   |
| `git revise`                 | 0.541s    |

The following are the commands I ran:

```bash
# Apply changes with git rebase -i --autosquash
$ git reset 6fceb7da316d && git add .
$ time bash -c 'TARGET=14f1c85bf60d; git commit --fixup=$TARGET; EDITOR=true git rebase -i --autosquash $TARGET~'
<snip>

real    0m16.931s
user    0m15.289s
sys     0m3.579s

# Apply changes with git revise
$ git reset 6fceb7da316d && git add .
$ time git revise 14f1c85bf60d
<snip>

real    0m0.541s
user    0m0.354s
sys     0m0.150s
```

### How is it faster?

1. To avoid spawning unnecessary subprocesses and hitting disk too
   frequently, `git revise` uses an in-memory cache of objects in the ODB
   which it has already seen.

2. Intermediate git trees, blobs, and commits created during processing are
   helds exclusively in-memory, and only persisted when necessary.

3. A custom implementation of the merge algorithm is used which directly
   merges trees rather than using the index. This ends up being faster on
   large repositories, as only the subset of modified files and directories
   need to be examined when merging.

   Currently this algorithm is incapable of handling copy and rename
   operations correctly, instead treating them as file creation and deletion
   actions. This may be resolveable in the future.

4. The working directory is never examined or updated during the rebasing
   process, avoiding disk I/O and invalidating existing builds.
