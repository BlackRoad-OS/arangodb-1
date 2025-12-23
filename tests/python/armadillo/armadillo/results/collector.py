"""Test result collection and aggregation."""

import time
import platform
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from ..core.types import CrashInfo, ServerHealthInfo, SanitizerError
from ..core.enums import ExecutionOutcome
from ..core.value_objects import ServerId, DeploymentId
from ..core.errors import ResultProcessingError, SerializationError, FilesystemError
from ..core.log import get_logger
from ..utils.codec import to_json_string
from ..utils.filesystem import atomic_write

logger = get_logger(__name__)


@dataclass
class TestFailureInfo:
    """Complete failure information from pytest report.

    Aggregates failure data from setup/call/teardown phases.
    This captures the complete failure story including exception details
    and full traceback for proper reporting.
    """

    __test__ = False  # Tell pytest this is not a test class

    phase: str  # "setup" | "call" | "teardown"
    exception_type: str  # e.g., "AssertionError"
    exception_message: str  # Short message
    traceback: str  # Full traceback
    longrepr: str  # Full pytest representation


@dataclass
class TestTiming:
    """Timing information for a test."""

    __test__ = False  # Tell pytest this is not a test class

    duration: float
    setup_duration: float = 0.0
    teardown_duration: float = 0.0


@dataclass
class TestResultParams:
    """Parameters for recording a test result."""

    __test__ = False  # Tell pytest this is not a test class

    name: str
    outcome: ExecutionOutcome
    timing: TestTiming
    error_message: Optional[str] = None
    failure_message: Optional[str] = None
    crash_info: Optional[Dict[ServerId, CrashInfo]] = None


@dataclass
class TestResult:
    """Individual test result for hierarchical structure."""

    __test__ = False  # Tell pytest this is not a test class

    id: str  # Full pytest nodeid
    outcome: str  # Outcome as string (passed, failed, etc.)
    duration_seconds: float
    setup_duration_seconds: float = 0.0
    call_duration_seconds: float = 0.0
    teardown_duration_seconds: float = 0.0
    markers: List[str] = field(default_factory=list)
    details: Optional[str] = None
    crash_info: Optional[Dict[ServerId, CrashInfo]] = None
    artifacts: List[str] = field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    # Complete failure information from pytest
    failure_info: Optional[TestFailureInfo] = None

    # Matched sanitizer errors (pre-computed during finalization)
    # Each SanitizerError has its own match_confidence field
    matched_sanitizers: List[SanitizerError] = field(default_factory=list)


@dataclass
class TestSuite:
    """Test suite (file) containing multiple tests."""

    __test__ = False  # Tell pytest this is not a test class

    file: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: float = 0.0
    setup_duration_seconds: float = 0.0
    teardown_duration_seconds: float = 0.0
    summary: Dict[str, int] = field(default_factory=dict)
    tests: Dict[str, TestResult] = field(default_factory=dict)


class ResultCollector:
    """Collects and aggregates test results in hierarchical format."""

    def __init__(self) -> None:
        self.test_suites: Dict[str, TestSuite] = {}
        self.start_time = time.time()
        self.metadata: Dict[str, Any] = {}
        self.server_health: Dict[DeploymentId, ServerHealthInfo] = (
            {}
        )  # DeploymentId -> ServerHealthInfo instances
        self._finalized = False
        self._suite_start_times: Dict[str, float] = {}

    def _extract_file_path(self, nodeid: str) -> str:
        """Extract file path from pytest nodeid."""
        # nodeid format: "path/to/file.py::TestClass::test_method"
        return nodeid.split("::")[0]

    def _extract_test_name(self, nodeid: str) -> str:
        """Extract test name from pytest nodeid (excluding file path)."""
        # nodeid format: "path/to/file.py::TestClass::test_method"
        parts = nodeid.split("::")
        if len(parts) > 1:
            return "::".join(parts[1:])
        return parts[0]

    def _ensure_suite(self, file_path: str) -> TestSuite:
        """Ensure a test suite exists for the given file path."""
        if file_path not in self.test_suites:
            self.test_suites[file_path] = TestSuite(file=file_path)
            self._suite_start_times[file_path] = time.time()
        return self.test_suites[file_path]

    def record_test_result(
        self,
        nodeid: str,
        outcome: ExecutionOutcome,
        duration: float,
        setup_duration: float = 0.0,
        call_duration: float = 0.0,
        teardown_duration: float = 0.0,
        markers: Optional[List[str]] = None,
        details: Optional[str] = None,
        crash_info: Optional[Dict[ServerId, CrashInfo]] = None,
        artifacts: Optional[List[str]] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        failure_info: Optional[TestFailureInfo] = None,
    ) -> None:
        """Record a test result in the hierarchical structure."""
        if self._finalized:
            raise ResultProcessingError("Cannot add results after finalization")

        file_path = self._extract_file_path(nodeid)
        test_name = self._extract_test_name(nodeid)
        suite = self._ensure_suite(file_path)

        # Create test result
        test_result = TestResult(
            id=nodeid,
            outcome=outcome.value,
            duration_seconds=duration,
            setup_duration_seconds=setup_duration,
            call_duration_seconds=call_duration,
            teardown_duration_seconds=teardown_duration,
            markers=markers or [],
            details=details,
            crash_info=crash_info,
            artifacts=artifacts or [],
            started_at=started_at.isoformat() if started_at else None,
            finished_at=finished_at.isoformat() if finished_at else None,
            failure_info=failure_info,
        )

        suite.tests[test_name] = test_result
        logger.debug("Recorded test result: %s -> %s", nodeid, outcome.value)

    def record_test(self, params: TestResultParams) -> None:
        """Record a test result using structured parameters."""
        # Convert structured format to internal representation
        self.record_test_result(
            nodeid=params.name,
            outcome=params.outcome,
            duration=params.timing.duration,
            setup_duration=params.timing.setup_duration,
            call_duration=params.timing.duration
            - params.timing.setup_duration
            - params.timing.teardown_duration,
            teardown_duration=params.timing.teardown_duration,
            details=params.error_message or params.failure_message,
            crash_info=params.crash_info,
        )

    def set_metadata(self, **metadata: Any) -> None:
        """Set metadata for the test run."""
        self.metadata.update(metadata)

    def set_server_health(
        self, health_data: Dict[DeploymentId, ServerHealthInfo]
    ) -> None:
        """Set server health data from deployments.

        Args:
            health_data: Dictionary mapping DeploymentId to ServerHealthInfo instances
        """
        self.server_health = health_data

    def _safe_platform_info(self, info_type: str) -> str:
        """Safely retrieve platform information, handling potential subprocess issues."""
        try:
            if info_type == "python_version":
                return platform.python_version()
            if info_type == "platform":
                return platform.platform()
            if info_type == "hostname":
                return platform.node()
            return "unknown"
        except Exception:
            # Handle any issues with platform module (e.g., in tests with mocked subprocess)
            return "unknown"

    def finalize_results(self) -> Dict[str, Any]:
        """Finalize and process all results."""
        if self._finalized:
            raise ResultProcessingError("Results already finalized")

        end_time = time.time()
        total_duration = end_time - self.start_time

        # Finalize each suite's timing and summary
        for suite in self.test_suites.values():
            self._finalize_suite(suite)

        # Match sanitizers to tests and attach to TestResult objects
        # This is the SINGLE PLACE where sanitizer matching happens
        self._match_and_attach_sanitizers()

        # Calculate overall summary
        summary = self._calculate_global_summary()

        # Get version info
        from .. import __version__ as armadillo_version

        # Build final results structure
        results = {
            "armadillo_version": armadillo_version if armadillo_version else "1.0.0",
            "schema_version": "1.0",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "test_run": {
                "started_at": datetime.fromtimestamp(
                    self.start_time, tz=timezone.utc
                ).isoformat(),
                "finished_at": datetime.fromtimestamp(
                    end_time, tz=timezone.utc
                ).isoformat(),
                "duration_seconds": total_duration,
                "environment": {
                    "deployment_mode": self.metadata.get("deployment_mode", "unknown"),
                    "build_dir": str(self.metadata.get("build_dir", "")),
                    "python_version": self._safe_platform_info("python_version"),
                    "platform": self._safe_platform_info("platform"),
                    "hostname": self._safe_platform_info("hostname"),
                },
                "configuration": {
                    "test_timeout": self.metadata.get("test_timeout", 900.0),
                    "compact_mode": self.metadata.get("compact_mode", False),
                    "show_server_logs": self.metadata.get("show_server_logs", False),
                },
            },
            "summary": summary,
            "test_suites": self._serialize_suites(),
            "server_health": (
                {
                    str(deployment_id): health.model_dump()
                    for deployment_id, health in self.server_health.items()
                }
                if self.server_health
                else {}
            ),
        }

        self._finalized = True
        total_tests = summary["total"]
        logger.info(
            "Finalized results: %s tests in %s suites, %.2fs total",
            total_tests,
            len(self.test_suites),
            total_duration,
        )
        return results

    def _finalize_suite(self, suite: TestSuite) -> None:
        """Finalize a suite's timing and summary statistics."""
        # Calculate suite summary
        suite.summary = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "timeout": 0,
            "crashed": 0,
        }

        suite_start = None
        suite_end = None
        total_setup = 0.0
        total_teardown = 0.0

        for test in suite.tests.values():
            # Update summary counts
            suite.summary["total"] += 1
            outcome = test.outcome
            if outcome in suite.summary:
                suite.summary[outcome] += 1

            # Track timing
            total_setup += test.setup_duration_seconds
            total_teardown += test.teardown_duration_seconds

            # Track earliest start and latest end
            if test.started_at:
                if suite_start is None or test.started_at < suite_start:
                    suite_start = test.started_at
            if test.finished_at:
                if suite_end is None or test.finished_at > suite_end:
                    suite_end = test.finished_at

        # Set suite timing
        suite.started_at = suite_start
        suite.finished_at = suite_end
        suite.setup_duration_seconds = total_setup
        suite.teardown_duration_seconds = total_teardown

        # Calculate total duration from start/end or sum of tests
        if suite_start and suite_end:
            start_dt = datetime.fromisoformat(suite_start)
            end_dt = datetime.fromisoformat(suite_end)
            suite.duration_seconds = (end_dt - start_dt).total_seconds()
        else:
            # Fallback: sum all test durations
            suite.duration_seconds = sum(
                t.duration_seconds for t in suite.tests.values()
            )

    def _match_and_attach_sanitizers(self) -> None:
        """Match sanitizers to tests and attach directly to TestResult objects.

        This is the SINGLE PLACE where sanitizer matching happens.
        Export functions will simply read the matched_sanitizers field.
        Uses centralized matching logic from sanitizer_matcher module.
        """
        from ..utils.sanitizer_matcher import calculate_match_confidence

        if not self.server_health:
            return

        # Extract all sanitizer errors from server health
        all_sanitizer_errors: List[SanitizerError] = []
        for health_info in self.server_health.values():
            for server_errors in health_info.sanitizer_errors.values():
                all_sanitizer_errors.extend(server_errors)

        if not all_sanitizer_errors:
            return

        # Get tolerance from metadata (configurable, defaults to 5.0)
        tolerance = self.metadata.get("sanitizer_match_tolerance_seconds", 5.0)

        # Match each sanitizer error to tests using timestamps
        for suite in self.test_suites.values():
            for test in suite.tests.values():
                if not test.started_at or not test.finished_at:
                    continue

                # Parse ISO timestamps
                test_start = datetime.fromisoformat(test.started_at)
                test_end = datetime.fromisoformat(test.finished_at)

                # Find sanitizers that match this test's time window
                for san_error in all_sanitizer_errors:
                    confidence = calculate_match_confidence(
                        san_error.timestamp, test_start, test_end, tolerance
                    )

                    # Only attach high-confidence matches
                    if confidence == "high":
                        # Create a copy with confidence set
                        matched_san = san_error.model_copy()
                        matched_san.match_confidence = confidence
                        test.matched_sanitizers.append(matched_san)

        # Log matching summary
        total_matched = sum(
            len(test.matched_sanitizers)
            for suite in self.test_suites.values()
            for test in suite.tests.values()
        )
        if total_matched > 0:
            logger.info(
                "Matched %d sanitizer error(s) to tests with high confidence",
                total_matched,
            )

    def _calculate_global_summary(self) -> Dict[str, int]:
        """Calculate overall summary statistics across all suites."""
        summary = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "timeout": 0,
            "crashed": 0,
        }

        for suite in self.test_suites.values():
            for key in summary:
                summary[key] += suite.summary.get(key, 0)

        return summary

    def _serialize_suites(self) -> Dict[str, Any]:
        """Serialize test suites to dictionary format.

        Now includes complete failure information and matched sanitizers
        from the data model (not computed during export).
        """
        result = {}
        for file_path, suite in self.test_suites.items():
            result[file_path] = {
                "file": suite.file,
                "started_at": suite.started_at,
                "finished_at": suite.finished_at,
                "duration_seconds": suite.duration_seconds,
                "setup_duration_seconds": suite.setup_duration_seconds,
                "teardown_duration_seconds": suite.teardown_duration_seconds,
                "summary": suite.summary,
                "tests": {
                    test_name: {
                        "id": test.id,
                        "outcome": test.outcome,
                        "duration_seconds": test.duration_seconds,
                        "setup_duration_seconds": test.setup_duration_seconds,
                        "call_duration_seconds": test.call_duration_seconds,
                        "teardown_duration_seconds": test.teardown_duration_seconds,
                        "markers": test.markers,
                        "details": test.details,
                        "crash_info": (
                            {
                                str(server_id): crash.model_dump()
                                for server_id, crash in test.crash_info.items()
                            }
                            if test.crash_info
                            else None
                        ),
                        "artifacts": test.artifacts,
                        "started_at": test.started_at,
                        "finished_at": test.finished_at,
                        # Complete failure information
                        "failure_info": (
                            {
                                "phase": test.failure_info.phase,
                                "exception_type": test.failure_info.exception_type,
                                "exception_message": test.failure_info.exception_message,
                                "traceback": test.failure_info.traceback,
                                "longrepr": test.failure_info.longrepr,
                            }
                            if test.failure_info
                            else None
                        ),
                        # Matched sanitizers (pre-computed during finalization)
                        "matched_sanitizers": (
                            [
                                {
                                    "content": san.content,
                                    "file_path": str(san.file_path),
                                    "timestamp": san.timestamp.isoformat(),
                                    "sanitizer_type": san.sanitizer_type,
                                    "server_id": san.server_id,
                                    "match_confidence": san.match_confidence,
                                }
                                for san in test.matched_sanitizers
                            ]
                            if test.matched_sanitizers
                            else []
                        ),
                    }
                    for test_name, test in suite.tests.items()
                },
            }
        return result

    def export_results(self, formats: List[str], output_dir: Path) -> Dict[str, Path]:
        """Export results in specified formats."""
        if not self._finalized:
            results = self.finalize_results()
        else:
            # Already finalized, need to regenerate the results dict
            # Temporarily unset finalized flag to allow re-generation
            self._finalized = False
            results = self.finalize_results()

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        exported_files = {}

        for format_name in formats:
            try:
                if format_name == "json":
                    file_path = output_dir / "test_results.json"
                    self._export_json(results, file_path)
                    exported_files["json"] = file_path
                elif format_name == "junit":
                    file_path = output_dir / "armadillo-junit.xml"
                    self._export_junit(results, file_path)
                    exported_files["junit"] = file_path
                else:
                    logger.warning("Unknown export format: %s", format_name)
            except (SerializationError, FilesystemError, OSError, IOError) as e:
                logger.error("Failed to export %s: %s", format_name, e, exc_info=True)
                raise ResultProcessingError(
                    f"Export failed for format {format_name}: {e}"
                ) from e

        logger.info(
            "Exported results in %s formats to %s", len(exported_files), output_dir
        )
        return exported_files

    def _format_matched_sanitizers_for_junit(
        self, matched_sanitizers: List[Dict[str, Any]]
    ) -> str:
        """Format matched sanitizers for JUnit XML error element.

        Pure transformation - reads from pre-computed matched_sanitizers data.

        Args:
            matched_sanitizers: List of sanitizer dictionaries from data model

        Returns:
            Formatted string with sanitizer content
        """
        lines = ["Sanitizer issue(s) detected during test execution:\n"]

        for san in matched_sanitizers:
            lines.append(f"File: {Path(san['file_path']).name}")
            lines.append(f"Timestamp: {san['timestamp']}")
            lines.append(f"Type: {san['sanitizer_type']}")
            lines.append(f"Server: {san['server_id']}")
            lines.append("")
            lines.append(san["content"])
            lines.append("\n" + "=" * 70 + "\n")

        return "\n".join(lines)

    def _export_json(self, results: Dict[str, Any], file_path: Path) -> None:
        """Export results as JSON in hierarchical format."""
        json_content = to_json_string(results)
        atomic_write(file_path, json_content)
        logger.debug("Exported JSON results to %s", file_path)

    def _export_junit(self, results: Dict[str, Any], file_path: Path) -> None:
        """Export results as JUnit XML - pure transformation.

        Reads from pre-computed data model. NO matching or enrichment logic.
        All data has been computed during finalization in finalize_results().
        """
        summary = results["summary"]
        test_run = results["test_run"]
        test_suites = results["test_suites"]

        testsuite = ET.Element("testsuite")
        testsuite.set("name", "ArmadilloTests")
        testsuite.set("tests", str(summary["total"]))
        testsuite.set("failures", str(summary["failed"]))
        testsuite.set("errors", str(summary["error"]))
        testsuite.set("skipped", str(summary["skipped"]))
        testsuite.set("time", f"{test_run['duration_seconds']:.3f}")
        testsuite.set("timestamp", test_run.get("started_at", ""))

        # Iterate through all suites and tests
        for suite_path, suite_data in test_suites.items():
            for test_name, test_data in suite_data["tests"].items():
                testcase = ET.SubElement(testsuite, "testcase")
                # Extract test name and classname from full ID
                test_id = test_data["id"]
                parts = test_id.split("::")
                if len(parts) > 1:
                    testcase.set("classname", "::".join(parts[:-1]))
                    testcase.set("name", parts[-1])
                else:
                    testcase.set("classname", suite_path)
                    testcase.set("name", test_name)
                testcase.set("time", f"{test_data['duration_seconds']:.3f}")

                outcome = test_data["outcome"]

                # NEW: Use complete failure information from data model
                if outcome == "failed" and test_data.get("failure_info"):
                    failure = ET.SubElement(testcase, "failure")
                    failure_info = test_data["failure_info"]
                    failure.set("type", failure_info["exception_type"])
                    failure.set("message", failure_info["exception_message"])
                    failure.text = failure_info["traceback"]
                elif outcome == "failed":
                    # Fallback if no failure_info (shouldn't happen with new code)
                    failure = ET.SubElement(testcase, "failure")
                    failure.set("message", test_data.get("details") or "Test failed")
                    if test_data.get("details"):
                        failure.text = test_data["details"]
                elif outcome == "error":
                    error = ET.SubElement(testcase, "error")
                    error.set("message", test_data.get("details") or "Test error")
                    if test_data.get("details"):
                        error.text = test_data["details"]
                elif outcome == "skipped":
                    skipped = ET.SubElement(testcase, "skipped")
                    skipped.set("message", test_data.get("details") or "Test skipped")
                elif outcome == "timeout":
                    error = ET.SubElement(testcase, "error")
                    error.set("message", "Test timed out")
                    error.set("type", "timeout")
                    if test_data.get("details"):
                        error.text = test_data["details"]
                elif outcome == "crashed":
                    error = ET.SubElement(testcase, "error")
                    error.set("message", "Test crashed")
                    error.set("type", "crash")
                    if test_data.get("crash_info"):
                        error.text = str(test_data["crash_info"])
                    elif test_data.get("details"):
                        error.text = test_data["details"]

                # NEW: Read matched sanitizers from pre-computed data
                if test_data.get("matched_sanitizers"):
                    error = ET.SubElement(testcase, "error")
                    error.set("type", "sanitizer")
                    error.set(
                        "message", "Sanitizer issue detected during test execution"
                    )
                    error.text = self._format_matched_sanitizers_for_junit(
                        test_data["matched_sanitizers"]
                    )

        # Add server health issues as system-err elements (DUAL REPRESENTATION)
        # This preserves the existing suite-level system-err for ALL sanitizers
        # while per-test errors above show only high-confidence matches
        if self.server_health:
            health_errors = 0
            for deployment_id, health_info in self.server_health.items():
                # Format health issues for JUnit XML (convert DeploymentId to string)
                formatted_text, error_count = health_info.format_for_junit(
                    str(deployment_id)
                )

                # Add system-err element with formatted health issues
                if formatted_text:
                    system_err = ET.SubElement(testsuite, "system-err")
                    system_err.text = formatted_text
                    health_errors += error_count

            # Update errors attribute if health issues found
            if health_errors > 0:
                current_errors = int(testsuite.get("errors", "0"))
                testsuite.set("errors", str(current_errors + health_errors))

        rough_string = ET.tostring(testsuite, encoding="unicode")
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent="  ")
        lines = [line for line in pretty_xml.split("\n") if line.strip()]
        xml_content = "\n".join(lines)
        atomic_write(file_path, xml_content)
        logger.debug("Exported JUnit XML results to %s", file_path)
