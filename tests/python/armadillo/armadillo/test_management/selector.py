"""Advanced test selection and filtering for Armadillo framework."""

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Pattern, Callable, Any, Union
from pathlib import Path

import pytest
from pytest import Item as PytestItem

from ..core.log import get_logger

logger = get_logger(__name__)


class FilterType(Enum):
    """Types of test filters available."""
    MARKER = "marker"
    PATTERN = "pattern"
    TAG = "tag"
    PATH = "path"
    CUSTOM = "custom"


class FilterOperation(Enum):
    """Filter operations for combining criteria."""
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REQUIRE = "require"


@dataclass
class FilterCriteria:
    """Criteria for filtering tests."""
    filter_type: FilterType
    operation: FilterOperation
    value: str
    pattern: Optional[Pattern[str]] = None

    def __post_init__(self):
        """Compile regex patterns if needed."""
        if (self.filter_type in [FilterType.PATTERN, FilterType.PATH]) and self.pattern is None:
            # Convert glob pattern to regex if it contains glob characters
            if any(char in self.value for char in ['*', '?', '[', ']']):
                # Convert glob to regex
                regex_pattern = fnmatch.translate(self.value)
                self.pattern = re.compile(regex_pattern, re.IGNORECASE)
            else:
                # Treat as substring match
                self.pattern = re.compile(re.escape(self.value), re.IGNORECASE)


@dataclass
class SelectionResult:
    """Result of test selection process."""
    selected_tests: List[PytestItem]
    excluded_tests: List[PytestItem]
    total_collected: int
    selection_summary: Dict[str, int] = field(default_factory=dict)
    filter_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def selected_count(self) -> int:
        """Number of selected tests."""
        return len(self.selected_tests)

    @property
    def excluded_count(self) -> int:
        """Number of excluded tests."""
        return len(self.excluded_tests)

    @property
    def selection_rate(self) -> float:
        """Percentage of tests selected."""
        if self.total_collected == 0:
            return 0.0
        return (self.selected_count / self.total_collected) * 100


class TestFilter:
    """Individual test filter with matching logic."""

    def __init__(self, criteria: FilterCriteria):
        self.criteria = criteria
        self.match_count = 0
        self.logger = get_logger(f"{__name__}.TestFilter")

    def matches(self, test_item: PytestItem) -> bool:
        """Check if test item matches this filter."""
        try:
            if self.criteria.filter_type == FilterType.MARKER:
                return self._matches_marker(test_item)
            elif self.criteria.filter_type == FilterType.PATTERN:
                return self._matches_pattern(test_item)
            elif self.criteria.filter_type == FilterType.TAG:
                return self._matches_tag(test_item)
            elif self.criteria.filter_type == FilterType.PATH:
                return self._matches_path(test_item)
            else:
                self.logger.warning(f"Unknown filter type: {self.criteria.filter_type}")
                return False
        except Exception as e:
            self.logger.error(f"Error matching filter {self.criteria.value}: {e}")
            return False

    def _matches_marker(self, test_item: PytestItem) -> bool:
        """Check if test has specified marker."""
        return test_item.get_closest_marker(self.criteria.value) is not None

    def _matches_pattern(self, test_item: PytestItem) -> bool:
        """Check if test name matches pattern."""
        if self.criteria.pattern is None:
            return False

        # Check both test name and nodeid
        test_name = test_item.name
        test_nodeid = test_item.nodeid

        return (self.criteria.pattern.search(test_name) is not None or
                self.criteria.pattern.search(test_nodeid) is not None)

    def _matches_tag(self, test_item: PytestItem) -> bool:
        """Check if test has specified tag in metadata."""
        # Look for tags in various places:
        # 1. Test function attributes
        test_func = getattr(test_item, 'function', None)
        if test_func and hasattr(test_func, '__tags__'):
            tags = getattr(test_func, '__tags__')
            if isinstance(tags, (list, set)) and self.criteria.value in tags:
                return True
            elif isinstance(tags, str) and self.criteria.value == tags:
                return True

        # 2. Test markers (tags can be stored as marker arguments)
        for marker in test_item.iter_markers():
            if hasattr(marker, 'args') and self.criteria.value in marker.args:
                return True
            if hasattr(marker, 'kwargs') and 'tags' in marker.kwargs:
                marker_tags = marker.kwargs['tags']
                if isinstance(marker_tags, (list, set)) and self.criteria.value in marker_tags:
                    return True

        return False

    def _matches_path(self, test_item: PytestItem) -> bool:
        """Check if test path matches pattern."""
        if self.criteria.pattern is None:
            return False

        # Get path from various sources
        test_paths = []

        # Try fspath attribute (pytest < 7.0)
        if hasattr(test_item, 'fspath') and test_item.fspath:
            test_paths.append(str(test_item.fspath))

        # Try path attribute (pytest >= 7.0)
        if hasattr(test_item, 'path') and test_item.path:
            test_paths.append(str(test_item.path))

        # Fallback to nodeid
        if test_item.nodeid:
            test_paths.append(test_item.nodeid)

        # Check if pattern matches any of the paths
        for path in test_paths:
            if self.criteria.pattern.search(path) is not None:
                return True

        return False


class TestSelector:
    """Advanced test selector with multiple filtering capabilities."""

    def __init__(self, logger_factory=None):
        """Initialize test selector.

        Args:
            logger_factory: Optional logger factory for dependency injection
        """
        if logger_factory:
            self.logger = logger_factory.create_logger("test_selector")
        else:
            self.logger = get_logger(__name__)

        self.filters: List[TestFilter] = []
        self.custom_filters: List[Callable[[PytestItem], bool]] = []

    def add_marker_filter(self, marker: str, operation: FilterOperation) -> 'TestSelector':
        """Add marker-based filter.

        Args:
            marker: Pytest marker name (e.g., 'slow', 'arango_cluster')
            operation: Include/exclude/require operation

        Returns:
            Self for chaining
        """
        criteria = FilterCriteria(FilterType.MARKER, operation, marker)
        filter_obj = TestFilter(criteria)
        self.filters.append(filter_obj)

        self.logger.debug(f"Added marker filter: {operation.value} '{marker}'")
        return self

    def add_pattern_filter(self, pattern: str, operation: FilterOperation) -> 'TestSelector':
        """Add pattern-based filter for test names.

        Args:
            pattern: Glob or regex pattern (e.g., 'test_auth_*', '.*integration.*')
            operation: Include/exclude/require operation

        Returns:
            Self for chaining
        """
        criteria = FilterCriteria(FilterType.PATTERN, operation, pattern)
        filter_obj = TestFilter(criteria)
        self.filters.append(filter_obj)

        self.logger.debug(f"Added pattern filter: {operation.value} '{pattern}'")
        return self

    def add_tag_filter(self, tag: str, operation: FilterOperation) -> 'TestSelector':
        """Add tag-based filter.

        Args:
            tag: Tag name (e.g., 'auth', 'collections', 'slow')
            operation: Include/exclude/require operation

        Returns:
            Self for chaining
        """
        criteria = FilterCriteria(FilterType.TAG, operation, tag)
        filter_obj = TestFilter(criteria)
        self.filters.append(filter_obj)

        self.logger.debug(f"Added tag filter: {operation.value} '{tag}'")
        return self

    def add_path_filter(self, path_pattern: str, operation: FilterOperation) -> 'TestSelector':
        """Add path-based filter for test file paths.

        Args:
            path_pattern: Path pattern (e.g., '*/auth/*', '**/*integration*')
            operation: Include/exclude/require operation

        Returns:
            Self for chaining
        """
        criteria = FilterCriteria(FilterType.PATH, operation, path_pattern)
        filter_obj = TestFilter(criteria)
        self.filters.append(filter_obj)

        self.logger.debug(f"Added path filter: {operation.value} '{path_pattern}'")
        return self

    def add_custom_filter(self, filter_func: Callable[[PytestItem], bool],
                         operation: FilterOperation = FilterOperation.INCLUDE) -> 'TestSelector':
        """Add custom filter function.

        Args:
            filter_func: Function that takes PytestItem and returns bool
            operation: Include/exclude operation (require not supported for custom)

        Returns:
            Self for chaining
        """
        # Wrap custom function to respect operation
        if operation == FilterOperation.EXCLUDE:
            wrapped_func = lambda item: not filter_func(item)
        else:
            wrapped_func = filter_func

        self.custom_filters.append(wrapped_func)

        self.logger.debug(f"Added custom filter: {operation.value} function")
        return self

    def select_tests(self, collected_tests: List[PytestItem]) -> SelectionResult:
        """Select tests based on configured filters.

        Args:
            collected_tests: List of pytest test items

        Returns:
            Selection result with selected/excluded tests and statistics
        """
        self.logger.info(f"Selecting tests from {len(collected_tests)} collected tests")

        if not collected_tests:
            return SelectionResult([], [], 0)

        if not self.filters and not self.custom_filters:
            # No filters, select all tests
            self.logger.info("No filters configured, selecting all tests")
            return SelectionResult(collected_tests, [], len(collected_tests))

        selected_tests = []
        excluded_tests = []
        filter_stats = {}

        for test_item in collected_tests:
            if self._should_include_test(test_item, filter_stats):
                selected_tests.append(test_item)
            else:
                excluded_tests.append(test_item)

        # Generate summary statistics
        selection_summary = {
            'total_collected': len(collected_tests),
            'selected': len(selected_tests),
            'excluded': len(excluded_tests),
            'filters_applied': len(self.filters) + len(self.custom_filters)
        }

        result = SelectionResult(
            selected_tests=selected_tests,
            excluded_tests=excluded_tests,
            total_collected=len(collected_tests),
            selection_summary=selection_summary,
            filter_stats=filter_stats
        )

        self.logger.info(
            f"Test selection complete: {result.selected_count}/{result.total_collected} "
            f"selected ({result.selection_rate:.1f}%)"
        )

        return result

    def _should_include_test(self, test_item: PytestItem, filter_stats: Dict[str, Dict[str, int]]) -> bool:
        """Determine if test should be included based on all filters."""
        # Track filter statistics
        for filter_obj in self.filters:
            filter_key = f"{filter_obj.criteria.filter_type.value}_{filter_obj.criteria.operation.value}"
            if filter_key not in filter_stats:
                filter_stats[filter_key] = {'matches': 0, 'total': 0}
            filter_stats[filter_key]['total'] += 1

        # Apply inclusion filters first
        include_matches = []
        exclude_matches = []
        require_matches = []

        for filter_obj in self.filters:
            matches = filter_obj.matches(test_item)
            if matches:
                filter_key = f"{filter_obj.criteria.filter_type.value}_{filter_obj.criteria.operation.value}"
                filter_stats[filter_key]['matches'] += 1

            if filter_obj.criteria.operation == FilterOperation.INCLUDE:
                include_matches.append(matches)
            elif filter_obj.criteria.operation == FilterOperation.EXCLUDE:
                exclude_matches.append(matches)
            elif filter_obj.criteria.operation == FilterOperation.REQUIRE:
                require_matches.append(matches)

        # Apply custom filters
        custom_include = True
        for custom_filter in self.custom_filters:
            if not custom_filter(test_item):
                custom_include = False
                break

        # Decision logic:
        # 1. If any EXCLUDE filter matches, exclude the test
        if any(exclude_matches):
            return False

        # 2. If there are REQUIRE filters, ALL must match
        if require_matches and not all(require_matches):
            return False

        # 3. If there are INCLUDE filters, at least one must match
        # If no INCLUDE filters, then include by default (unless excluded above)
        include_result = True
        if include_matches:
            include_result = any(include_matches)

        # 4. Apply custom filters
        return include_result and custom_include

    def get_filter_summary(self) -> Dict[str, Any]:
        """Get summary of configured filters."""
        summary = {
            'total_filters': len(self.filters) + len(self.custom_filters),
            'standard_filters': len(self.filters),
            'custom_filters': len(self.custom_filters),
            'filter_breakdown': {}
        }

        # Group filters by type and operation
        for filter_obj in self.filters:
            key = f"{filter_obj.criteria.filter_type.value}_{filter_obj.criteria.operation.value}"
            if key not in summary['filter_breakdown']:
                summary['filter_breakdown'][key] = []
            summary['filter_breakdown'][key].append(filter_obj.criteria.value)

        return summary

    def clear_filters(self) -> 'TestSelector':
        """Clear all configured filters.

        Returns:
            Self for chaining
        """
        self.filters.clear()
        self.custom_filters.clear()
        self.logger.debug("Cleared all filters")
        return self


# Convenience functions for common filter patterns
def create_marker_selector(include_markers: List[str] = None,
                          exclude_markers: List[str] = None,
                          require_markers: List[str] = None) -> TestSelector:
    """Create a test selector with marker-based filters.

    Args:
        include_markers: Markers to include (OR logic)
        exclude_markers: Markers to exclude (OR logic)
        require_markers: Markers that must be present (AND logic)

    Returns:
        Configured TestSelector
    """
    selector = TestSelector()

    for marker in include_markers or []:
        selector.add_marker_filter(marker, FilterOperation.INCLUDE)

    for marker in exclude_markers or []:
        selector.add_marker_filter(marker, FilterOperation.EXCLUDE)

    for marker in require_markers or []:
        selector.add_marker_filter(marker, FilterOperation.REQUIRE)

    return selector


def create_pattern_selector(include_patterns: List[str] = None,
                           exclude_patterns: List[str] = None) -> TestSelector:
    """Create a test selector with pattern-based filters.

    Args:
        include_patterns: Name patterns to include
        exclude_patterns: Name patterns to exclude

    Returns:
        Configured TestSelector
    """
    selector = TestSelector()

    for pattern in include_patterns or []:
        selector.add_pattern_filter(pattern, FilterOperation.INCLUDE)

    for pattern in exclude_patterns or []:
        selector.add_pattern_filter(pattern, FilterOperation.EXCLUDE)

    return selector


def create_suite_selector(suite_name: str) -> TestSelector:
    """Create a test selector for a specific test suite.

    Args:
        suite_name: Name of the test suite

    Returns:
        Configured TestSelector
    """
    return TestSelector().add_tag_filter(suite_name, FilterOperation.REQUIRE)
