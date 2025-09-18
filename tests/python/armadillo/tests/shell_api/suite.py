"""Shell API test suite configuration for Armadillo framework.

This module defines the shell_api test suite, converted from the JavaScript
framework's shell_api test suite defined in js/client/modules/@arangodb/testsuites/aql.js
"""

from pathlib import Path
from typing import List

from armadillo.test_management import (
    SuiteOrganizer, Suite, SuiteConfig, SuitePriority,
    Selector, FilterOperation, create_pattern_selector
)


def create_shell_api_suite() -> Suite:
    """Create the shell_api test suite.

    This mirrors the JavaScript shell_api test suite which runs tests from:
    tests/js/client/shell/api

    Returns:
        Configured Suite for shell API tests
    """
    config = SuiteConfig(
        name="shell_api",
        description="Shell client tests - API endpoints and functionality",
        priority=SuitePriority.NORMAL,
        tags={"shell", "api", "client", "converted_from_js"},

        # Configuration from original JS suite
        timeout=300.0,  # 5 minutes timeout for API tests
        max_parallel=4,  # Can run multiple API tests in parallel
        requires_isolation=False,  # API tests don't need full isolation
        setup_timeout=60.0,
        teardown_timeout=30.0,

        # Resource requirements - API tests are lightweight
        min_memory_mb=256,
        max_cpu_cores=2,
        requires_network=True,  # API tests need network access to server
        requires_filesystem=False,  # No special filesystem requirements

        # Custom metadata
        metadata={
            "converted_from": "js/client/modules/@arangodb/testsuites/aql.js:shellApiClient",
            "original_test_path": "tests/js/client/shell/api",
            "python_test_path": "tests/shell_api",
            "framework_version": "1.0.0",
            "test_categories": ["api", "statistics", "endpoints"]
        }
    )

    # Create selector for shell API tests
    # Select all test files in the shell_api directory
    selector = create_pattern_selector(
        include_patterns=["**/shell_api/**"]
    )

    suite = Suite(config=config, selector=selector)
    return suite


def create_shell_api_organizer() -> SuiteOrganizer:
    """Create a test suite organizer for shell API tests.

    Returns:
        Configured SuiteOrganizer with shell API suites
    """
    organizer = SuiteOrganizer()

    # Add main shell API suite
    shell_api_suite = create_shell_api_suite()
    organizer.add_suite(shell_api_suite)

    # Create specialized sub-suites for different test categories

    # Statistics API tests
    statistics_config = SuiteConfig(
        name="shell_api.statistics",
        description="Statistics API endpoint tests",
        priority=SuitePriority.HIGH,  # Statistics are important
        tags={"shell", "api", "statistics", "admin_endpoints"},
        timeout=120.0,
        metadata={
            "test_file": "test_statistics.py",
            "endpoints_tested": [
                "/_admin/statistics",
                "/_admin/statistics-description"
            ]
        }
    )

    statistics_selector = create_pattern_selector(
        include_patterns=["**/test_statistics.py"]
    )

    statistics_suite = Suite(config=statistics_config, selector=statistics_selector)

    # Add as child of main shell API suite
    shell_api_suite.add_child(statistics_suite)
    organizer.add_suite(statistics_suite)

    # TODO: Add more sub-suites as we convert more tests:
    # - Version API tests
    # - Database API tests
    # - Collection API tests
    # - etc.

    return organizer


def get_shell_api_test_paths() -> List[Path]:
    """Get list of test file paths for shell API tests.

    Returns:
        List of Path objects pointing to test files
    """
    base_path = Path(__file__).parent
    test_files = []

    # Collect all test_*.py files in this directory
    for test_file in base_path.glob("test_*.py"):
        test_files.append(test_file)

    return test_files


# Convenience function for quick test suite creation
def setup_shell_api_tests() -> SuiteOrganizer:
    """Set up and configure shell API test suite.

    This is the main entry point for setting up shell API tests
    in the Armadillo framework.

    Returns:
        Ready-to-use SuiteOrganizer with shell API tests configured
    """
    organizer = create_shell_api_organizer()

    # Get test files and collect tests (would be done by framework)
    test_files = get_shell_api_test_paths()

    # In a real scenario, the framework would:
    # 1. Discover test files using pytest
    # 2. Collect test items
    # 3. Organize them using our selector
    # 4. Execute according to suite configuration

    return organizer


if __name__ == "__main__":
    # Demo the shell API suite setup
    organizer = setup_shell_api_tests()

    print("Shell API Test Suite Configuration:")
    print("=" * 50)

    summary = organizer.export_summary()

    print(f"Total suites: {summary['statistics']['total_suites']}")
    print(f"Root suites: {summary['statistics']['root_suites']}")
    print(f"Execution order: {summary['execution_order']}")

    print("\nSuites:")
    for suite_name, suite_info in summary['suites'].items():
        suite = organizer.get_suite(suite_name)
        description = suite.config.description if suite else "No description"
        print(f"  - {suite_name}: {description}")
        if suite_info['tags']:
            print(f"    Tags: {', '.join(suite_info['tags'])}")
        if suite_info['children_count'] > 0:
            print(f"    Children: {suite_info['children_count']}")

    print(f"\nHierarchy: {summary['hierarchy']}")

    validation_errors = summary['validation_errors']
    if validation_errors:
        print(f"\nValidation errors: {validation_errors}")
    else:
        print("\n✅ All suite validations passed!")
