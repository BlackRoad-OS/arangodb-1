"""Tests for result collection and processing."""

import pytest
import time
from pathlib import Path

from armadillo.results.collector import (
    ResultCollector,
    TestResultParams,
    TestTiming,
    get_result_collector,
    record_test_result,
    finalize_results,
    export_results,
)
from armadillo.core.types import ExecutionOutcome
from armadillo.core.errors import ResultProcessingError


class TestResultCollector:
    """Test ResultCollector class with hierarchical structure."""

    def test_result_collector_creation(self):
        """Test ResultCollector creation."""
        collector = ResultCollector()

        assert len(collector.test_suites) == 0
        assert collector.start_time > 0
        assert len(collector.metadata) == 0
        assert collector._finalized is False

    def test_record_single_test_result(self):
        """Test recording a single test result."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::test_passed",
            outcome=ExecutionOutcome.PASSED,
            duration=1.5,
            setup_duration=0.1,
            call_duration=1.3,
            teardown_duration=0.1,
        )

        assert len(collector.test_suites) == 1
        assert "tests/test_example.py" in collector.test_suites
        suite = collector.test_suites["tests/test_example.py"]
        assert len(suite.tests) == 1
        assert "test_passed" in suite.tests
        test = suite.tests["test_passed"]
        assert test.outcome == "passed"
        assert test.duration_seconds == 1.5

    def test_record_multiple_tests_same_file(self):
        """Test recording multiple tests from the same file."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::test_one",
            outcome=ExecutionOutcome.PASSED,
            duration=1.0,
        )
        collector.record_test_result(
            nodeid="tests/test_example.py::test_two",
            outcome=ExecutionOutcome.FAILED,
            duration=2.0,
        )

        assert len(collector.test_suites) == 1
        suite = collector.test_suites["tests/test_example.py"]
        assert len(suite.tests) == 2
        assert "test_one" in suite.tests
        assert "test_two" in suite.tests

    def test_record_tests_different_files(self):
        """Test recording tests from different files."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_one.py::test_a",
            outcome=ExecutionOutcome.PASSED,
            duration=1.0,
        )
        collector.record_test_result(
            nodeid="tests/test_two.py::test_b",
            outcome=ExecutionOutcome.PASSED,
            duration=2.0,
        )

        assert len(collector.test_suites) == 2
        assert "tests/test_one.py" in collector.test_suites
        assert "tests/test_two.py" in collector.test_suites

    def test_record_test_with_class(self):
        """Test recording test with class name in nodeid."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::TestClass::test_method",
            outcome=ExecutionOutcome.PASSED,
            duration=1.0,
        )

        suite = collector.test_suites["tests/test_example.py"]
        assert "TestClass::test_method" in suite.tests

    def test_record_test_with_markers(self):
        """Test recording test with markers."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::test_slow",
            outcome=ExecutionOutcome.PASSED,
            duration=5.0,
            markers=["slow", "arango_single"],
        )

        test = collector.test_suites["tests/test_example.py"].tests["test_slow"]
        assert test.markers == ["slow", "arango_single"]

    def test_record_test_with_details(self):
        """Test recording failed test with details."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::test_failed",
            outcome=ExecutionOutcome.FAILED,
            duration=1.0,
            details="AssertionError: Expected 5, got 3",
        )

        test = collector.test_suites["tests/test_example.py"].tests["test_failed"]
        assert test.details == "AssertionError: Expected 5, got 3"

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

        # Add some test results
        collector.record_test_result(
            nodeid="tests/test_example.py::test_passed",
            outcome=ExecutionOutcome.PASSED,
            duration=1.0,
        )
        collector.record_test_result(
            nodeid="tests/test_example.py::test_failed",
            outcome=ExecutionOutcome.FAILED,
            duration=2.0,
        )
        collector.record_test_result(
            nodeid="tests/test_example.py::test_skipped",
            outcome=ExecutionOutcome.SKIPPED,
            duration=0.0,
        )
        collector.set_metadata(framework="test")

        # Wait a bit to ensure duration calculation
        time.sleep(0.01)

        results = collector.finalize_results()

        assert isinstance(results, dict)
        assert "summary" in results
        assert "test_suites" in results
        assert "test_run" in results
        assert results["summary"]["total"] == 3
        assert results["summary"]["passed"] == 1
        assert results["summary"]["failed"] == 1
        assert results["summary"]["skipped"] == 1
        assert results["test_run"]["duration_seconds"] > 0

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

        with pytest.raises(
            ResultProcessingError, match="Cannot add results after finalization"
        ):
            collector.record_test_result(
                nodeid="tests/test_example.py::test_late",
                outcome=ExecutionOutcome.PASSED,
                duration=1.0,
            )

    def test_suite_summary_calculation(self):
        """Test that suite summaries are calculated correctly."""
        collector = ResultCollector()

        # Add tests with different outcomes to same suite
        collector.record_test_result(
            nodeid="tests/test_example.py::test_1",
            outcome=ExecutionOutcome.PASSED,
            duration=1.0,
        )
        collector.record_test_result(
            nodeid="tests/test_example.py::test_2",
            outcome=ExecutionOutcome.PASSED,
            duration=1.0,
        )
        collector.record_test_result(
            nodeid="tests/test_example.py::test_3",
            outcome=ExecutionOutcome.FAILED,
            duration=1.0,
        )

        results = collector.finalize_results()
        suite_data = results["test_suites"]["tests/test_example.py"]

        assert suite_data["summary"]["total"] == 3
        assert suite_data["summary"]["passed"] == 2
        assert suite_data["summary"]["failed"] == 1

    def test_export_json(self, temp_dir):
        """Test exporting results as JSON."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::test_passed",
            outcome=ExecutionOutcome.PASSED,
            duration=1.5,
        )
        collector.record_test_result(
            nodeid="tests/test_example.py::test_failed",
            outcome=ExecutionOutcome.FAILED,
            duration=2.0,
            details="Test failed",
        )

        exported_files = collector.export_results(["json"], temp_dir)

        assert "json" in exported_files
        json_file = exported_files["json"]
        assert json_file.exists()
        assert json_file.name == "test_results.json"

        # Verify JSON content
        import json as json_module

        with open(json_file) as f:
            data = json_module.load(f)

        assert "armadillo_version" in data
        assert "schema_version" in data
        assert "test_suites" in data
        assert "summary" in data
        assert len(data["test_suites"]) == 1

    def test_export_junit(self, temp_dir):
        """Test exporting results as JUnit XML."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::test_passed",
            outcome=ExecutionOutcome.PASSED,
            duration=1.0,
        )
        collector.record_test_result(
            nodeid="tests/test_example.py::test_failed",
            outcome=ExecutionOutcome.FAILED,
            duration=2.0,
            details="Assertion error",
        )

        exported_files = collector.export_results(["junit"], temp_dir)

        assert "junit" in exported_files
        junit_file = exported_files["junit"]
        assert junit_file.exists()
        assert junit_file.name == "junit.xml"

        # Verify XML structure
        content = junit_file.read_text()
        assert "<testsuite" in content
        assert "<testcase" in content
        assert "<failure" in content

    def test_export_multiple_formats(self, temp_dir):
        """Test exporting results in multiple formats."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::test_passed",
            outcome=ExecutionOutcome.PASSED,
            duration=1.0,
        )

        exported_files = collector.export_results(["json", "junit"], temp_dir)

        assert len(exported_files) == 2
        assert "json" in exported_files
        assert "junit" in exported_files
        assert exported_files["json"].exists()
        assert exported_files["junit"].exists()


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

        record_test_result(
            "tests/test_example.py::test_global",
            ExecutionOutcome.PASSED,
            1.0,
            setup_duration=0.1,
        )

        collector = get_result_collector()
        assert len(collector.test_suites) == 1
        suite = collector.test_suites["tests/test_example.py"]
        assert "test_global" in suite.tests
        test = suite.tests["test_global"]
        assert test.outcome == "passed"
        assert test.setup_duration_seconds == 0.1

    def test_finalize_results_function(self):
        """Test global finalize_results function."""
        # Reset and populate global collector
        import armadillo.results.collector

        armadillo.results.collector._result_collector = ResultCollector()

        record_test_result("tests/test_example.py::test1", ExecutionOutcome.PASSED, 1.0)
        record_test_result("tests/test_example.py::test2", ExecutionOutcome.FAILED, 2.0)

        results = finalize_results()

        assert isinstance(results, dict)
        assert results["summary"]["total"] == 2

    def test_export_results_function(self, temp_dir):
        """Test global export_results function."""
        # Reset and populate global collector
        import armadillo.results.collector

        armadillo.results.collector._result_collector = ResultCollector()

        record_test_result("tests/test_example.py::test1", ExecutionOutcome.PASSED, 1.0)

        exported_files = export_results(["json"], temp_dir)

        assert "json" in exported_files
        assert exported_files["json"].exists()


class TestResultCollectorEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_result_collection(self, temp_dir):
        """Test handling empty result collection."""
        collector = ResultCollector()

        results = collector.finalize_results()

        assert len(results["test_suites"]) == 0
        assert (
            results["test_run"]["duration_seconds"] > 0
        )  # Should still have elapsed time
        assert results["summary"]["total"] == 0

        # Should still be able to export
        exported_files = collector.export_results(["json"], temp_dir)
        assert "json" in exported_files

    def test_very_short_duration_tests(self):
        """Test handling tests with very short durations."""
        collector = ResultCollector()

        collector.record_test_result(
            nodeid="tests/test_example.py::test_fast",
            outcome=ExecutionOutcome.PASSED,
            duration=0.001,
        )
        collector.record_test_result(
            nodeid="tests/test_example.py::test_instant",
            outcome=ExecutionOutcome.PASSED,
            duration=0.0,
        )

        results = collector.finalize_results()

        assert results["summary"]["total"] == 2
        assert results["summary"]["passed"] == 2

    def test_test_with_crash_info(self):
        """Test test result with crash information."""
        from armadillo.core.types import CrashInfo
        from armadillo.core.value_objects import ServerId
        collector = ResultCollector()

        crash_info = {
            ServerId("srv1"): CrashInfo(
                exit_code=-11,
                timestamp=1234567890.0,
                stderr="Segmentation fault",
                signal=11,
            )
        }

        collector.record_test_result(
            nodeid="tests/test_crash.py::test_segfault",
            outcome=ExecutionOutcome.CRASHED,
            duration=5.0,
            details="Process crashed",
            crash_info=crash_info,
        )

        results = collector.finalize_results()

        test = results["test_suites"]["tests/test_crash.py"]["tests"]["test_segfault"]
        assert test["outcome"] == "crashed"
        assert "srv1" in test["crash_info"]  # Should be string key in JSON
        assert test["crash_info"]["srv1"]["exit_code"] == -11
        assert test["crash_info"]["srv1"]["signal"] == 11

    def test_large_number_of_tests(self):
        """Test handling large number of test results."""
        collector = ResultCollector()

        # Add many test results
        for i in range(100):
            outcome = ExecutionOutcome.PASSED if i % 2 == 0 else ExecutionOutcome.FAILED
            collector.record_test_result(
                nodeid=f"tests/test_suite.py::test_{i}",
                outcome=outcome,
                duration=0.1,
            )

        results = collector.finalize_results()

        assert results["summary"]["total"] == 100
        assert results["summary"]["passed"] == 50
        assert results["summary"]["failed"] == 50
