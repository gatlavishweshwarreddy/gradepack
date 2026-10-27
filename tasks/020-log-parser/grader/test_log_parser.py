import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from parser import parse_log
from filter import filter_level
from stats import duration_seconds
import pytest


SIMPLE_LOG = [
    "10:00:00 INFO  started",
    "10:00:05 DEBUG tick",
    "10:00:30 ERROR boom",
    "10:01:00 INFO  done",
]

MIDNIGHT_LOG = [
    "23:59:50 INFO  winding down",
    "23:59:55 DEBUG final tick",
    "00:00:05 INFO  new day",
    "00:00:20 ERROR late error",
]


def test_parse_returns_correct_count():
    entries = parse_log(SIMPLE_LOG)
    assert len(entries) == 4


def test_parse_first_entry_time():
    entries = parse_log(SIMPLE_LOG)
    import datetime
    assert entries[0].time.hour == 10
    assert entries[0].time.minute == 0
    assert entries[0].time.second == 0


def test_parse_first_entry_level():
    entries = parse_log(SIMPLE_LOG)
    assert entries[0].level == "INFO"


def test_duration_simple():
    entries = parse_log(SIMPLE_LOG)
    assert duration_seconds(entries) == 60.0


def test_duration_midnight_span():
    entries = parse_log(MIDNIGHT_LOG)
    result = duration_seconds(entries)
    assert result == 30.0, f"Expected 30.0 seconds, got {result}"


def test_duration_single_entry():
    entries = parse_log(["10:00:00 INFO only"])
    assert duration_seconds(entries) == 0


def test_filter_level_keeps_matching():
    entries = parse_log(SIMPLE_LOG)
    info = filter_level(entries, "INFO")
    assert len(info) == 2
    assert all(e.level == "INFO" for e in info)


def test_filter_level_removes_others():
    entries = parse_log(SIMPLE_LOG)
    errs = filter_level(entries, "ERROR")
    assert len(errs) == 1
    assert errs[0].message.strip() == "boom"


def test_filter_level_empty_result():
    entries = parse_log(SIMPLE_LOG)
    assert filter_level(entries, "WARNING") == []
