"""Test result collection and aggregation."""

import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path

from ..core.types import ExecutionResult, SuiteExecutionResults, ExecutionOutcome
from ..core.errors import ResultProcessingError
from ..core.log import get_logger
from ..utils.codec import get_codec, to_json_string
from ..utils.filesystem import atomic_write

logger = get_logger(__name__)


class ResultCollector:
    """Collects and aggregates test results."""

    def __init__(self) -> None:
        self.tests: List[ExecutionResult] = []
        self.start_time = time.time()
        self.metadata: Dict[str, Any] = {}
        self._finalized = False

    def add_test_result(self, result: ExecutionResult) -> None:
        """Add a single test result."""
        if self._finalized:
            raise ResultProcessingError("Cannot add results after finalization")

        self.tests.append(result)
        logger.debug(f"Added test result: {result.name} -> {result.outcome.value}")

    def record_test(self,
                   name: str,
                   outcome: ExecutionOutcome,
                   duration: float,
                   setup_duration: float = 0.0,
                   teardown_duration: float = 0.0,
                   error_message: Optional[str] = None,
                   failure_message: Optional[str] = None,
                   crash_info: Optional[Dict[str, Any]] = None) -> None:
        """Record a test result directly."""
        result = ExecutionResult(
            name=name,
            outcome=outcome,
            duration=duration,
            setup_duration=setup_duration,
            teardown_duration=teardown_duration,
            error_message=error_message,
            failure_message=failure_message,
            crash_info=crash_info
        )
        self.add_test_result(result)

    def set_metadata(self, **metadata: Any) -> None:
        """Set metadata for the test run."""
        self.metadata.update(metadata)

    def finalize_results(self) -> SuiteExecutionResults:
        """Finalize and process all results."""
        if self._finalized:
            raise ResultProcessingError("Results already finalized")

        end_time = time.time()
        total_duration = end_time - self.start_time

        # Calculate summary statistics
        summary = self._calculate_summary()

        # Add timing metadata
        self.metadata.update({
            'start_time': datetime.fromtimestamp(self.start_time, tz=timezone.utc).isoformat(),
            'end_time': datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat(),
            'total_duration': total_duration,
        })

        results = SuiteExecutionResults(
            tests=self.tests.copy(),
            total_duration=total_duration,
            summary=summary,
            metadata=self.metadata.copy()
        )

        self._finalized = True
        logger.info(f"Finalized results: {len(self.tests)} tests, {total_duration:.2f}s total")

        return results

    def export_results(self, formats: List[str], output_dir: Path) -> Dict[str, Path]:
        """Export results in specified formats."""
        if not self._finalized:
            results = self.finalize_results()
        else:
            results = SuiteExecutionResults(
                tests=self.tests,
                total_duration=time.time() - self.start_time,
                summary=self._calculate_summary(),
                metadata=self.metadata
            )

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        exported_files = {}

        for format_name in formats:
            try:
                if format_name == "json":
                    file_path = output_dir / "UNITTEST_RESULT.json"
                    self._export_json(results, file_path)
                    exported_files["json"] = file_path

                elif format_name == "junit":
                    file_path = output_dir / "junit.xml"
                    self._export_junit(results, file_path)
                    exported_files["junit"] = file_path

                else:
                    logger.warning(f"Unknown export format: {format_name}")

            except Exception as e:
                logger.error(f"Failed to export {format_name}: {e}")
                raise ResultProcessingError(f"Export failed for format {format_name}: {e}")

        logger.info(f"Exported results in {len(exported_files)} formats to {output_dir}")
        return exported_files

    def _calculate_summary(self) -> Dict[str, int]:
        """Calculate summary statistics."""
        summary = {
            'total': len(self.tests),
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'error': 0,
            'timeout': 0,
            'crashed': 0,
        }

        for test in self.tests:
            outcome = test.outcome.value
            if outcome in summary:
                summary[outcome] += 1

        return summary

    def _export_json(self, results: SuiteExecutionResults, file_path: Path) -> None:
        """Export results as JSON."""
        # Convert to dictionary format expected by analysis tools
        export_data = {
            'framework_version': '1.0.0',
            'timestamp_utc': results.metadata.get('start_time'),
            'duration_s': results.total_duration,
            'tests': {},
            'meta': {
                'summary': results.summary,
                'metadata': results.metadata
            }
        }

        # Convert test results to expected format
        for test in results.tests:
            test_data = {
                'status': test.outcome.value,
                'duration_s': test.duration,
                'setup_duration_s': test.setup_duration,
                'teardown_duration_s': test.teardown_duration,
            }

            if test.error_message:
                test_data['error_message'] = test.error_message

            if test.failure_message:
                test_data['failure_message'] = test.failure_message

            if test.crash_info:
                test_data['crash_info'] = test.crash_info

            export_data['tests'][test.name] = test_data

        # Write JSON atomically
        json_content = to_json_string(export_data)
        atomic_write(file_path, json_content)
        logger.debug(f"Exported JSON results to {file_path}")

    def _export_junit(self, results: SuiteExecutionResults, file_path: Path) -> None:
        """Export results as JUnit XML."""
        import xml.etree.ElementTree as ET
        from xml.dom import minidom

        # Create root testsuite element
        testsuite = ET.Element('testsuite')
        testsuite.set('name', 'ArmadilloTests')
        testsuite.set('tests', str(results.summary['total']))
        testsuite.set('failures', str(results.summary['failed']))
        testsuite.set('errors', str(results.summary['error']))
        testsuite.set('skipped', str(results.summary['skipped']))
        testsuite.set('time', f"{results.total_duration:.3f}")
        testsuite.set('timestamp', results.metadata.get('start_time', ''))

        # Add test cases
        for test in results.tests:
            testcase = ET.SubElement(testsuite, 'testcase')
            testcase.set('name', test.name.split('::')[-1])  # Just the test function name
            testcase.set('classname', '::'.join(test.name.split('::')[:-1]))  # Module/class path
            testcase.set('time', f"{test.duration:.3f}")

            # Add failure/error information
            if test.outcome == ExecutionOutcome.FAILED:
                failure = ET.SubElement(testcase, 'failure')
                failure.set('message', test.failure_message or 'Test failed')
                if test.failure_message:
                    failure.text = test.failure_message

            elif test.outcome == ExecutionOutcome.ERROR:
                error = ET.SubElement(testcase, 'error')
                error.set('message', test.error_message or 'Test error')
                if test.error_message:
                    error.text = test.error_message

            elif test.outcome == ExecutionOutcome.SKIPPED:
                skipped = ET.SubElement(testcase, 'skipped')
                skipped.set('message', 'Test skipped')

            elif test.outcome == ExecutionOutcome.TIMEOUT:
                error = ET.SubElement(testcase, 'error')
                error.set('message', 'Test timed out')
                error.set('type', 'timeout')

            elif test.outcome == ExecutionOutcome.CRASHED:
                error = ET.SubElement(testcase, 'error')
                error.set('message', 'Test crashed')
                error.set('type', 'crash')
                if test.crash_info:
                    error.text = str(test.crash_info)

        # Write XML with proper formatting
        rough_string = ET.tostring(testsuite, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent='  ')

        # Remove empty lines and write
        lines = [line for line in pretty_xml.split('\n') if line.strip()]
        xml_content = '\n'.join(lines)

        atomic_write(file_path, xml_content)
        logger.debug(f"Exported JUnit XML results to {file_path}")


# Global result collector
_result_collector: Optional[ResultCollector] = None


def get_result_collector() -> ResultCollector:
    """Get or create global result collector."""
    global _result_collector
    if _result_collector is None:
        _result_collector = ResultCollector()
    return _result_collector


def record_test_result(name: str, outcome: ExecutionOutcome, duration: float, **kwargs) -> None:
    """Record a test result using global collector."""
    get_result_collector().record_test(name, outcome, duration, **kwargs)


def finalize_results() -> SuiteExecutionResults:
    """Finalize results using global collector."""
    return get_result_collector().finalize_results()


def export_results(formats: List[str], output_dir: Path) -> Dict[str, Path]:
    """Export results using global collector."""
    return get_result_collector().export_results(formats, output_dir)

