"""Test suite organization and management for Armadillo framework."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Any, Callable, Union
from pathlib import Path
import re

import pytest
from pytest import Item as PytestItem

from .selector import Selector, FilterOperation, create_marker_selector, create_pattern_selector
from ..core.log import get_logger

logger = get_logger(__name__)


class SuitePriority(Enum):
    """Priority levels for suite execution ordering."""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    DEFERRED = 5


class SuiteStatus(Enum):
    """Status of suite execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class SuiteConfig:
    """Configuration for test suite behavior and execution."""
    name: str
    description: str = ""
    priority: SuitePriority = SuitePriority.NORMAL
    tags: Set[str] = field(default_factory=set)

    # Execution configuration
    timeout: Optional[float] = None
    max_parallel: Optional[int] = None
    requires_isolation: bool = False
    setup_timeout: float = 60.0
    teardown_timeout: float = 30.0

    # Dependencies
    depends_on: List[str] = field(default_factory=list)
    conflicts_with: List[str] = field(default_factory=list)

    # Resource requirements
    min_memory_mb: Optional[int] = None
    max_cpu_cores: Optional[int] = None
    requires_network: bool = False
    requires_filesystem: bool = False

    # Execution hooks (callable names or functions)
    setup_hooks: List[Union[str, Callable]] = field(default_factory=list)
    teardown_hooks: List[Union[str, Callable]] = field(default_factory=list)

    # Custom metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_tag(self, tag: str) -> 'SuiteConfig':
        """Add a tag to this suite configuration.

        Args:
            tag: Tag to add

        Returns:
            Self for chaining
        """
        self.tags.add(tag)
        return self

    def add_dependency(self, suite_name: str) -> 'SuiteConfig':
        """Add a dependency on another suite.

        Args:
            suite_name: Name of suite this depends on

        Returns:
            Self for chaining
        """
        if suite_name not in self.depends_on:
            self.depends_on.append(suite_name)
        return self

    def add_conflict(self, suite_name: str) -> 'SuiteConfig':
        """Add a conflict with another suite.

        Args:
            suite_name: Name of suite this conflicts with

        Returns:
            Self for chaining
        """
        if suite_name not in self.conflicts_with:
            self.conflicts_with.append(suite_name)
        return self

    def has_tag(self, tag: str) -> bool:
        """Check if suite has a specific tag."""
        return tag in self.tags

    def is_compatible_with(self, other: 'SuiteConfig') -> bool:
        """Check if this suite is compatible with another suite."""
        return (other.name not in self.conflicts_with and
                self.name not in other.conflicts_with)


@dataclass
class Suite:
    """A logical grouping of tests with associated metadata and configuration."""
    config: SuiteConfig
    selector: Selector
    tests: List[PytestItem] = field(default_factory=list)
    status: SuiteStatus = SuiteStatus.PENDING

    # Execution results
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0

    # Hierarchy
    parent: Optional['Suite'] = None
    children: List['Suite'] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Get the suite name."""
        return self.config.name

    @property
    def test_count(self) -> int:
        """Get the number of tests in this suite."""
        return len(self.tests)

    @property
    def total_tests(self) -> int:
        """Get the total number of tests including children."""
        total = self.test_count
        for child in self.children:
            total += child.total_tests
        return total

    @property
    def duration(self) -> Optional[float]:
        """Get the execution duration if available."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None

    @property
    def success_rate(self) -> float:
        """Get the success rate as a percentage."""
        if self.test_count == 0:
            return 0.0
        return (self.passed / self.test_count) * 100

    def collect_tests(self, all_tests: List[PytestItem]) -> 'Suite':
        """Collect tests for this suite using the configured selector.

        Args:
            all_tests: All available test items

        Returns:
            Self for chaining
        """
        selection_result = self.selector.select_tests(all_tests)
        self.tests = selection_result.selected_tests

        logger.debug(f"Suite '{self.name}' collected {len(self.tests)} tests")
        return self

    def add_child(self, child_suite: 'Suite') -> 'Suite':
        """Add a child suite.

        Args:
            child_suite: Child suite to add

        Returns:
            Self for chaining
        """
        if child_suite not in self.children:
            self.children.append(child_suite)
            child_suite.parent = self
        return self

    def remove_child(self, child_suite: 'Suite') -> 'Suite':
        """Remove a child suite.

        Args:
            child_suite: Child suite to remove

        Returns:
            Self for chaining
        """
        if child_suite in self.children:
            self.children.remove(child_suite)
            child_suite.parent = None
        return self

    def get_all_tests(self) -> List[PytestItem]:
        """Get all tests from this suite and its children."""
        all_tests = list(self.tests)
        for child in self.children:
            all_tests.extend(child.get_all_tests())
        return all_tests

    def get_path(self) -> List[str]:
        """Get the hierarchical path to this suite."""
        if self.parent:
            return self.parent.get_path() + [self.name]
        return [self.name]

    def get_full_name(self) -> str:
        """Get the full hierarchical name."""
        return ".".join(self.get_path())

    def matches_criteria(self, criteria: Dict[str, Any]) -> bool:
        """Check if suite matches given criteria.

        Args:
            criteria: Dictionary of criteria to check

        Returns:
            True if suite matches all criteria
        """
        # Check tags
        if 'tags' in criteria:
            required_tags = set(criteria['tags']) if isinstance(criteria['tags'], (list, set)) else {criteria['tags']}
            if not required_tags.issubset(self.config.tags):
                return False

        # Check priority
        if 'priority' in criteria:
            if self.config.priority != criteria['priority']:
                return False

        # Check status
        if 'status' in criteria:
            if self.status != criteria['status']:
                return False

        # Check custom metadata
        if 'metadata' in criteria:
            for key, value in criteria['metadata'].items():
                if self.config.metadata.get(key) != value:
                    return False

        return True

    def summary(self) -> Dict[str, Any]:
        """Get a summary of this suite."""
        return {
            'name': self.name,
            'full_name': self.get_full_name(),
            'status': self.status.value,
            'test_count': self.test_count,
            'total_tests': self.total_tests,
            'passed': self.passed,
            'failed': self.failed,
            'skipped': self.skipped,
            'errors': self.errors,
            'success_rate': self.success_rate,
            'duration': self.duration,
            'priority': self.config.priority.value,
            'tags': list(self.config.tags),
            'children_count': len(self.children),
            'has_parent': self.parent is not None
        }


class SuiteOrganizer:
    """Organizes and manages test suites with hierarchy and dependencies."""

    def __init__(self, logger_factory=None):
        """Initialize test suite organizer.

        Args:
            logger_factory: Optional logger factory for dependency injection
        """
        if logger_factory:
            self.logger = logger_factory.create_logger("test_suite_organizer")
        else:
            self.logger = get_logger(__name__)

        self.suites: Dict[str, Suite] = {}
        self.root_suites: List[Suite] = []
        self.execution_order: List[str] = []

    def create_suite(self, config: SuiteConfig, selector: Selector = None) -> Suite:
        """Create a new test suite.

        Args:
            config: Suite configuration
            selector: Test selector (creates empty selector if None)

        Returns:
            Created test suite
        """
        if selector is None:
            selector = Selector()

        suite = Suite(config=config, selector=selector)
        self.add_suite(suite)

        self.logger.debug(f"Created suite: {config.name}")
        return suite

    def add_suite(self, suite: Suite) -> 'SuiteOrganizer':
        """Add a suite to the organizer.

        Args:
            suite: Suite to add

        Returns:
            Self for chaining
        """
        if suite.name in self.suites:
            self.logger.warning(f"Suite '{suite.name}' already exists, replacing")

        self.suites[suite.name] = suite

        # Add to root suites if no parent
        if suite.parent is None and suite not in self.root_suites:
            self.root_suites.append(suite)

        # Clear execution order cache
        self.execution_order.clear()

        self.logger.debug(f"Added suite: {suite.name}")
        return self

    def remove_suite(self, suite_name: str) -> bool:
        """Remove a suite from the organizer.

        Args:
            suite_name: Name of suite to remove

        Returns:
            True if suite was removed, False if not found
        """
        if suite_name not in self.suites:
            return False

        suite = self.suites[suite_name]

        # Remove from parent
        if suite.parent:
            suite.parent.remove_child(suite)
        else:
            # Remove from root suites
            if suite in self.root_suites:
                self.root_suites.remove(suite)

        # Handle children
        for child in suite.children[:]:  # Copy list to avoid modification during iteration
            child.parent = None
            if child not in self.root_suites:
                self.root_suites.append(child)

        del self.suites[suite_name]

        # Clear execution order cache
        self.execution_order.clear()

        self.logger.debug(f"Removed suite: {suite_name}")
        return True

    def get_suite(self, suite_name: str) -> Optional[Suite]:
        """Get a suite by name.

        Args:
            suite_name: Name of suite to get

        Returns:
            Suite if found, None otherwise
        """
        return self.suites.get(suite_name)

    def find_suites(self, criteria: Dict[str, Any]) -> List[Suite]:
        """Find suites matching given criteria.

        Args:
            criteria: Criteria to match against

        Returns:
            List of matching suites
        """
        matching_suites = []
        for suite in self.suites.values():
            if suite.matches_criteria(criteria):
                matching_suites.append(suite)
        return matching_suites

    def organize_by_markers(self, all_tests: List[PytestItem]) -> 'SuiteOrganizer':
        """Automatically organize tests into suites based on pytest markers.

        Args:
            all_tests: All available test items

        Returns:
            Self for chaining
        """
        # Collect all markers from tests
        markers = set()
        for test in all_tests:
            for marker in test.iter_markers():
                markers.add(marker.name)

        # Create suites for common markers
        common_markers = ['slow', 'fast', 'integration', 'unit', 'arango_single', 'arango_cluster']

        for marker in markers:
            if marker in common_markers:
                config = SuiteConfig(
                    name=f"{marker}_tests",
                    description=f"Tests marked with @pytest.mark.{marker}",
                    tags={marker, "auto_generated"}
                )

                selector = create_marker_selector(require_markers=[marker])
                suite = self.create_suite(config, selector)
                suite.collect_tests(all_tests)

                self.logger.debug(f"Auto-created suite '{marker}_tests' with {suite.test_count} tests")

        return self

    def organize_by_paths(self, all_tests: List[PytestItem]) -> 'SuiteOrganizer':
        """Automatically organize tests into suites based on file paths.

        Args:
            all_tests: All available test items

        Returns:
            Self for chaining
        """
        # Group tests by directory
        path_groups = {}

        for test in all_tests:
            test_path = None
            if hasattr(test, 'fspath'):
                test_path = Path(str(test.fspath))
            elif hasattr(test, 'path'):
                test_path = Path(str(test.path))
            elif test.nodeid:
                # Extract path from nodeid
                path_part = test.nodeid.split('::')[0]
                test_path = Path(path_part)

            if test_path:
                # Use parent directory as grouping key
                parent_dir = test_path.parent.name
                if parent_dir not in path_groups:
                    path_groups[parent_dir] = []
                path_groups[parent_dir].append(test)

        # Create suites for each path group
        for dir_name, tests in path_groups.items():
            if len(tests) >= 2:  # Only create suite if multiple tests
                config = SuiteConfig(
                    name=f"{dir_name}_suite",
                    description=f"Tests from {dir_name} directory",
                    tags={dir_name, "path_based", "auto_generated"}
                )

                selector = Selector()
                suite = Suite(config=config, selector=selector, tests=tests)
                self.add_suite(suite)

                self.logger.debug(f"Auto-created path suite '{dir_name}_suite' with {len(tests)} tests")

        return self

    def organize_hierarchical(self, separator: str = ".") -> 'SuiteOrganizer':
        """Organize suites into hierarchy based on names with separators.

        Args:
            separator: Character used to separate hierarchy levels

        Returns:
            Self for chaining
        """
        # Build hierarchy from suite names
        suite_hierarchy = {}

        for suite_name, suite in self.suites.items():
            parts = suite_name.split(separator)
            current_level = suite_hierarchy

            for i, part in enumerate(parts):
                if part not in current_level:
                    current_level[part] = {'suites': [], 'children': {}}

                if i == len(parts) - 1:
                    # This is the leaf level, add the suite
                    current_level[part]['suites'].append(suite)
                else:
                    # This is an intermediate level, go deeper
                    current_level = current_level[part]['children']

        # Create parent suites for hierarchy levels with multiple children
        def create_parent_suites(level_dict, parent_name="", level=0):
            for name, data in level_dict.items():
                current_name = f"{parent_name}{separator}{name}" if parent_name else name

                # If this level has children, create a parent suite
                if data['children'] and len(data['children']) > 1:
                    if current_name not in self.suites:
                        parent_config = SuiteConfig(
                            name=current_name,
                            description=f"Parent suite for {name} category",
                            tags={name, "parent_suite", "auto_generated"}
                        )
                        parent_suite = self.create_suite(parent_config, Selector())
                    else:
                        parent_suite = self.suites[current_name]

                    # Add child suites
                    for child_name, child_data in data['children'].items():
                        child_full_name = f"{current_name}{separator}{child_name}"
                        if child_full_name in self.suites:
                            child_suite = self.suites[child_full_name]
                            parent_suite.add_child(child_suite)
                            # Remove from root suites if it's there
                            if child_suite in self.root_suites:
                                self.root_suites.remove(child_suite)

                # Recurse to deeper levels
                create_parent_suites(data['children'], current_name, level + 1)

        create_parent_suites(suite_hierarchy)

        self.logger.debug("Organized suites into hierarchy")
        return self

    def calculate_execution_order(self) -> List[str]:
        """Calculate optimal execution order based on dependencies and priorities.

        Returns:
            List of suite names in execution order
        """
        if self.execution_order:
            return self.execution_order

        # Topological sort with priority consideration
        visited = set()
        temp_visited = set()
        execution_order = []

        def visit(suite_name: str):
            if suite_name in temp_visited:
                raise ValueError(f"Circular dependency detected involving suite: {suite_name}")
            if suite_name in visited:
                return

            temp_visited.add(suite_name)

            suite = self.suites.get(suite_name)
            if suite:
                # Visit dependencies first
                for dep_name in suite.config.depends_on:
                    if dep_name in self.suites:
                        visit(dep_name)

            temp_visited.remove(suite_name)
            visited.add(suite_name)
            execution_order.append(suite_name)

        # Sort suites by priority, then visit in order
        sorted_suites = sorted(
            self.suites.items(),
            key=lambda item: (item[1].config.priority.value, item[0])
        )

        for suite_name, _ in sorted_suites:
            if suite_name not in visited:
                visit(suite_name)

        self.execution_order = execution_order
        self.logger.debug(f"Calculated execution order: {execution_order}")
        return execution_order

    def validate_dependencies(self) -> List[str]:
        """Validate suite dependencies and return any issues found.

        Returns:
            List of validation error messages
        """
        errors = []

        for suite_name, suite in self.suites.items():
            # Check if dependencies exist
            for dep_name in suite.config.depends_on:
                if dep_name not in self.suites:
                    errors.append(f"Suite '{suite_name}' depends on non-existent suite '{dep_name}'")

            # Check for conflicts
            for conflict_name in suite.config.conflicts_with:
                if conflict_name in self.suites:
                    conflict_suite = self.suites[conflict_name]
                    if not suite.config.is_compatible_with(conflict_suite.config):
                        errors.append(f"Suite '{suite_name}' conflicts with '{conflict_name}'")

        # Check for circular dependencies
        try:
            self.calculate_execution_order()
        except ValueError as e:
            errors.append(str(e))

        return errors

    def collect_all_tests(self, all_tests: List[PytestItem]) -> 'SuiteOrganizer':
        """Collect tests for all suites.

        Args:
            all_tests: All available test items

        Returns:
            Self for chaining
        """
        for suite in self.suites.values():
            suite.collect_tests(all_tests)

        self.logger.info(f"Collected tests for {len(self.suites)} suites")
        return self

    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics about all suites.

        Returns:
            Dictionary containing statistics
        """
        total_suites = len(self.suites)
        total_tests = sum(suite.test_count for suite in self.suites.values())
        root_suites_count = len(self.root_suites)

        # Count by status
        status_counts = {}
        for status in SuiteStatus:
            status_counts[status.value] = sum(1 for s in self.suites.values() if s.status == status)

        # Count by priority
        priority_counts = {}
        for priority in SuitePriority:
            priority_counts[priority.value] = sum(1 for s in self.suites.values() if s.config.priority == priority)

        # Hierarchy depth
        max_depth = 0
        for suite in self.suites.values():
            depth = len(suite.get_path())
            max_depth = max(max_depth, depth)

        return {
            'total_suites': total_suites,
            'total_tests': total_tests,
            'root_suites': root_suites_count,
            'max_hierarchy_depth': max_depth,
            'status_distribution': status_counts,
            'priority_distribution': priority_counts,
            'has_dependencies': any(suite.config.depends_on for suite in self.suites.values()),
            'has_conflicts': any(suite.config.conflicts_with for suite in self.suites.values()),
            'execution_order_calculated': bool(self.execution_order)
        }

    def export_summary(self) -> Dict[str, Any]:
        """Export a comprehensive summary of all suites.

        Returns:
            Dictionary containing complete suite information
        """
        return {
            'statistics': self.get_statistics(),
            'execution_order': self.calculate_execution_order(),
            'validation_errors': self.validate_dependencies(),
            'suites': {name: suite.summary() for name, suite in self.suites.items()},
            'hierarchy': self._build_hierarchy_tree()
        }

    def _build_hierarchy_tree(self) -> Dict[str, Any]:
        """Build a tree representation of suite hierarchy."""
        def build_tree(suite: Suite) -> Dict[str, Any]:
            return {
                'name': suite.name,
                'test_count': suite.test_count,
                'status': suite.status.value,
                'children': [build_tree(child) for child in suite.children]
            }

        return {
            'roots': [build_tree(suite) for suite in self.root_suites]
        }


# Convenience functions for common suite patterns
def create_marker_suite(name: str, marker: str, description: str = "") -> Suite:
    """Create a suite based on a pytest marker.

    Args:
        name: Suite name
        marker: Pytest marker name
        description: Optional description

    Returns:
        Configured test suite
    """
    config = SuiteConfig(
        name=name,
        description=description or f"Tests marked with @pytest.mark.{marker}",
        tags={marker}
    )

    selector = create_marker_selector(require_markers=[marker])
    return Suite(config=config, selector=selector)


def create_pattern_suite(name: str, pattern: str, description: str = "") -> Suite:
    """Create a suite based on a test name pattern.

    Args:
        name: Suite name
        pattern: Test name pattern
        description: Optional description

    Returns:
        Configured test suite
    """
    config = SuiteConfig(
        name=name,
        description=description or f"Tests matching pattern: {pattern}",
        tags={"pattern_based"}
    )

    selector = create_pattern_selector(include_patterns=[pattern])
    return Suite(config=config, selector=selector)


def create_priority_suite(name: str, priority: SuitePriority,
                         selector: Selector, description: str = "") -> Suite:
    """Create a suite with specific priority.

    Args:
        name: Suite name
        priority: Execution priority
        selector: Test selector
        description: Optional description

    Returns:
        Configured test suite
    """
    config = SuiteConfig(
        name=name,
        description=description,
        priority=priority,
        tags={priority.name.lower()}
    )

    return Suite(config=config, selector=selector)
