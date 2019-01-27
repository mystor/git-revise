Performance
===========

.. note::
  These numbers are from an earlier version, and may not reflect
  the current state of `git-revise`.

With large repositories such as ``mozilla-central``, :command:`git revise` is
often significantly faster than :manpage:`git-rebase(1)` for incremental, due
to not needing to update the index or working directory during rebases.

I did a simple test, applying a single-line change to a commit 11 patches up
the stack. The following are my extremely non-scientific time measurements:

==============================  =========
Command                         Real Time
==============================  =========
``git rebase -i --autosquash``   16.931s
``git revise``                   0.541s
==============================  =========

The following are the commands I ran:

.. code-block:: bash

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


How is it faster?
-----------------

.. rubric:: In-Memory Cache

To avoid spawning unnecessary subprocesses and hitting disk too frequently,
:command:`git revise` uses an in-memory cache of objects in the ODB which it
has already seen.

Intermediate git trees, blobs, and commits created during processing are helds
exclusively in-memory, and only persisted when necessary.


.. rubric:: Custom Merge Algorithm

A custom implementation of the merge algorithm is used which directly merges
trees rather than using the index. This ends up being faster on large
repositories, as only the subset of modified files and directories need to be
examined when merging.

.. note::
  Currently this algorithm is incapable of handling copy and rename
  operations correctly, instead treating them as file creation and deletion
  actions. This may be resolveable in the future.

.. rubric:: Avoiding Index & Working Directory

The working directory and index are never examined or updated during the
rebasing process, avoiding disk I/O and invalidating existing builds.
