# Changelog

## vNext

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
