"""Tests for result collection and processing."""

import pytest
import time
from pathlib import Path
from unittest.mock import patch, mock_open

from armadillo.results.collector import (
    ResultCollector, get_result_collector, record_test_result,
    finalize_results, export_results
)
from armadillo.core.types import TestResult, TestSuiteResults, TestOutcome
from armadillo.core.errors import ResultProcessingError


class TestResultCollector:
    """Test ResultCollector class."""

    def test_result_collector_creation(self):
        """Test ResultCollector creation."""
        collector = ResultCollector()

        assert len(collector.tests) == 0
        assert collector.start_time > 0
        assert len(collector.metadata) == 0
        assert collector._finalized is False

    def test_add_test_result(self):
        """Test adding individual test results."""
        collector = ResultCollector()

        result = TestResult("test_example", TestOutcome.PASSED, 1.5)
        collector.add_test_result(result)

        assert len(collector.tests) == 1
        assert collector.tests[0] == result

    def test_add_multiple_test_results(self):
        """Test adding multiple test results."""
        collector = ResultCollector()

        results = [
            TestResult("test1", TestOutcome.PASSED, 1.0),
            TestResult("test2", TestOutcome.FAILED, 2.0),
            TestResult("test3", TestOutcome.SKIPPED, 0.0)
        ]

        for result in results:
            collector.add_test_result(result)

        assert len(collector.tests) == 3
        assert collector.tests == results

    def test_record_test_direct(self):
        """Test recording test result directly."""
        collector = ResultCollector()

        collector.record_test(
            name="test_direct",
            outcome=TestOutcome.FAILED,
            duration=2.5,
            setup_duration=0.1,
            teardown_duration=0.05,
            failure_message="Assertion failed"
        )

        assert len(collector.tests) == 1
        result = collector.tests[0]
        assert result.name == "test_direct"
        assert result.outcome == TestOutcome.FAILED
        assert result.duration == 2.5
        assert result.setup_duration == 0.1
        assert result.teardown_duration == 0.05
        assert result.failure_message == "Assertion failed"

    def test_set_metadata(self):
        """Test setting metadata."""
        collector = ResultCollector()

        collector.set_metadata(framework="armadillo", version="1.0.0")
        collector.set_metadata(additional="info")

        assert collector.metadata["framework"] == "armadillo"
        assert collector.metadata["version"] == "1.0.0"
        assert collector.metadata["additional"] == "info"

    def test_finalize_results(self):
        """Test finalizing results."""
        collector = ResultCollector()
        start_time = collector.start_time

        # Add some test results
        collector.add_test_result(TestResult("test1", TestOutcome.PASSED, 1.0))
        collector.add_test_result(TestResult("test2", TestOutcome.FAILED, 2.0))
        collector.add_test_result(TestResult("test3", TestOutcome.SKIPPED, 0.5))
        collector.set_metadata(framework="test")

        # Wait a bit to ensure duration calculation
        time.sleep(0.01)

        results = collector.finalize_results()

        assert isinstance(results, TestSuiteResults)
        assert len(results.tests) == 3
        assert results.total_duration > 0
        assert results.summary["total"] == 3
        assert results.summary["passed"] == 1
        assert results.summary["failed"] == 1
        assert results.summary["skipped"] == 1
        assert "start_time" in results.metadata
        assert "end_time" in results.metadata
        assert results.metadata["framework"] == "test"

        # Should be marked as finalized
        assert collector._finalized is True

    def test_finalize_results_twice_error(self):
        """Test that finalizing twice raises error."""
        collector = ResultCollector()

        collector.finalize_results()

        with pytest.raises(ResultProcessingError, match="already finalized"):
            collector.finalize_results()

    def test_add_result_after_finalize_error(self):
        """Test that adding results after finalize raises error."""
        collector = ResultCollector()

        collector.finalize_results()

        with pytest.raises(ResultProcessingError, match="Cannot add results after finalization"):
            collector.add_test_result(TestResult("late_test", TestOutcome.PASSED, 1.0))

    def test_calculate_summary(self):
        """Test summary calculation."""
        collector = ResultCollector()

        # Add results with different outcomes
        outcomes = [
            TestOutcome.PASSED, TestOutcome.PASSED,
            TestOutcome.FAILED, TestOutcome.ERROR,
            TestOutcome.SKIPPED, TestOutcome.TIMEOUT,
            TestOutcome.CRASHED
        ]

        for i, outcome in enumerate(outcomes):
            collector.add_test_result(TestResult(f"test_{i}", outcome, 1.0))

        summary = collector._calculate_summary()

        assert summary["total"] == 7
        assert summary["passed"] == 2
        assert summary["failed"] == 1
        assert summary["error"] == 1
        assert summary["skipped"] == 1
        assert summary["timeout"] == 1
        assert summary["crashed"] == 1

    def test_export_results_json(self, temp_dir):
        """Test exporting results as JSON."""
        collector = ResultCollector()

        # Add test data
        collector.add_test_result(TestResult("test1", TestOutcome.PASSED, 1.5))
        collector.add_test_result(TestResult("test2", TestOutcome.FAILED, 2.0,
                                           failure_message="Test failed"))

        exported_files = collector.export_results(["json"], temp_dir)

        assert "json" in exported_files
        json_file = exported_files["json"]
        assert json_file.exists()
        assert json_file.name == "UNITTEST_RESULT.json"

        # Verify JSON content
        import json as json_module
        with open(json_file) as f:
            data = json_module.load(f)

        assert "framework_version" in data
        assert "tests" in data
        assert "meta" in data
        assert len(data["tests"]) == 2

    def test_export_results_junit(self, temp_dir):
        """Test exporting results as JUnit XML."""
        collector = ResultCollector()

        # Add test data
        collector.add_test_result(TestResult("test_suite::test_passed", TestOutcome.PASSED, 1.0))
        collector.add_test_result(TestResult("test_suite::test_failed", TestOutcome.FAILED, 2.0,
                                           failure_message="Assertion error"))
        collector.add_test_result(TestResult("test_suite::test_error", TestOutcome.ERROR, 1.5,
                                           error_message="Runtime error"))
        collector.add_test_result(TestResult("test_suite::test_skipped", TestOutcome.SKIPPED, 0.0))

        exported_files = collector.export_results(["junit"], temp_dir)

        assert "junit" in exported_files
        junit_file = exported_files["junit"]
        assert junit_file.exists()
        assert junit_file.name == "junit.xml"

        # Verify XML structure
        content = junit_file.read_text()
        assert '<testsuite' in content
        assert '<testcase' in content
        assert '<failure' in content
        assert '<error' in content
        assert '<skipped' in content

    def test_export_results_multiple_formats(self, temp_dir):
        """Test exporting results in multiple formats."""
        collector = ResultCollector()

        collector.add_test_result(TestResult("test1", TestOutcome.PASSED, 1.0))

        exported_files = collector.export_results(["json", "junit"], temp_dir)

        assert len(exported_files) == 2
        assert "json" in exported_files
        assert "junit" in exported_files
        assert exported_files["json"].exists()
        assert exported_files["junit"].exists()

    def test_export_results_unknown_format(self, temp_dir):
        """Test exporting with unknown format."""
        collector = ResultCollector()

        collector.add_test_result(TestResult("test1", TestOutcome.PASSED, 1.0))

        exported_files = collector.export_results(["unknown"], temp_dir)

        # Should skip unknown format and return empty dict
        assert len(exported_files) == 0

    def test_export_results_creates_output_dir(self, temp_dir):
        """Test that export creates output directory if it doesn't exist."""
        collector = ResultCollector()

        collector.add_test_result(TestResult("test1", TestOutcome.PASSED, 1.0))

        output_dir = temp_dir / "new_output_dir"
        exported_files = collector.export_results(["json"], output_dir)

        assert output_dir.exists()
        assert "json" in exported_files


class TestGlobalResultFunctions:
    """Test global result collection functions."""

    def test_get_result_collector_singleton(self):
        """Test get_result_collector returns singleton."""
        collector1 = get_result_collector()
        collector2 = get_result_collector()

        assert collector1 is collector2

    def test_record_test_result_function(self):
        """Test global record_test_result function."""
        # Reset global collector
        import armadillo.results.collector
        armadillo.results.collector._result_collector = None

        record_test_result("global_test", TestOutcome.PASSED, 1.0, setup_duration=0.1)

        collector = get_result_collector()
        assert len(collector.tests) == 1

        result = collector.tests[0]
        assert result.name == "global_test"
        assert result.outcome == TestOutcome.PASSED
        assert result.duration == 1.0
        assert result.setup_duration == 0.1

    def test_finalize_results_function(self):
        """Test global finalize_results function."""
        # Reset and populate global collector
        import armadillo.results.collector
        armadillo.results.collector._result_collector = ResultCollector()

        record_test_result("test1", TestOutcome.PASSED, 1.0)
        record_test_result("test2", TestOutcome.FAILED, 2.0)

        results = finalize_results()

        assert isinstance(results, TestSuiteResults)
        assert len(results.tests) == 2

    def test_export_results_function(self, temp_dir):
        """Test global export_results function."""
        # Reset and populate global collector
        import armadillo.results.collector
        armadillo.results.collector._result_collector = ResultCollector()

        record_test_result("test1", TestOutcome.PASSED, 1.0)

        exported_files = export_results(["json"], temp_dir)

        assert "json" in exported_files
        assert exported_files["json"].exists()


class TestResultCollectorEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_result_collection(self, temp_dir):
        """Test handling empty result collection."""
        collector = ResultCollector()

        results = collector.finalize_results()

        assert len(results.tests) == 0
        assert results.total_duration > 0  # Should still have elapsed time
        assert results.summary["total"] == 0

        # Should still be able to export
        exported_files = collector.export_results(["json"], temp_dir)
        assert "json" in exported_files

    def test_very_short_duration_tests(self):
        """Test handling tests with very short durations."""
        collector = ResultCollector()

        collector.add_test_result(TestResult("fast_test", TestOutcome.PASSED, 0.001))
        collector.add_test_result(TestResult("instant_test", TestOutcome.PASSED, 0.0))

        results = collector.finalize_results()

        assert results.summary["total"] == 2
        assert results.summary["passed"] == 2

    def test_test_with_all_optional_fields(self):
        """Test test result with all optional fields populated."""
        collector = ResultCollector()

        crash_info = {"signal": 11, "backtrace": "..."}

        collector.record_test(
            name="complex_test",
            outcome=TestOutcome.CRASHED,
            duration=5.0,
            setup_duration=1.0,
            teardown_duration=0.5,
            error_message="Segmentation fault",
            failure_message="Process crashed",
            crash_info=crash_info
        )

        results = collector.finalize_results()

        test = results.tests[0]
        assert test.name == "complex_test"
        assert test.outcome == TestOutcome.CRASHED
        assert test.error_message == "Segmentation fault"
        assert test.failure_message == "Process crashed"
        assert test.crash_info == crash_info

    def test_large_number_of_tests(self):
        """Test handling large number of test results."""
        collector = ResultCollector()

        # Add many test results
        for i in range(1000):
            outcome = TestOutcome.PASSED if i % 2 == 0 else TestOutcome.FAILED
            collector.add_test_result(TestResult(f"test_{i}", outcome, 0.1))

        results = collector.finalize_results()

        assert results.summary["total"] == 1000
        assert results.summary["passed"] == 500
        assert results.summary["failed"] == 500

    def test_unicode_in_test_names_and_messages(self):
        """Test handling Unicode in test names and messages."""
        collector = ResultCollector()

        collector.record_test(
            name="test_unicode_你好",
            outcome=TestOutcome.FAILED,
            duration=1.0,
            failure_message="Failed with 🚫 emoji and 世界 characters"
        )

        results = collector.finalize_results()

        test = results.tests[0]
        assert "你好" in test.name
        assert "🚫" in test.failure_message
        assert "世界" in test.failure_message
