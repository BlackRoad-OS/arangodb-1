"""Test result collection and aggregation."""

import time
import platform
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from ..core.types import ExecutionOutcome, CrashInfo, ServerHealthInfo
from ..core.value_objects import ServerId, DeploymentId
from ..core.errors import ResultProcessingError, SerializationError, FilesystemError
from ..core.log import get_logger
from ..utils.codec import to_json_string
from ..utils.filesystem import atomic_write

logger = get_logger(__name__)


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
        for file_path, suite in self.test_suites.items():
            self._finalize_suite(suite, file_path)

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

    def _finalize_suite(self, suite: TestSuite, file_path: str) -> None:
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
        """Serialize test suites to dictionary format."""
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
                    file_path = output_dir / "junit.xml"
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

    def _export_json(self, results: Dict[str, Any], file_path: Path) -> None:
        """Export results as JSON in hierarchical format."""
        json_content = to_json_string(results)
        atomic_write(file_path, json_content)
        logger.debug("Exported JSON results to %s", file_path)

    def _export_junit(self, results: Dict[str, Any], file_path: Path) -> None:
        """Export results as JUnit XML."""
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
                details = test_data.get("details")

                if outcome == "failed":
                    failure = ET.SubElement(testcase, "failure")
                    failure.set("message", details or "Test failed")
                    if details:
                        failure.text = details
                elif outcome == "error":
                    error = ET.SubElement(testcase, "error")
                    error.set("message", details or "Test error")
                    if details:
                        error.text = details
                elif outcome == "skipped":
                    skipped = ET.SubElement(testcase, "skipped")
                    skipped.set("message", details or "Test skipped")
                elif outcome == "timeout":
                    error = ET.SubElement(testcase, "error")
                    error.set("message", "Test timed out")
                    error.set("type", "timeout")
                    if details:
                        error.text = details
                elif outcome == "crashed":
                    error = ET.SubElement(testcase, "error")
                    error.set("message", "Test crashed")
                    error.set("type", "crash")
                    if test_data.get("crash_info"):
                        error.text = str(test_data["crash_info"])
                    elif details:
                        error.text = details

        # Add server health issues as system-err elements
        # Note: self.server_health contains ServerHealthInfo instances
        if self.server_health:
            health_errors = 0
            for deployment_id, health_info in self.server_health.items():
                # Format health issues for JUnit XML (convert DeploymentId to string)
                formatted_text, error_count = health_info.format_for_junit(
                    str(deployment_id)
                )

                # Add system-err element with formatted health issues
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


_result_collector: Optional[ResultCollector] = None


def get_result_collector() -> ResultCollector:
    """Get or create global result collector."""
    global _result_collector
    if _result_collector is None:
        _result_collector = ResultCollector()
    return _result_collector


def record_test_result(
    name: str, outcome: ExecutionOutcome, duration: float, **kwargs
) -> None:
    """Record a test result using global collector."""
    get_result_collector().record_test_result(
        nodeid=name,
        outcome=outcome,
        duration=duration,
        setup_duration=kwargs.get("setup_duration", 0.0),
        call_duration=kwargs.get("call_duration", 0.0),
        teardown_duration=kwargs.get("teardown_duration", 0.0),
        markers=kwargs.get("markers"),
        details=kwargs.get("details"),
        crash_info=kwargs.get("crash_info"),
        artifacts=kwargs.get("artifacts"),
        started_at=kwargs.get("started_at"),
        finished_at=kwargs.get("finished_at"),
    )


def finalize_results() -> Dict[str, Any]:
    """Finalize results using global collector."""
    return get_result_collector().finalize_results()


def export_results(formats: List[str], output_dir: Path) -> Dict[str, Path]:
    """Export results using global collector."""
    return get_result_collector().export_results(formats, output_dir)
