"""Utilities for matching sanitizer reports to test cases based on timestamps.

This module provides functionality to correlate sanitizer log files with individual
test cases using file modification timestamps and test execution windows.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import os


def calculate_match_confidence(
    sanitizer_timestamp: datetime,
    test_start: datetime,
    test_end: datetime,
    tolerance_seconds: float = 5.0,
) -> str:
    """Calculate match confidence based on timestamps.

    This is the core matching algorithm used by both file-based and
    object-based sanitizer matching.

    Args:
        sanitizer_timestamp: When the sanitizer file was written
        test_start: When the test started
        test_end: When the test finished
        tolerance_seconds: Seconds after test end to consider (for async writes)

    Returns:
        "high" if within test window, "low" if shortly after, "" if no match
    """
    # High confidence: file written during test execution
    if test_start <= sanitizer_timestamp <= test_end:
        return "high"

    # Low confidence: file written shortly after (async write delay)
    time_after = (sanitizer_timestamp - test_end).total_seconds()
    if 0 < time_after <= tolerance_seconds:
        return "low"

    return ""


@dataclass
class SanitizerMatch:
    """Result of matching a sanitizer file to a test case.

    Attributes:
        test_nodeid: Pytest node ID of the matched test
        sanitizer_file: Path to the sanitizer log file
        confidence: Match confidence level ("high" or "low")
        file_timestamp: Modification timestamp of the sanitizer file
        test_start: Test execution start time
        test_end: Test execution end time
        reason: Human-readable explanation of why this match was made
    """

    test_nodeid: str
    sanitizer_file: Path
    confidence: str
    file_timestamp: datetime
    test_start: datetime
    test_end: datetime
    reason: str


def get_file_timestamp(file_path: Path) -> Optional[datetime]:
    """Get modification timestamp of a file.

    Args:
        file_path: Path to the file

    Returns:
        datetime object representing file modification time, or None if unable to read
    """
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.fromtimestamp(mtime)
    except (OSError, ValueError):
        return None


def match_sanitizer_to_tests(
    sanitizer_file: Path, tests: List[Dict], tolerance_seconds: float = 5.0
) -> Optional[SanitizerMatch]:
    """Match a sanitizer file to a test based on timestamps.

    Matching strategy:
    1. High confidence: File timestamp falls within test execution window
    2. Low confidence: File timestamp within tolerance after test end (async write)
    3. No match: File timestamp doesn't correlate with any test

    Args:
        sanitizer_file: Path to sanitizer log file
        tests: List of test dicts with 'started_at', 'finished_at', and 'id' fields
        tolerance_seconds: Seconds after test end to still consider a low-confidence match

    Returns:
        SanitizerMatch if a correlation is found, None otherwise
    """
    file_ts = get_file_timestamp(sanitizer_file)
    if not file_ts:
        return None

    for test in tests:
        if not test.get("started_at") or not test.get("finished_at"):
            continue

        test_start = datetime.fromisoformat(test["started_at"])
        test_end = datetime.fromisoformat(test["finished_at"])

        # Use centralized matching logic
        confidence = calculate_match_confidence(
            file_ts, test_start, test_end, tolerance_seconds
        )

        if confidence == "high":
            return SanitizerMatch(
                test_nodeid=test["id"],
                sanitizer_file=sanitizer_file,
                confidence="high",
                file_timestamp=file_ts,
                test_start=test_start,
                test_end=test_end,
                reason="File timestamp within test execution window",
            )
        elif confidence == "low":
            return SanitizerMatch(
                test_nodeid=test["id"],
                sanitizer_file=sanitizer_file,
                confidence="low",
                file_timestamp=file_ts,
                test_start=test_start,
                test_end=test_end,
                reason=f"File timestamp {(file_ts - test_end).total_seconds():.1f}s after test end (async write)",
            )

    return None


def match_all_sanitizers(
    sanitizer_files: Dict[str, List[Path]],
    test_suites: Dict[str, Dict],
    min_confidence: str = "high",
) -> Dict[str, List[Tuple[Path, str]]]:
    """Match all sanitizer files to tests.

    This function attempts to correlate each sanitizer log file with a specific
    test case based on timestamps. Only matches meeting the minimum confidence
    threshold are returned.

    Args:
        sanitizer_files: Dict mapping server_id to list of sanitizer file paths
        test_suites: Test suite data from ResultCollector (contains test metadata)
        min_confidence: Minimum confidence level to include ("high" or "low")

    Returns:
        Dict mapping test nodeid to list of (file_path, confidence) tuples

    Example:
        >>> matches = match_all_sanitizers(
        ...     {"server-1": [Path("asan.log.arangod.1234")]},
        ...     test_suites,
        ...     min_confidence="high"
        ... )
        >>> # Returns: {"test_file.py::test_function": [(Path("..."), "high")]}
    """
    matches: Dict[str, List[Tuple[Path, str]]] = {}

    # Flatten test suites into list of all tests
    all_tests = []
    for suite_data in test_suites.values():
        for test_name, test_data in suite_data.get("tests", {}).items():
            all_tests.append(test_data)

    # Try to match each sanitizer file
    for server_id, files in sanitizer_files.items():
        for san_file in files:
            match = match_sanitizer_to_tests(san_file, all_tests)

            if match and (min_confidence == "low" or match.confidence == "high"):
                if match.test_nodeid not in matches:
                    matches[match.test_nodeid] = []
                matches[match.test_nodeid].append((san_file, match.confidence))

    return matches


def get_sanitizer_summary(
    sanitizer_files: Dict[str, List[Path]], matched_files: List[Path]
) -> Dict[str, int]:
    """Get summary statistics about sanitizer files.

    Args:
        sanitizer_files: All sanitizer files organized by server_id
        matched_files: List of files that were successfully matched to tests

    Returns:
        Dict with 'total', 'matched', and 'unmatched' counts
    """
    all_files = []
    for files in sanitizer_files.values():
        all_files.extend(files)

    matched_set = set(matched_files)

    return {
        "total": len(all_files),
        "matched": len(matched_set),
        "unmatched": len(all_files) - len(matched_set),
    }
