"""Custom test reporter for Armadillo framework.

Provides detailed verbose output with timestamps, test phases, and comprehensive timing information.
"""

import os
import sys
import time
from datetime import datetime
from typing import Dict
from _pytest.reports import TestReport

from ..core.log import get_logger

logger = get_logger(__name__)


# ANSI color codes for output formatting
class Colors:
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
        return hasattr(os.sys.stderr, "isatty") and os.sys.stderr.isatty()


class ArmadilloReporter:
    """Custom test reporter that provides detailed verbose output with timing and phases."""

    def __init__(self):
        self.test_times: Dict[str, Dict[str, float]] = {}
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
        self.file_start_times: Dict[str, float] = {}  # Track start time per file
        self.file_test_counts: Dict[str, int] = {}  # Track test count per file
        self.file_expected_counts: Dict[str, int] = {}  # Expected test count per file
        self.files_completed: set = set()  # Track which files have been completed

    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if colors are supported."""
        if not self.use_colors:
            return text
        return f"{color}{text}{Colors.RESET}"

    def _write_to_terminal(self, message: str) -> None:
        """Write message directly to terminal.

        Since pytest is run with -s (no output capture), we can write directly
        to stderr without needing /dev/tty hacks.
        """
        sys.stderr.write(message)
        sys.stderr.flush()

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
            else:
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
        header_msg = f"\n🚀 {self._colorize('Running', Colors.CYAN)} {self._colorize(file_path, Colors.BOLD)}\n"
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
        summary_msg = f"{self._get_timestamp()} {self._colorize('[------------]', Colors.CYAN)} {test_count} tests from {self._colorize(file_path, Colors.BOLD)} ran ({file_duration_ms}ms total)\n"

        self._write_to_terminal(summary_msg)

    def _print_session_summary(self):
        """Print the session summary (total tests, timing, etc.)."""
        # Use captured session_finish_time if available, otherwise current time
        end_time = (
            self.session_finish_time if self.session_finish_time > 0 else time.time()
        )
        total_time = int((end_time - self.session_start_time) * 1000)
        summary_color = Colors.GREEN if self.failed_tests == 0 else Colors.RED
        status_text = "PASSED" if self.failed_tests == 0 else "FAILED"
        sys.stderr.write(
            f"{self._get_timestamp()} {self._colorize(f'[   {status_text:>7} ]', summary_color)} {self.passed_tests} tests.\n"
        )
        sys.stderr.write(
            f"{self._get_timestamp()} {self._colorize('[============]', Colors.CYAN)} Ran: {self.total_tests} tests "
            f"({self._colorize(f'{self.passed_tests} passed', Colors.GREEN)}, {self._colorize(f'{self.failed_tests} failed', Colors.RED if self.failed_tests > 0 else Colors.GREEN)}) ({total_time}ms total)\n"
        )
        sys.stderr.flush()

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

        # Print [ RUN ] message here - this hook may not be captured like pytest_runtest_call
        run_msg = f"{self._get_timestamp()} {self._colorize('[ RUN        ]', Colors.YELLOW)} {test_name}\n"
        self._write_to_terminal(run_msg)

    def pytest_runtest_setup(self, item):
        """Handle test setup start."""
        test_name = self._get_test_name(item.nodeid)
        if test_name in self.test_times:
            self.test_times[test_name]["setup_start"] = time.time()

    def pytest_runtest_call(self, item):
        """Handle test call start."""
        test_name = self._get_test_name(item.nodeid)
        if test_name in self.test_times:
            # Calculate setup time
            if "setup_start" in self.test_times[test_name]:
                self.test_times[test_name]["setup"] = (
                    time.time() - self.test_times[test_name]["setup_start"]
                ) * 1000  # Convert to milliseconds
            self.test_times[test_name]["call_start"] = time.time()

        # [ RUN ] message now printed in pytest_runtest_logstart to avoid capture issues

    def pytest_runtest_teardown(self, item):
        """Handle test teardown start."""
        test_name = self._get_test_name(item.nodeid)
        if test_name in self.test_times:
            # Calculate call time
            if "call_start" in self.test_times[test_name]:
                self.test_times[test_name]["call"] = (
                    time.time() - self.test_times[test_name]["call_start"]
                ) * 1000  # Convert to milliseconds
            self.test_times[test_name]["teardown_start"] = time.time()

    def pytest_runtest_logreport(self, report: TestReport):
        """Handle test report."""
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

            # Print test result
            if report.outcome == "passed":
                self.passed_tests += 1
                setup_time = int(self.test_times.get(test_name, {}).get("setup", 0))
                call_time = int(self.test_times.get(test_name, {}).get("call", 0))
                teardown_time = int(
                    self.test_times.get(test_name, {}).get("teardown", 0)
                )

                # Use sys.stderr to bypass pytest's output capture
                sys.stderr.write(
                    f"{self._get_timestamp()} {self._colorize('[     PASSED ]', Colors.GREEN)} {test_name} "
                    f"(setUp: {setup_time}ms, test: {call_time}ms, tearDown: {teardown_time}ms)\n"
                )
                sys.stderr.flush()
            else:
                self.failed_tests += 1
                sys.stderr.write(
                    f"{self._get_timestamp()} {self._colorize('[     FAILED ]', Colors.RED)} {test_name}\n"
                )
                sys.stderr.flush()

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

        # Print file information using sys.stderr to bypass pytest's output capture
        for file_path, file_items in files.items():
            suite_name = self._get_suite_name(file_items[0].nodeid)
            sys.stderr.write(
                f"{self._get_timestamp()} {self._colorize('[============]', Colors.CYAN)} {self._colorize('armadillo:', Colors.BOLD)} Trying {file_path} ... 1\n"
            )
            sys.stderr.write(
                f"{self._get_timestamp()} {self._colorize('[------------]', Colors.CYAN)} {len(file_items)} tests from {self._colorize(suite_name, Colors.BOLD)} (setUpAll: 0ms)\n"
            )
            sys.stderr.flush()

    def pytest_sessionfinish(self, _session, exitstatus):
        """Handle session finish - store data for later summary."""
        # session_finish_time is now set by the plugin before cleanup
        # Summary is printed immediately by the plugin before server shutdown
        self.final_exitstatus = exitstatus

    def print_final_summary(self):
        """Print the final test summary."""
        if self.summary_printed:
            return  # Already printed

        self._print_session_summary()
        self.summary_printed = True


# Global reporter instance
_reporter = None


def get_armadillo_reporter() -> ArmadilloReporter:
    """Get or create the global Armadillo reporter."""
    global _reporter
    if _reporter is None:
        _reporter = ArmadilloReporter()
    return _reporter
