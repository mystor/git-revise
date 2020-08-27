# Changelog

## vNEXT

* Add support for `git-rerere`, to record and replay conflict resolutions (#75)
* Fix autosquash order of multiple fixup commits with the same target (#72)
* Use `GIT_SEQUENCE_EDITOR` instead of `SEQUENCE_EDITOR` (#71)
* Fix handling of multiline commit subjects (#86)
* Add support for `commit.gpgSign` (#46)

## v0.6.0

* Fixed handling of fixup-of-fixup commits (#58)
* Added support for `git add`'s `--patch` flag (#61)
* Manpage is now installed in `share/man/man1` instead of `man/man1` (#62)
* Which patch failed to apply is now included in the conflict editor (#53)
* Trailing whitespaces are no longer generated for empty comment lines (#50)
* Use `sequence.editor` when editing `revise-todo` (#60)

## v0.5.1

* Support non-ASCII branchnames. (#48)
* LICENSE included in PyPi package. (#44)

## v0.5.0

* Invoke `GIT_EDITOR` correctly when it includes quotes.
* Use `sh` instead of `bash` to run `GIT_EDITOR`.
* Added support for the `core.commentChar` config option.
* Added the `revise.autoSquash` config option to imply `--autosquash` by
  default.
* Added support for unambiguous abbreviated refs.

## v0.4.2

* Fixes a bug where the tempdir path is set incorrectly when run from a
  subdirectory.

## v0.4.1

* Improved the performance and UX for the `cut` command.

## v0.4.0

* Support for combining `--interactive` and `--edit` commands to perform bulk
  commit message editing during interactive mode.
* No longer eagerly parses author/committer signatures, avoiding crashes when
  encountering broken signatures.
