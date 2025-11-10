"""Custom test reporter for Armadillo framework.

Provides detailed verbose output with timestamps, test phases, and comprehensive timing information.
"""

import os
import time
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path
from _pytest.reports import TestReport

from ..core.log import get_logger
from ..core.types import ExecutionOutcome
from ..core.process import has_any_crash
from ..results.collector import ResultCollector
from ..utils.output import write_stdout

logger = get_logger(__name__)


# ANSI color codes for output formatting
class Colors:
    """ANSI color codes for terminal output formatting."""

    GREEN = "\033[32m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    WHITE = "\033[37m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @staticmethod
    def is_color_supported():
        """Check if terminal supports colors."""
        return hasattr(os.sys.stdout, "isatty") and os.sys.stdout.isatty()


class ArmadilloReporter:
    """Custom test reporter that provides detailed verbose output with timing and phases."""

    def __init__(self, result_collector: Optional[ResultCollector] = None):
        self.test_times: Dict[str, Dict[str, float]] = {}
        self.test_reports: Dict[str, TestReport] = (
            {}
        )  # Store reports for result collection
        self.test_skipped: Dict[str, bool] = {}  # Track which tests were skipped
        self.suite_start_times: Dict[str, float] = {}
        self.suite_test_counts: Dict[str, int] = {}
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.session_start_time = 0.0
        self.session_finish_time = 0.0
        self.final_exitstatus = 0
        self.expected_total_tests = 0
        self.summary_printed = False
        self.use_colors = Colors.is_color_supported()
        self.current_file = None  # Track current test file for header display
        self.deployment_failed = False  # Flag set by plugin when deployment fails
        self.file_start_times: Dict[str, float] = {}  # Track start time per file
        self.file_test_counts: Dict[str, int] = {}  # Track test count per file
        self.file_expected_counts: Dict[str, int] = {}  # Expected test count per file
        self.files_completed: set = set()  # Track which files have been completed
        self.result_collector = result_collector or ResultCollector()

    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if colors are supported."""
        if not self.use_colors:
            return text
        return f"{color}{text}{Colors.RESET}"

    def _write_to_terminal(self, message: str) -> None:
        """Write message directly to terminal.

        Since pytest is run with -s (no output capture), we can write directly
        to stdout without needing /dev/tty hacks.
        """
        write_stdout(message)

    def _get_timestamp(self) -> str:
        """Get formatted timestamp."""
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def _get_suite_name(self, nodeid: str) -> str:
        """Extract suite name from test nodeid."""
        # Convert pytest nodeid to suite name
        # Example: tests/shell_api/test_statistics.py::TestStatisticsAPI::test_name
        # -> calculating_statisticsSuite (matching JS framework style)
        parts = nodeid.split("::")
        if len(parts) >= 2:
            test_file = parts[0]
            _ = parts[1] if len(parts) > 1 else ""  # test_class, for future use

            # Extract meaningful name from file path
            file_name = test_file.split("/")[-1].replace("test_", "").replace(".py", "")

            # Create descriptive suite name
            if "statistics" in file_name:
                return "calculating_statisticsSuite"
            return f"{file_name}Suite"
        return "unknownSuite"

    def _get_test_name(self, nodeid: str) -> str:
        """Extract test name from nodeid."""
        parts = nodeid.split("::")
        if len(parts) >= 3:
            # Convert Python test name to descriptive format
            test_name = parts[2]
            # Convert test_statistics_correct_endpoint -> test_testing_statistics_correct_cmd
            return test_name
        return nodeid.split("::")[-1]

    def _get_file_path(self, nodeid: str) -> str:
        """Extract file path from pytest node ID."""
        return nodeid.split("::")[0]

    def _print_file_header(self, file_path: str):
        """Print a colored header when starting a new test file."""
        running_text = self._colorize("Running", Colors.CYAN)
        file_text = self._colorize(file_path, Colors.BOLD)
        header_msg = f"\n🚀 {running_text} {file_text}\n"
        underline = "─" * min(
            len(f"🚀 Running {file_path}"), 80
        )  # Limit width to 80 chars
        header_msg += f"{self._colorize(underline, Colors.CYAN)}\n"

        self._write_to_terminal(header_msg)

    def _print_file_summary(self, file_path: str):
        """Print a summary for a completed test file."""
        test_count = self.file_test_counts.get(file_path, 0)
        if test_count == 0:
            return  # No tests in this file

        # Calculate file execution time
        current_time = time.time()
        file_start_time = self.file_start_times.get(file_path, current_time)
        file_duration_ms = int((current_time - file_start_time) * 1000)

        # Print file summary
        timestamp = self._get_timestamp()
        separator = self._colorize("[------------]", Colors.CYAN)
        file_text = self._colorize(file_path, Colors.BOLD)
        summary_msg = (
            f"{timestamp} {separator} {test_count} tests from {file_text} "
            f"ran ({file_duration_ms}ms total)\n"
        )

        self._write_to_terminal(summary_msg)

    def _print_session_summary(self):
        """Print the session summary (total tests, timing, etc.)."""
        # Use captured session_finish_time if available, otherwise current time
        end_time = (
            self.session_finish_time if self.session_finish_time > 0 else time.time()
        )
        total_time = int((end_time - self.session_start_time) * 1000)

        # Consider it a failure if tests failed OR deployment failed
        is_failure = self.failed_tests > 0 or self.deployment_failed
        summary_color = Colors.RED if is_failure else Colors.GREEN
        status_text = "FAILED" if is_failure else "PASSED"
        write_stdout(
            f"{self._get_timestamp()} "
            f"{self._colorize(f'[   {status_text:>7} ]', summary_color)} "
            f"{self.passed_tests} tests.\n"
        )
        passed_colored = self._colorize(f"{self.passed_tests} passed", Colors.GREEN)
        failed_color = Colors.RED if self.failed_tests > 0 else Colors.GREEN
        failed_colored = self._colorize(f"{self.failed_tests} failed", failed_color)
        write_stdout(
            f"{self._get_timestamp()} {self._colorize('[============]', Colors.CYAN)} "
            f"Ran: {self.total_tests} tests "
            f"({passed_colored}, {failed_colored}) ({total_time}ms total)\n"
        )

    def pytest_sessionstart(self, _session):
        """Handle session start."""
        # session_start_time will be set by the plugin after server deployment
        # Don't print session start here - will be handled by file processing

    def pytest_runtest_logstart(self, nodeid, _location):
        """Handle test run start."""
        suite_name = self._get_suite_name(nodeid)
        test_name = self._get_test_name(nodeid)
        file_path = self._get_file_path(nodeid)

        # Check if we're starting a new test file and print header if needed
        if self.current_file != file_path:
            # Start tracking the new file
            self.current_file = file_path
            self.file_start_times[file_path] = time.time()
            self.file_test_counts[file_path] = 0
            self._print_file_header(file_path)

        # Track suite information
        if suite_name not in self.suite_start_times:
            self.suite_start_times[suite_name] = time.time()
            self.suite_test_counts[suite_name] = 0

        # Initialize test timing
        if test_name not in self.test_times:
            self.test_times[test_name] = {
                "setup": 0.0,
                "call": 0.0,
                "teardown": 0.0,
                "start": time.time(),
            }

    def pytest_runtest_setup(self, item):
        """Handle test setup start."""
        test_name = self._get_test_name(item.nodeid)
        if test_name in self.test_times:
            self.test_times[test_name]["setup_start"] = time.time()

    def pytest_runtest_call(self, item):
        """Handle test call start - print [ RUN ] here after fixture setup."""
        test_name = self._get_test_name(item.nodeid)

        # Print [ RUN ] message here, AFTER fixture setup has completed
        # This ensures deployment logs don't mix with test output
        run_msg = f"{self._get_timestamp()} {self._colorize('[ RUN        ]', Colors.YELLOW)} {test_name}\n"
        self._write_to_terminal(run_msg)

        if test_name in self.test_times:
            # Calculate setup time
            if "setup_start" in self.test_times[test_name]:
                self.test_times[test_name]["setup"] = (
                    time.time() - self.test_times[test_name]["setup_start"]
                ) * 1000  # Convert to milliseconds
            self.test_times[test_name]["call_start"] = time.time()

    def pytest_runtest_teardown(self, item):
        """Handle test teardown start."""
        test_name = self._get_test_name(item.nodeid)
        if test_name in self.test_times:
            self.test_times[test_name]["teardown_start"] = time.time()

    def pytest_runtest_logreport(self, report: TestReport):
        """Handle test report."""
        # Store all reports for later aggregation
        if report.when == "call":
            self.test_reports[report.nodeid] = report

            # Print PASSED immediately after call finishes (before teardown)
            # to avoid mixing with fixture teardown logs (like deployment shutdown)
            test_name = self._get_test_name(report.nodeid)

            # Calculate call time
            if (
                test_name in self.test_times
                and "call_start" in self.test_times[test_name]
            ):
                self.test_times[test_name]["call"] = (
                    time.time() - self.test_times[test_name]["call_start"]
                ) * 1000

            # Check if test passed (not skipped, not crashed, report outcome is passed)
            if (
                not self.test_skipped.get(report.nodeid, False)
                and not has_any_crash()
                and report.outcome == "passed"
            ):

                setup_time = int(self.test_times.get(test_name, {}).get("setup", 0))
                call_time = int(self.test_times.get(test_name, {}).get("call", 0))

                # Print PASSED message now (before teardown)
                write_stdout(
                    f"{self._get_timestamp()} {self._colorize('[     PASSED ]', Colors.GREEN)} {test_name} "
                    f"(setUp: {setup_time}ms, test: {call_time}ms, tearDown: 0ms)\n"
                )

                # Mark that we've printed this test result
                self.test_times[test_name]["result_printed"] = True
                self.passed_tests += 1

        # Track skips in any phase
        if report.outcome == "skipped":
            self.test_skipped[report.nodeid] = True

        if report.when == "teardown":
            test_name = self._get_test_name(report.nodeid)
            suite_name = self._get_suite_name(report.nodeid)
            file_path = self._get_file_path(report.nodeid)

            # Calculate teardown time
            if (
                test_name in self.test_times
                and "teardown_start" in self.test_times[test_name]
            ):
                self.test_times[test_name]["teardown"] = (
                    time.time() - self.test_times[test_name]["teardown_start"]
                ) * 1000  # Convert to milliseconds

            # Determine actual outcome
            # Check if test was skipped in any phase
            if self.test_skipped.get(report.nodeid, False):
                outcome = "skipped"
            # Check if there's crash info attached to the report (from makereport hook)
            # or check crash state directly
            elif (
                hasattr(report, "crash_info") and report.crash_info
            ) or has_any_crash():
                outcome = "failed"  # Crashed tests should show as failed
            else:
                outcome = report.outcome

            # Print test result
            if outcome == "passed":
                # Check if we already printed this result during call phase
                # (to avoid duplicate output - we print early to avoid mixing with teardown logs)
                if not self.test_times.get(test_name, {}).get("result_printed", False):
                    self.passed_tests += 1
                    setup_time = int(self.test_times.get(test_name, {}).get("setup", 0))
                    call_time = int(self.test_times.get(test_name, {}).get("call", 0))
                    teardown_time = int(
                        self.test_times.get(test_name, {}).get("teardown", 0)
                    )

                    # Write directly to stdout (fallback for edge cases)
                    write_stdout(
                        f"{self._get_timestamp()} {self._colorize('[     PASSED ]', Colors.GREEN)} {test_name} "
                        f"(setUp: {setup_time}ms, test: {call_time}ms, tearDown: {teardown_time}ms)\n"
                    )
            elif outcome == "skipped":
                # Test was skipped (e.g., due to crash in previous test)
                write_stdout(
                    f"{self._get_timestamp()} {self._colorize('[    SKIPPED ]', Colors.YELLOW)} {test_name}\n"
                )
            else:
                self.failed_tests += 1
                write_stdout(
                    f"{self._get_timestamp()} {self._colorize('[     FAILED ]', Colors.RED)} {test_name}\n"
                )

            # Record test result for JSON export
            self._record_test_result(report.nodeid, outcome)

            # Print file summary immediately after each test to ensure proper timing
            # This happens in teardown phase to ensure all timing is complete
            self._print_file_summary(file_path)

            self.suite_test_counts[suite_name] = (
                self.suite_test_counts.get(suite_name, 0) + 1
            )
            # Increment file test count FIRST
            self.file_test_counts[file_path] = (
                self.file_test_counts.get(file_path, 0) + 1
            )
            self.total_tests += 1

    def pytest_collection_modifyitems(self, items):
        """Handle collection completion - print file and suite info."""
        if not items:
            return

        # Set expected total tests for summary timing
        self.expected_total_tests = len(items)

        # Group tests by file for JS-framework-style output
        files = {}
        for item in items:
            file_path = str(item.fspath)
            if file_path not in files:
                files[file_path] = []
            files[file_path].append(item)

        # Set expected test counts per file
        for file_path, file_items in files.items():
            file_path_normalized = self._get_file_path(file_items[0].nodeid)
            self.file_expected_counts[file_path_normalized] = len(file_items)

        # Print file information to stdout
        for file_path, file_items in files.items():
            suite_name = self._get_suite_name(file_items[0].nodeid)
            write_stdout(
                f"{self._get_timestamp()} {self._colorize('[============]', Colors.CYAN)} "
                f"{self._colorize('armadillo:', Colors.BOLD)} Trying {file_path} ... 1\n"
            )
            write_stdout(
                f"{self._get_timestamp()} {self._colorize('[------------]', Colors.CYAN)} "
                f"{len(file_items)} tests from {self._colorize(suite_name, Colors.BOLD)} "
                f"(setUpAll: 0ms)\n"
            )

    def pytest_sessionfinish(self, _session, exitstatus):
        """Handle session finish - store data for later summary."""
        # session_finish_time is now set by the plugin before cleanup
        # Summary is printed immediately by the plugin before server shutdown
        self.final_exitstatus = exitstatus

    def _record_test_result(self, nodeid: str, outcome: str) -> None:
        """Record a test result to the result collector."""
        # Map pytest outcome to ExecutionOutcome
        outcome_map = {
            "passed": ExecutionOutcome.PASSED,
            "failed": ExecutionOutcome.FAILED,
            "skipped": ExecutionOutcome.SKIPPED,
            "error": ExecutionOutcome.ERROR,
        }

        exec_outcome = outcome_map.get(outcome, ExecutionOutcome.ERROR)

        # Get timing info (convert from milliseconds to seconds)
        test_name = self._get_test_name(nodeid)
        timing = self.test_times.get(test_name, {})
        setup_duration = timing.get("setup", 0) / 1000.0
        call_duration = timing.get("call", 0) / 1000.0
        teardown_duration = timing.get("teardown", 0) / 1000.0
        total_duration = setup_duration + call_duration + teardown_duration

        # Get details from stored report
        details = None
        if nodeid in self.test_reports:
            report = self.test_reports[nodeid]
            if report.longrepr:
                details = str(report.longrepr)

        # Get markers from stored report
        markers = []
        if nodeid in self.test_reports:
            report = self.test_reports[nodeid]
            if hasattr(report, "keywords"):
                # Extract marker names
                markers = [key for key in report.keywords if not key.startswith("_")]

        # Record to collector
        self.result_collector.record_test_result(
            nodeid=nodeid,
            outcome=exec_outcome,
            duration=total_duration,
            setup_duration=setup_duration,
            call_duration=call_duration,
            teardown_duration=teardown_duration,
            markers=markers,
            details=details,
        )

    def export_results(
        self,
        output_dir: Path,
        formats: Optional[list] = None,
        server_health: Optional[Dict["DeploymentId", "ServerHealthInfo"]] = None,
    ) -> None:
        """Export collected results to specified formats.

        Args:
            output_dir: Directory to write result files to
            formats: List of export formats (e.g., ["json", "junit"])
            server_health: Optional dict of ServerHealthInfo by DeploymentId
        """
        if formats is None:
            formats = ["json"]

        try:
            # Set metadata from test run
            from ..core.config import get_config

            config = get_config()

            self.result_collector.set_metadata(
                deployment_mode=config.deployment_mode.value,
                build_dir=str(config.bin_dir) if config.bin_dir else "",
                test_timeout=config.test_timeout,
                compact_mode=config.compact_mode,
                show_server_logs=config.show_server_logs,
            )

            # Set server health if provided (ServerHealthInfo instances)
            if server_health:
                self.result_collector.set_server_health(server_health)

            # Export results
            exported_files = self.result_collector.export_results(formats, output_dir)
            logger.info("Exported test results to: %s", list(exported_files.values()))
        except Exception as e:
            logger.error("Failed to export results: %s", e, exc_info=True)

    def print_final_summary(self):
        """Print the final test summary."""
        if self.summary_printed:
            return  # Already printed

        self._print_session_summary()
        self.summary_printed = True


# Global reporter instance
_reporter: Optional[ArmadilloReporter] = None


def get_armadillo_reporter(
    result_collector: Optional[ResultCollector] = None,
) -> ArmadilloReporter:
    """Get or create the global Armadillo reporter.

    Args:
        result_collector: Optional ResultCollector to use (only used on first call)

    Returns:
        Global ArmadilloReporter instance
    """
    global _reporter
    if _reporter is None:
        _reporter = ArmadilloReporter(result_collector=result_collector)
    return _reporter
