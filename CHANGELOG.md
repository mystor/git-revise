# Changelog

## vNEXT

* Added support for `git add`'s `--patch` flag (#61)
* Manpage is now installed in `share/man/man1` instead of `man/man1` (#62)
* Which patch failed to apply is now included in the conflict editor (#53)
* Trailing whitespaces are no longer generated for empty comment lines (#50)

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
