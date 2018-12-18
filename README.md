# git zipfix

git-zipfix is a tool to make it easier and faster to perform modifications on
historical commits within large repositories.

The command `git zipfix $1` is, in effect, a more efficient version of the
following common snippet:

```bash
$ TARGET=$(git rev-parse --validate $1)
$ git commit --fixup=$TARGET
$ EDITOR=true git rebase -i --autosquash $TARGET^
```

> **NOTE** This hasn't been tested much yet. Unfortunately, it currently
> lacks automated testing, which I hope to rectify soon. Probably don't
> depend on this for anything yet.

## Usage

Stage changes, and call git-zipfix to apply them to a commit

```bash
$ git add ...
$ git zipfix HEAD^
```

With the `-e` and `-m` flags, `git zipfix` quickly edits commit messages.

```bash
$ git zipfix -e HEAD^                # Opens an editor for message
$ git zipfix -m "New message" HEAD^  # Takes message from cmdline
```

### Conflicts

When conflicts occur, `git zipfix` will attempt to resolve them
automatically. If it fails, it will either prompt the user for a resolution,
or start the `kdiff3` tool to resolve the conflict. Other difftools are not
currently handled.

### Working Directory Changes

`git zipfix` makes no effort to update the index or working directory after
applying changes, however it will emit a warning if the final state of the
repository after the rebase does not match the initial state.

Differences in state should be easy to spot, as the index and working
directory will still reflect the initial state.

### Merge commits

`git zipfix` makes no attempt to handle merge commits, and will simply error
if they are found within the range of commits which needs to be rewritten.

## How is it faster?

1. To avoid spawning unnecessary subprocesses and hitting disk too
   frequently, `git zipfix` uses an in-memory cache of objects in the ODB
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
