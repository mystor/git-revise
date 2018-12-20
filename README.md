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

> **NOTE** This hasn't been tested nor reviewed much yet. Use my personal
> scripts at your own risk :-).

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

## Performance

With large repositories such as mozilla-central, git-zipfix is often
significantly faster incremental targeted changes, due to not needing to
update either the index or working directory during rebases.

I did a simple test, applying a single-line change to a commit 11 patches up
the stack. The following are my extremely non-scientific time measurements:

| Command                      | Real Time |
| ---------------------------- | --------- |
| `git rebase -i --autosquash` | 16.931s   |
| `git zipfix`                 | 0.541s    |

The following are the commands I ran:

```bash
# Apply changes with git rebase -i --autosquash
$ git reset 6fceb7da316d && git add .
$ time bash -c 'TARGET=14f1c85bf60d; git commit --fixup=$TARGET; EDITOR=true git rebase -i --autosquash $TARGET~'
[mybranch 286c7cff7330] fixup! Bug ...
 1 file changed, 1 insertion(+)
Successfully rebased and updated refs/heads/mybranch.

real    0m16.931s
user    0m15.289s
sys     0m3.579s

# Apply changes with git zipfix
$ git reset 6fceb7da316d && git add .
$ time git zipfix 14f1c85bf60d
Applying staged changes to '14f1c85bf60d'
Reparenting commit 1/10: 23a741dff61496ba929d979942e0ab590db1fece
Reparenting commit 2/10: 8376b15993e506883a54c5d1b75becd083224eb7
<snip>
Reparenting commit 10/10: 6fceb7da316dbf4fedb5360ed09bd7b03f28bc6a
Updating HEAD (6fceb7da316dbf4fedb5360ed09bd7b03f28bc6a => 996ec1a718bad36edab0e7c1129d698d29cdcdfc)

real    0m0.541s
user    0m0.354s
sys     0m0.150s
```

### How is it faster?

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
