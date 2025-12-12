"""Unit tests for sanitizer_matcher utility."""

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from armadillo.utils.sanitizer_matcher import (
    get_file_timestamp,
    match_sanitizer_to_tests,
    match_all_sanitizers,
    get_sanitizer_summary,
    SanitizerMatch,
)


class TestGetFileTimestamp:
    """Tests for get_file_timestamp function."""

    def test_get_timestamp_for_existing_file(self, tmp_path):
        """Should return datetime for existing file."""
        test_file = tmp_path / "test.log"
        test_file.write_text("test content")

        timestamp = get_file_timestamp(test_file)

        assert timestamp is not None
        assert isinstance(timestamp, datetime)
        # Timestamp should be recent (within last minute)
        assert (datetime.now() - timestamp).total_seconds() < 60

    def test_get_timestamp_for_nonexistent_file(self, tmp_path):
        """Should return None for non-existent file."""
        test_file = tmp_path / "nonexistent.log"

        timestamp = get_file_timestamp(test_file)

        assert timestamp is None

    def test_get_timestamp_handles_permission_error(self, tmp_path, monkeypatch):
        """Should return None if file is not accessible."""
        test_file = tmp_path / "test.log"
        test_file.write_text("test content")

        # Mock getmtime to raise OSError
        def mock_getmtime(path):
            raise OSError("Permission denied")

        monkeypatch.setattr(os.path, "getmtime", mock_getmtime)

        timestamp = get_file_timestamp(test_file)

        assert timestamp is None


class TestMatchSanitizerToTests:
    """Tests for match_sanitizer_to_tests function."""

    def test_match_high_confidence_within_test_window(self, tmp_path):
        """Should return high confidence match when file timestamp is within test execution window."""
        # Create test file
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        # Create test data - file written during test execution
        test_start = datetime.now() - timedelta(seconds=10)
        test_end = datetime.now() - timedelta(seconds=5)

        # Touch file to set timestamp within window
        file_time = test_start + timedelta(seconds=2.5)
        os.utime(san_file, (file_time.timestamp(), file_time.timestamp()))

        tests = [
            {
                "id": "test_something.py::test_case",
                "started_at": test_start.isoformat(),
                "finished_at": test_end.isoformat(),
            }
        ]

        match = match_sanitizer_to_tests(san_file, tests)

        assert match is not None
        assert match.test_nodeid == "test_something.py::test_case"
        assert match.confidence == "high"
        assert match.sanitizer_file == san_file
        assert "within test execution window" in match.reason

    def test_match_low_confidence_shortly_after_test(self, tmp_path):
        """Should return low confidence match when file is written shortly after test."""
        # Create test file
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        # Create test data - file written 2 seconds after test
        test_start = datetime.now() - timedelta(seconds=10)
        test_end = datetime.now() - timedelta(seconds=5)

        # Touch file to set timestamp after test end
        file_time = test_end + timedelta(seconds=2)
        os.utime(san_file, (file_time.timestamp(), file_time.timestamp()))

        tests = [
            {
                "id": "test_something.py::test_case",
                "started_at": test_start.isoformat(),
                "finished_at": test_end.isoformat(),
            }
        ]

        match = match_sanitizer_to_tests(san_file, tests, tolerance_seconds=5.0)

        assert match is not None
        assert match.test_nodeid == "test_something.py::test_case"
        assert match.confidence == "low"
        assert "after test end" in match.reason
        assert "async write" in match.reason

    def test_no_match_when_file_too_late(self, tmp_path):
        """Should return None when file is written too long after test."""
        # Create test file
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        # Create test data - file written 10 seconds after test (beyond tolerance)
        test_start = datetime.now() - timedelta(seconds=20)
        test_end = datetime.now() - timedelta(seconds=15)

        # Touch file to set timestamp way after test end
        file_time = test_end + timedelta(seconds=10)
        os.utime(san_file, (file_time.timestamp(), file_time.timestamp()))

        tests = [
            {
                "id": "test_something.py::test_case",
                "started_at": test_start.isoformat(),
                "finished_at": test_end.isoformat(),
            }
        ]

        match = match_sanitizer_to_tests(san_file, tests, tolerance_seconds=5.0)

        assert match is None

    def test_no_match_when_file_before_test(self, tmp_path):
        """Should return None when file is written before test started."""
        # Create test file
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        # Create test data - file written before test started
        test_start = datetime.now() - timedelta(seconds=10)
        test_end = datetime.now() - timedelta(seconds=5)

        # Touch file to set timestamp before test start
        file_time = test_start - timedelta(seconds=5)
        os.utime(san_file, (file_time.timestamp(), file_time.timestamp()))

        tests = [
            {
                "id": "test_something.py::test_case",
                "started_at": test_start.isoformat(),
                "finished_at": test_end.isoformat(),
            }
        ]

        match = match_sanitizer_to_tests(san_file, tests)

        assert match is None

    def test_match_correct_test_among_many(self, tmp_path):
        """Should match to correct test when multiple tests exist."""
        # Create test file
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        # Create multiple tests at different times
        base_time = datetime.now() - timedelta(seconds=30)

        tests = [
            {
                "id": "test_file.py::test_one",
                "started_at": (base_time + timedelta(seconds=0)).isoformat(),
                "finished_at": (base_time + timedelta(seconds=5)).isoformat(),
            },
            {
                "id": "test_file.py::test_two",
                "started_at": (base_time + timedelta(seconds=10)).isoformat(),
                "finished_at": (base_time + timedelta(seconds=15)).isoformat(),
            },
            {
                "id": "test_file.py::test_three",
                "started_at": (base_time + timedelta(seconds=20)).isoformat(),
                "finished_at": (base_time + timedelta(seconds=25)).isoformat(),
            },
        ]

        # File written during test_two
        file_time = base_time + timedelta(seconds=12)
        os.utime(san_file, (file_time.timestamp(), file_time.timestamp()))

        match = match_sanitizer_to_tests(san_file, tests)

        assert match is not None
        assert match.test_nodeid == "test_file.py::test_two"
        assert match.confidence == "high"

    def test_handles_tests_without_timestamps(self, tmp_path):
        """Should handle tests that don't have started_at/finished_at."""
        # Create test file
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        tests = [
            {"id": "test_file.py::test_one"},  # No timestamps
            {"id": "test_file.py::test_two", "started_at": None, "finished_at": None},
        ]

        match = match_sanitizer_to_tests(san_file, tests)

        assert match is None

    def test_custom_tolerance_seconds(self, tmp_path):
        """Should respect custom tolerance_seconds parameter."""
        # Create test file
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        test_start = datetime.now() - timedelta(seconds=20)
        test_end = datetime.now() - timedelta(seconds=15)

        # File written 8 seconds after test end
        file_time = test_end + timedelta(seconds=8)
        os.utime(san_file, (file_time.timestamp(), file_time.timestamp()))

        tests = [
            {
                "id": "test_something.py::test_case",
                "started_at": test_start.isoformat(),
                "finished_at": test_end.isoformat(),
            }
        ]

        # Should not match with default tolerance (5 seconds)
        match_default = match_sanitizer_to_tests(san_file, tests, tolerance_seconds=5.0)
        assert match_default is None

        # Should match with higher tolerance (10 seconds)
        match_higher = match_sanitizer_to_tests(san_file, tests, tolerance_seconds=10.0)
        assert match_higher is not None
        assert match_higher.confidence == "low"


class TestMatchAllSanitizers:
    """Tests for match_all_sanitizers function."""

    def test_match_multiple_sanitizers_to_tests(self, tmp_path):
        """Should match multiple sanitizer files to appropriate tests."""
        # Create sanitizer files
        asan_file = tmp_path / "asan.log"
        asan_file.write_text("AddressSanitizer error")

        tsan_file = tmp_path / "tsan.log"
        tsan_file.write_text("ThreadSanitizer error")

        # Set up times
        base_time = datetime.now() - timedelta(seconds=30)

        # Test 1 execution: 0-5 seconds
        test1_start = base_time
        test1_end = base_time + timedelta(seconds=5)

        # Test 2 execution: 10-15 seconds
        test2_start = base_time + timedelta(seconds=10)
        test2_end = base_time + timedelta(seconds=15)

        # ASAN file written during test 1
        os.utime(asan_file, ((test1_start + timedelta(seconds=2)).timestamp(),
                              (test1_start + timedelta(seconds=2)).timestamp()))

        # TSAN file written during test 2
        os.utime(tsan_file, ((test2_start + timedelta(seconds=2)).timestamp(),
                              (test2_start + timedelta(seconds=2)).timestamp()))

        sanitizer_files = {
            "server_1": [asan_file, tsan_file]
        }

        test_suites = {
            "suite1": {
                "tests": {
                    "test_one": {
                        "id": "test_file.py::test_one",
                        "started_at": test1_start.isoformat(),
                        "finished_at": test1_end.isoformat(),
                    },
                    "test_two": {
                        "id": "test_file.py::test_two",
                        "started_at": test2_start.isoformat(),
                        "finished_at": test2_end.isoformat(),
                    },
                }
            }
        }

        matches = match_all_sanitizers(sanitizer_files, test_suites, min_confidence="high")

        assert len(matches) == 2
        assert "test_file.py::test_one" in matches
        assert "test_file.py::test_two" in matches

        # Check test_one has ASAN match
        test_one_matches = matches["test_file.py::test_one"]
        assert len(test_one_matches) == 1
        assert test_one_matches[0][0] == asan_file
        assert test_one_matches[0][1] == "high"

        # Check test_two has TSAN match
        test_two_matches = matches["test_file.py::test_two"]
        assert len(test_two_matches) == 1
        assert test_two_matches[0][0] == tsan_file
        assert test_two_matches[0][1] == "high"

    def test_min_confidence_filter(self, tmp_path):
        """Should filter matches based on min_confidence parameter."""
        # Create sanitizer file
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        base_time = datetime.now() - timedelta(seconds=20)
        test_start = base_time
        test_end = base_time + timedelta(seconds=5)

        # File written 2 seconds after test (low confidence)
        file_time = test_end + timedelta(seconds=2)
        os.utime(san_file, (file_time.timestamp(), file_time.timestamp()))

        sanitizer_files = {"server_1": [san_file]}

        test_suites = {
            "suite1": {
                "tests": {
                    "test_one": {
                        "id": "test_file.py::test_one",
                        "started_at": test_start.isoformat(),
                        "finished_at": test_end.isoformat(),
                    }
                }
            }
        }

        # Should not match with min_confidence="high"
        matches_high = match_all_sanitizers(sanitizer_files, test_suites, min_confidence="high")
        assert len(matches_high) == 0

        # Should match with min_confidence="low"
        matches_low = match_all_sanitizers(sanitizer_files, test_suites, min_confidence="low")
        assert len(matches_low) == 1
        assert "test_file.py::test_one" in matches_low

    def test_handles_multiple_servers(self, tmp_path):
        """Should handle sanitizer files from multiple servers."""
        # Create files for different servers
        server1_file = tmp_path / "server1_asan.log"
        server1_file.write_text("AddressSanitizer error")

        server2_file = tmp_path / "server2_tsan.log"
        server2_file.write_text("ThreadSanitizer error")

        base_time = datetime.now() - timedelta(seconds=20)
        test_start = base_time
        test_end = base_time + timedelta(seconds=5)

        # Both files written during test
        os.utime(server1_file, ((test_start + timedelta(seconds=2)).timestamp(),
                                 (test_start + timedelta(seconds=2)).timestamp()))
        os.utime(server2_file, ((test_start + timedelta(seconds=3)).timestamp(),
                                 (test_start + timedelta(seconds=3)).timestamp()))

        sanitizer_files = {
            "server_1": [server1_file],
            "server_2": [server2_file],
        }

        test_suites = {
            "suite1": {
                "tests": {
                    "test_one": {
                        "id": "test_file.py::test_one",
                        "started_at": test_start.isoformat(),
                        "finished_at": test_end.isoformat(),
                    }
                }
            }
        }

        matches = match_all_sanitizers(sanitizer_files, test_suites, min_confidence="high")

        assert len(matches) == 1
        test_matches = matches["test_file.py::test_one"]
        assert len(test_matches) == 2  # Both files matched to same test

    def test_empty_sanitizer_files(self, tmp_path):
        """Should handle empty sanitizer_files dict."""
        test_suites = {
            "suite1": {
                "tests": {
                    "test_one": {
                        "id": "test_file.py::test_one",
                        "started_at": datetime.now().isoformat(),
                        "finished_at": datetime.now().isoformat(),
                    }
                }
            }
        }

        matches = match_all_sanitizers({}, test_suites, min_confidence="high")

        assert len(matches) == 0

    def test_empty_test_suites(self, tmp_path):
        """Should handle empty test_suites dict."""
        san_file = tmp_path / "asan.log"
        san_file.write_text("AddressSanitizer error")

        sanitizer_files = {"server_1": [san_file]}

        matches = match_all_sanitizers(sanitizer_files, {}, min_confidence="high")

        assert len(matches) == 0


class TestGetSanitizerSummary:
    """Tests for get_sanitizer_summary function."""

    def test_summary_with_all_matched(self, tmp_path):
        """Should return correct counts when all sanitizers are matched."""
        file1 = tmp_path / "asan1.log"
        file2 = tmp_path / "asan2.log"
        file1.write_text("error")
        file2.write_text("error")

        sanitizer_files = {
            "server_1": [file1, file2]
        }

        matched_files = {file1, file2}

        summary = get_sanitizer_summary(sanitizer_files, matched_files)

        assert summary["total"] == 2
        assert summary["matched"] == 2
        assert summary["unmatched"] == 0

    def test_summary_with_some_matched(self, tmp_path):
        """Should return correct counts when some sanitizers are matched."""
        file1 = tmp_path / "asan1.log"
        file2 = tmp_path / "asan2.log"
        file3 = tmp_path / "tsan1.log"
        file1.write_text("error")
        file2.write_text("error")
        file3.write_text("error")

        sanitizer_files = {
            "server_1": [file1, file2],
            "server_2": [file3]
        }

        matched_files = {file1, file3}

        summary = get_sanitizer_summary(sanitizer_files, matched_files)

        assert summary["total"] == 3
        assert summary["matched"] == 2
        assert summary["unmatched"] == 1

    def test_summary_with_none_matched(self, tmp_path):
        """Should return correct counts when no sanitizers are matched."""
        file1 = tmp_path / "asan1.log"
        file1.write_text("error")

        sanitizer_files = {"server_1": [file1]}
        matched_files = set()

        summary = get_sanitizer_summary(sanitizer_files, matched_files)

        assert summary["total"] == 1
        assert summary["matched"] == 0
        assert summary["unmatched"] == 1

    def test_summary_with_empty_files(self):
        """Should handle empty sanitizer files."""
        summary = get_sanitizer_summary({}, set())

        assert summary["total"] == 0
        assert summary["matched"] == 0
        assert summary["unmatched"] == 0


class TestSanitizerMatch:
    """Tests for SanitizerMatch dataclass."""

    def test_sanitizer_match_creation(self, tmp_path):
        """Should create SanitizerMatch instance with all fields."""
        san_file = tmp_path / "asan.log"
        san_file.write_text("error")

        test_start = datetime.now()
        test_end = test_start + timedelta(seconds=5)
        file_ts = test_start + timedelta(seconds=2)

        match = SanitizerMatch(
            test_nodeid="test_file.py::test_case",
            sanitizer_file=san_file,
            confidence="high",
            file_timestamp=file_ts,
            test_start=test_start,
            test_end=test_end,
            reason="Test reason"
        )

        assert match.test_nodeid == "test_file.py::test_case"
        assert match.sanitizer_file == san_file
        assert match.confidence == "high"
        assert match.file_timestamp == file_ts
        assert match.test_start == test_start
        assert match.test_end == test_end
        assert match.reason == "Test reason"
