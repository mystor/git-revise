# git revise
[![Build Status](https://travis-ci.org/mystor/git-revise.svg?branch=master)](https://travis-ci.org/mystor/git-revise)
[![PyPi](https://img.shields.io/pypi/v/git-revise.svg)](https://pypi.org/project/git-revise)
[![Documentation Status](https://readthedocs.org/projects/git-revise/badge/?version=latest)](https://git-revise.readthedocs.io/en/latest/?badge=latest)


`git revise` is a `git` subcommand to efficiently update, split, and rearrange
commits. It is heavily inspired by `git rebase`, however it tries to be more
efficient and ergonomic for patch-stack oriented workflows.

By default, `git revise` will apply staged changes to a target commit, then
update `HEAD` to point at the revised history. It also supports splitting
commits and rewording commit messages.

Unlike `git rebase`, `git revise` avoids modifying the working directory or
the index state, performing all merges in-memory and only writing them when
necessary. This allows it to be significantly faster on large codebases and
avoids unnecessarily invalidating builds.

## Install

```sh
$ pip install --user git-revise
```

Various people have also packaged `git revise` for platform-specific package
managers (Thanks!)

#### macOS Homebrew

```sh
$ brew install git-revise
```

#### Fedora

```sh
$ dnf install git-revise
```

## Documentation

Documentation, including usage and examples, is hosted on [Read the Docs].

[Read the Docs]: https://git-revise.readthedocs.io/en/latest

