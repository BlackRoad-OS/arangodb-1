"""Advanced test selection and filtering for Armadillo framework."""
import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Pattern, Callable, Any
from pathlib import Path
import pytest
from pytest import Item as PytestItem
from ..core.log import get_logger
logger = get_logger(__name__)

class FilterType(Enum):
    """Types of test filters available."""
    MARKER = 'marker'
    PATTERN = 'pattern'
    TAG = 'tag'
    PATH = 'path'
    CUSTOM = 'custom'

class FilterOperation(Enum):
    """Filter operations for combining criteria."""
    INCLUDE = 'include'
    EXCLUDE = 'exclude'
    REQUIRE = 'require'

@dataclass
class FilterCriteria:
    """Criteria for filtering tests."""
    filter_type: FilterType
    operation: FilterOperation
    value: str
    pattern: Optional[Pattern[str]] = None

    def __post_init__(self):
        """Compile regex patterns if needed."""
        if self.filter_type in [FilterType.PATTERN, FilterType.PATH] and self.pattern is None:
            if any((char in self.value for char in ['*', '?', '[', ']'])):
                regex_pattern = fnmatch.translate(self.value)
                self.pattern = re.compile(regex_pattern, re.IGNORECASE)
            else:
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
        return self.selected_count / self.total_collected * 100

class Filter:
    """Individual test filter with matching logic."""

    def __init__(self, criteria: FilterCriteria):
        self.criteria = criteria
        self.match_count = 0
        self.logger = get_logger(f'{__name__}.Filter')

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
                self.logger.warning('Unknown filter type: %s', self.criteria.filter_type)
                return False
        except Exception as e:
            self.logger.error('Error matching filter %s: %s', self.criteria.value, e)
            return False

    def _matches_marker(self, test_item: PytestItem) -> bool:
        """Check if test has specified marker."""
        return test_item.get_closest_marker(self.criteria.value) is not None

    def _matches_pattern(self, test_item: PytestItem) -> bool:
        """Check if test name matches pattern."""
        if self.criteria.pattern is None:
            return False
        test_name = test_item.name
        test_nodeid = test_item.nodeid
        return self.criteria.pattern.search(test_name) is not None or self.criteria.pattern.search(test_nodeid) is not None

    def _matches_tag(self, test_item: PytestItem) -> bool:
        """Check if test has specified tag in metadata."""
        test_func = getattr(test_item, 'function', None)
        if test_func and hasattr(test_func, '__tags__'):
            tags = getattr(test_func, '__tags__')
            if isinstance(tags, (list, set)) and self.criteria.value in tags:
                return True
            elif isinstance(tags, str) and self.criteria.value == tags:
                return True
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
        test_paths = []
        if hasattr(test_item, 'fspath') and test_item.fspath:
            test_paths.append(str(test_item.fspath))
        if hasattr(test_item, 'path') and test_item.path:
            test_paths.append(str(test_item.path))
        if test_item.nodeid:
            test_paths.append(test_item.nodeid)
        for path in test_paths:
            if self.criteria.pattern.search(path) is not None:
                return True
        return False

class Selector:
    """Advanced test selector with multiple filtering capabilities."""

    def __init__(self, logger_factory=None):
        """Initialize test selector.

        Args:
            logger_factory: Optional logger factory for dependency injection
        """
        if logger_factory:
            self.logger = logger_factory.create_logger('test_selector')
        else:
            self.logger = get_logger(__name__)
        self.filters: List[Filter] = []
        self.custom_filters: List[Callable[[PytestItem], bool]] = []

    def add_marker_filter(self, marker: str, operation: FilterOperation) -> 'Selector':
        """Add marker-based filter.

        Args:
            marker: Pytest marker name (e.g., 'slow', 'arango_cluster')
            operation: Include/exclude/require operation

        Returns:
            Self for chaining
        """
        criteria = FilterCriteria(FilterType.MARKER, operation, marker)
        filter_obj = Filter(criteria)
        self.filters.append(filter_obj)
        self.logger.debug("Added marker filter: %s '%s'", operation.value, marker)
        return self

    def add_pattern_filter(self, pattern: str, operation: FilterOperation) -> 'Selector':
        """Add pattern-based filter for test names.

        Args:
            pattern: Glob or regex pattern (e.g., 'test_auth_*', '.*integration.*')
            operation: Include/exclude/require operation

        Returns:
            Self for chaining
        """
        criteria = FilterCriteria(FilterType.PATTERN, operation, pattern)
        filter_obj = Filter(criteria)
        self.filters.append(filter_obj)
        self.logger.debug("Added pattern filter: %s '%s'", operation.value, pattern)
        return self

    def add_tag_filter(self, tag: str, operation: FilterOperation) -> 'Selector':
        """Add tag-based filter.

        Args:
            tag: Tag name (e.g., 'auth', 'collections', 'slow')
            operation: Include/exclude/require operation

        Returns:
            Self for chaining
        """
        criteria = FilterCriteria(FilterType.TAG, operation, tag)
        filter_obj = Filter(criteria)
        self.filters.append(filter_obj)
        self.logger.debug("Added tag filter: %s '%s'", operation.value, tag)
        return self

    def add_path_filter(self, path_pattern: str, operation: FilterOperation) -> 'Selector':
        """Add path-based filter for test file paths.

        Args:
            path_pattern: Path pattern (e.g., '*/auth/*', '**/*integration*')
            operation: Include/exclude/require operation

        Returns:
            Self for chaining
        """
        criteria = FilterCriteria(FilterType.PATH, operation, path_pattern)
        filter_obj = Filter(criteria)
        self.filters.append(filter_obj)
        self.logger.debug("Added path filter: %s '%s'", operation.value, path_pattern)
        return self

    def add_custom_filter(self, filter_func: Callable[[PytestItem], bool], operation: FilterOperation=FilterOperation.INCLUDE) -> 'Selector':
        """Add custom filter function.

        Args:
            filter_func: Function that takes PytestItem and returns bool
            operation: Include/exclude operation (require not supported for custom)

        Returns:
            Self for chaining
        """
        if operation == FilterOperation.EXCLUDE:
            wrapped_func = lambda item: not filter_func(item)
        else:
            wrapped_func = filter_func
        self.custom_filters.append(wrapped_func)
        self.logger.debug('Added custom filter: %s function', operation.value)
        return self

    def select_tests(self, collected_tests: List[PytestItem]) -> SelectionResult:
        """Select tests based on configured filters.

        Args:
            collected_tests: List of pytest test items

        Returns:
            Selection result with selected/excluded tests and statistics
        """
        self.logger.info('Selecting tests from %s collected tests', len(collected_tests))
        if not collected_tests:
            return SelectionResult([], [], 0)
        if not self.filters and (not self.custom_filters):
            self.logger.info('No filters configured, selecting all tests')
            return SelectionResult(collected_tests, [], len(collected_tests))
        selected_tests = []
        excluded_tests = []
        filter_stats = {}
        for test_item in collected_tests:
            if self._should_include_test(test_item, filter_stats):
                selected_tests.append(test_item)
            else:
                excluded_tests.append(test_item)
        selection_summary = {'total_collected': len(collected_tests), 'selected': len(selected_tests), 'excluded': len(excluded_tests), 'filters_applied': len(self.filters) + len(self.custom_filters)}
        result = SelectionResult(selected_tests=selected_tests, excluded_tests=excluded_tests, total_collected=len(collected_tests), selection_summary=selection_summary, filter_stats=filter_stats)
        self.logger.info('Test selection complete: %s/%s selected (%s%%)', result.selected_count, result.total_collected, result.selection_rate)
        return result

    def _should_include_test(self, test_item: PytestItem, filter_stats: Dict[str, Dict[str, int]]) -> bool:
        """Determine if test should be included based on all filters."""
        for filter_obj in self.filters:
            filter_key = f'{filter_obj.criteria.filter_type.value}_{filter_obj.criteria.operation.value}'
            if filter_key not in filter_stats:
                filter_stats[filter_key] = {'matches': 0, 'total': 0}
            filter_stats[filter_key]['total'] += 1
        include_matches = []
        exclude_matches = []
        require_matches = []
        for filter_obj in self.filters:
            matches = filter_obj.matches(test_item)
            if matches:
                filter_key = f'{filter_obj.criteria.filter_type.value}_{filter_obj.criteria.operation.value}'
                filter_stats[filter_key]['matches'] += 1
            if filter_obj.criteria.operation == FilterOperation.INCLUDE:
                include_matches.append(matches)
            elif filter_obj.criteria.operation == FilterOperation.EXCLUDE:
                exclude_matches.append(matches)
            elif filter_obj.criteria.operation == FilterOperation.REQUIRE:
                require_matches.append(matches)
        custom_include = True
        for custom_filter in self.custom_filters:
            if not custom_filter(test_item):
                custom_include = False
                break
        if any(exclude_matches):
            return False
        if require_matches and (not all(require_matches)):
            return False
        include_result = True
        if include_matches:
            include_result = any(include_matches)
        return include_result and custom_include

    def get_filter_summary(self) -> Dict[str, Any]:
        """Get summary of configured filters."""
        summary = {'total_filters': len(self.filters) + len(self.custom_filters), 'standard_filters': len(self.filters), 'custom_filters': len(self.custom_filters), 'filter_breakdown': {}}
        for filter_obj in self.filters:
            key = f'{filter_obj.criteria.filter_type.value}_{filter_obj.criteria.operation.value}'
            if key not in summary['filter_breakdown']:
                summary['filter_breakdown'][key] = []
            summary['filter_breakdown'][key].append(filter_obj.criteria.value)
        return summary

    def clear_filters(self) -> 'Selector':
        """Clear all configured filters.

        Returns:
            Self for chaining
        """
        self.filters.clear()
        self.custom_filters.clear()
        self.logger.debug('Cleared all filters')
        return self

def create_marker_selector(include_markers: List[str]=None, exclude_markers: List[str]=None, require_markers: List[str]=None) -> Selector:
    """Create a test selector with marker-based filters.

    Args:
        include_markers: Markers to include (OR logic)
        exclude_markers: Markers to exclude (OR logic)
        require_markers: Markers that must be present (AND logic)

    Returns:
        Configured Selector
    """
    selector = Selector()
    for marker in include_markers or []:
        selector.add_marker_filter(marker, FilterOperation.INCLUDE)
    for marker in exclude_markers or []:
        selector.add_marker_filter(marker, FilterOperation.EXCLUDE)
    for marker in require_markers or []:
        selector.add_marker_filter(marker, FilterOperation.REQUIRE)
    return selector

def create_pattern_selector(include_patterns: List[str]=None, exclude_patterns: List[str]=None) -> Selector:
    """Create a test selector with pattern-based filters.

    Args:
        include_patterns: Name patterns to include
        exclude_patterns: Name patterns to exclude

    Returns:
        Configured Selector
    """
    selector = Selector()
    for pattern in include_patterns or []:
        selector.add_pattern_filter(pattern, FilterOperation.INCLUDE)
    for pattern in exclude_patterns or []:
        selector.add_pattern_filter(pattern, FilterOperation.EXCLUDE)
    return selector

def create_suite_selector(suite_name: str) -> Selector:
    """Create a test selector for a specific test suite.

    Args:
        suite_name: Name of the test suite

    Returns:
        Configured Selector
    """
    return Selector().add_tag_filter(suite_name, FilterOperation.REQUIRE)