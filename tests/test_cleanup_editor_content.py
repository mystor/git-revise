from typing import Optional

from gitrevise.utils import (
    GIT_SCISSOR_LINE_WITHOUT_COMMENT_CHAR,
    EditorCleanupMode,
    cleanup_editor_content,
)


def test_strip_comments() -> None:
    _do_test(
        b"foo\n# bar\n",
        expected_strip=b"foo\n",
        expected_whitespace=b"foo\n# bar\n",
    )


def test_leading_empty_lines() -> None:
    _do_test(
        b"\n\nfoo\n# bar\n",
        expected_strip=b"foo\n",
        expected_whitespace=b"foo\n# bar\n",
    )


def test_trailing_empty_lines() -> None:
    _do_test(
        b"foo\n# bar\n\n\n",
        expected_strip=b"foo\n",
        expected_whitespace=b"foo\n# bar\n",
    )


def test_trailing_whitespaces() -> None:
    _do_test(
        b"foo \nfoo \n# bar \n",
        expected_strip=b"foo\nfoo\n",
        expected_whitespace=b"foo\nfoo\n# bar\n",
    )


def test_consecutive_emtpy_lines() -> None:
    _do_test(b"foo\nbar\n", expected_strip=b"foo\nbar\n")


def test_scissors() -> None:
    original = f"foo\n# {GIT_SCISSOR_LINE_WITHOUT_COMMENT_CHAR}bar\n".encode()
    _do_test(
        original,
        expected_strip=b"foo\nbar\n",
        expected_whitespace=original,
        expected_scissors=b"foo\n",
    )


def test_force_cut_scissors_in_verbatim_mode() -> None:
    actual = cleanup_editor_content(
        f"foo\n# {GIT_SCISSOR_LINE_WITHOUT_COMMENT_CHAR}bar\n".encode(),
        b"#",
        EditorCleanupMode.VERBATIM,
        force_cut_after_scissors=True,
    )
    assert actual == b"foo\n"


def _do_test(
    data: bytes,
    expected_strip: bytes,
    expected_whitespace: Optional[bytes] = None,
    expected_scissors: Optional[bytes] = None,
) -> None:
    if expected_whitespace is None:
        expected_whitespace = expected_strip
    if expected_scissors is None:
        expected_scissors = expected_whitespace

    actual_strip = cleanup_editor_content(data, b"#", EditorCleanupMode.STRIP)
    actual_verbatim = cleanup_editor_content(data, b"#", EditorCleanupMode.VERBATIM)
    actual_scissors = cleanup_editor_content(data, b"#", EditorCleanupMode.SCISSORS)
    actual_whitespace = cleanup_editor_content(data, b"#", EditorCleanupMode.WHITESPACE)

    assert actual_strip == expected_strip, "default"
    assert actual_verbatim == data, "verbatim"
    assert actual_scissors == expected_scissors, "scissors"
    assert actual_whitespace == expected_whitespace, "whitespace"
