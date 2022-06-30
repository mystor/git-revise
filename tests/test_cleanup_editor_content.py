from gitrevise.utils import cleanup_editor_content


def test_strip_comments() -> None:
    _do_test(
        (
            b"foo\n"
            b"# bar\n"
        ),
        expected=b"foo\n",
    )


def test_leading_empty_lines() -> None:
    _do_test(
        (
            b"\n"
            b"\n"
            b"foo\n"
            b"# bar\n"
        ),
        expected=(
            b"\n"
            b"\n"
            b"foo\n"
        ),
    )


def test_trailing_empty_lines() -> None:
    _do_test(
        (
            b"foo\n"
            b"# bar\n"
            b"\n"
            b"\n"
        ),
        expected=b"foo\n"
    )


def test_trailing_whitespaces() -> None:
    _do_test(
        (
            b"foo \n"
            b"foo \n"
            b"# bar \n"
        ),
        expected=(
            b"foo \n"
            b"foo\n"
        )
    )


def test_consecutive_emtpy_lines() -> None:
    _do_test(
        (
            b"foo\n"
            b""
            b""
            b"bar\n"
        ),
        expected=(
            b"foo\n"
            b""
            b""
            b"bar\n"
        )
    )


def _do_test(data: bytes, expected: bytes):
    actual = cleanup_editor_content(data, b"#", allow_preceding_whitespace=False)
    assert actual == expected
