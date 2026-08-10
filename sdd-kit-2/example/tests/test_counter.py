"""test_counter.py — unit tests for count_file.

Tests the pure function in isolation. No signal emission tested here; that's
test_scanner.py's job.
"""
import os
from pathlib import Path

from wordcount.counter import count_file, SkipReason
from wordcount.types import Counts


FIXTURES = Path(__file__).parent / "fixtures" / "sample_tree"


def test_count_text_file():
    result = count_file(FIXTURES / "hello.txt")
    assert isinstance(result, Counts)
    assert result.words > 0
    assert result.lines > 0
    assert result.bytes > 0


def test_count_nested_text_file():
    result = count_file(FIXTURES / "nested" / "world.md")
    assert isinstance(result, Counts)
    assert result.words > 0


def test_count_binary_file_skipped():
    result = count_file(FIXTURES / "image.png")
    assert result is SkipReason.BINARY_DETECTED


def test_count_known_content():
    # Write a known file to a temp path to lock specific expected counts.
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world\nfoo bar baz\n")
        tmp = Path(f.name)
    try:
        result = count_file(tmp)
        assert isinstance(result, Counts)
        assert result.words == 5
        assert result.lines == 2
        assert result.bytes == 24
        assert result.chars == 24
    finally:
        os.unlink(tmp)
