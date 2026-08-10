"""test_report.py — unit tests for format_json_report."""
import json

from wordcount.report import format_json_report


def test_round_trips_as_json():
    sample = {"files_counted": 2, "files_skipped": 1, "total_words": 25}
    formatted = format_json_report(sample)
    assert json.loads(formatted) == sample


def test_pretty_printed_with_sorted_keys():
    sample = {"z": 1, "a": 2}
    formatted = format_json_report(sample)
    a_pos = formatted.index('"a"')
    z_pos = formatted.index('"z"')
    assert a_pos < z_pos


def test_ends_with_newline():
    sample = {"key": "value"}
    formatted = format_json_report(sample)
    assert formatted.endswith("\n")
