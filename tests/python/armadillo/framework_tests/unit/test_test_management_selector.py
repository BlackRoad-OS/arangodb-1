"""Unit tests for test management selector."""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

from armadillo.test_management.selector import (
    TestSelector, TestFilter, FilterCriteria, SelectionResult,
    FilterType, FilterOperation,
    create_marker_selector, create_pattern_selector, create_suite_selector
)


class TestFilterCriteria:
    """Test FilterCriteria functionality."""
    
    def test_filter_criteria_creation(self):
        """Test basic filter criteria creation."""
        criteria = FilterCriteria(FilterType.MARKER, FilterOperation.INCLUDE, "slow")
        
        assert criteria.filter_type == FilterType.MARKER
        assert criteria.operation == FilterOperation.INCLUDE
        assert criteria.value == "slow"
        assert criteria.pattern is None
    
    def test_pattern_criteria_with_glob(self):
        """Test pattern criteria with glob patterns."""
        criteria = FilterCriteria(FilterType.PATTERN, FilterOperation.INCLUDE, "test_auth_*")
        
        assert criteria.pattern is not None
        assert criteria.pattern.pattern  # Compiled regex exists
    
    def test_pattern_criteria_with_substring(self):
        """Test pattern criteria with simple substring."""
        criteria = FilterCriteria(FilterType.PATTERN, FilterOperation.INCLUDE, "integration")
        
        assert criteria.pattern is not None
        # Should match strings containing 'integration'
        assert criteria.pattern.search("test_integration_auth") is not None
        assert criteria.pattern.search("other_test") is None


class TestTestFilter:
    """Test TestFilter functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.mock_test_item = Mock()
        self.mock_test_item.name = "test_user_authentication"
        self.mock_test_item.nodeid = "tests/auth/test_user.py::test_user_authentication"
        self.mock_test_item.fspath = Path("tests/auth/test_user.py")
    
    def test_marker_filter_matching(self):
        """Test marker-based filtering."""
        criteria = FilterCriteria(FilterType.MARKER, FilterOperation.INCLUDE, "slow")
        filter_obj = TestFilter(criteria)
        
        # Mock marker presence
        self.mock_test_item.get_closest_marker.return_value = Mock()  # Marker exists
        assert filter_obj.matches(self.mock_test_item) is True
        
        self.mock_test_item.get_closest_marker.return_value = None  # No marker
        assert filter_obj.matches(self.mock_test_item) is False
    
    def test_pattern_filter_matching(self):
        """Test pattern-based filtering."""
        criteria = FilterCriteria(FilterType.PATTERN, FilterOperation.INCLUDE, "*auth*")
        filter_obj = TestFilter(criteria)
        
        # Should match both test name and nodeid containing 'auth'
        assert filter_obj.matches(self.mock_test_item) is True
        
        # Change to non-matching name
        self.mock_test_item.name = "test_collections_create"
        self.mock_test_item.nodeid = "tests/collections/test_create.py::test_collections_create"
        assert filter_obj.matches(self.mock_test_item) is False
    
    def test_tag_filter_matching(self):
        """Test tag-based filtering."""
        criteria = FilterCriteria(FilterType.TAG, FilterOperation.INCLUDE, "auth")
        filter_obj = TestFilter(criteria)
        
        # Mock test function with tags
        mock_function = Mock()
        mock_function.__tags__ = ["auth", "security"]
        self.mock_test_item.function = mock_function
        
        assert filter_obj.matches(self.mock_test_item) is True
        
        # Test with different tag
        mock_function.__tags__ = ["collections", "crud"]
        assert filter_obj.matches(self.mock_test_item) is False
    
    def test_path_filter_matching(self):
        """Test path-based filtering."""
        criteria = FilterCriteria(FilterType.PATH, FilterOperation.INCLUDE, "*/auth/*")
        filter_obj = TestFilter(criteria)
        
        assert filter_obj.matches(self.mock_test_item) is True
        
        # Change to non-matching path
        self.mock_test_item.fspath = Path("tests/collections/test_create.py")
        self.mock_test_item.nodeid = "tests/collections/test_create.py::test_create_collection"
        assert filter_obj.matches(self.mock_test_item) is False


class TestSelectionResult:
    """Test SelectionResult functionality."""
    
    def test_selection_result_properties(self):
        """Test selection result properties and calculations."""
        selected_tests = [Mock() for _ in range(3)]
        excluded_tests = [Mock() for _ in range(2)]
        total_collected = 5
        
        result = SelectionResult(selected_tests, excluded_tests, total_collected)
        
        assert result.selected_count == 3
        assert result.excluded_count == 2
        assert result.total_collected == 5
        assert result.selection_rate == 60.0  # 3/5 * 100
    
    def test_empty_selection_result(self):
        """Test selection result with no tests."""
        result = SelectionResult([], [], 0)
        
        assert result.selected_count == 0
        assert result.excluded_count == 0
        assert result.selection_rate == 0.0


class TestTestSelector:
    """Test TestSelector functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.selector = TestSelector()
        
        # Create mock test items
        self.test_items = []
        
        # Auth test with slow marker
        auth_test = Mock()
        auth_test.name = "test_user_login"
        auth_test.nodeid = "tests/auth/test_user.py::test_user_login"
        auth_test.fspath = Path("tests/auth/test_user.py")
        auth_test.get_closest_marker = lambda name: Mock() if name == "slow" else None
        auth_test.iter_markers = lambda: [Mock(args=["auth"], kwargs={})]
        self.test_items.append(auth_test)
        
        # Collections test without markers
        collections_test = Mock()
        collections_test.name = "test_create_collection"
        collections_test.nodeid = "tests/collections/test_crud.py::test_create_collection"
        collections_test.fspath = Path("tests/collections/test_crud.py")
        collections_test.get_closest_marker = lambda name: None
        collections_test.iter_markers = lambda: [Mock(args=["collections"], kwargs={})]
        self.test_items.append(collections_test)
        
        # Integration test with cluster marker
        integration_test = Mock()
        integration_test.name = "test_cluster_setup"
        integration_test.nodeid = "tests/integration/test_cluster.py::test_cluster_setup"
        integration_test.fspath = Path("tests/integration/test_cluster.py")
        integration_test.get_closest_marker = lambda name: Mock() if name == "arango_cluster" else None
        integration_test.iter_markers = lambda: [Mock(args=["integration"], kwargs={})]
        self.test_items.append(integration_test)
    
    def test_no_filters_selects_all(self):
        """Test that no filters means all tests are selected."""
        result = self.selector.select_tests(self.test_items)
        
        assert result.selected_count == len(self.test_items)
        assert result.excluded_count == 0
        assert result.selection_rate == 100.0
    
    def test_marker_include_filter(self):
        """Test marker inclusion filter."""
        self.selector.add_marker_filter("slow", FilterOperation.INCLUDE)
        result = self.selector.select_tests(self.test_items)
        
        # Only the auth test has the slow marker
        assert result.selected_count == 1
        assert result.excluded_count == 2
        assert "test_user_login" in [t.name for t in result.selected_tests]
    
    def test_marker_exclude_filter(self):
        """Test marker exclusion filter."""
        self.selector.add_marker_filter("slow", FilterOperation.EXCLUDE)
        result = self.selector.select_tests(self.test_items)
        
        # Should exclude the slow test
        assert result.selected_count == 2
        assert result.excluded_count == 1
        assert "test_user_login" not in [t.name for t in result.selected_tests]
    
    def test_pattern_filter(self):
        """Test pattern-based filtering."""
        self.selector.add_pattern_filter("*auth*", FilterOperation.INCLUDE)
        result = self.selector.select_tests(self.test_items)
        
        # Only tests with 'auth' in path/name
        assert result.selected_count == 1
        assert "test_user_login" in [t.name for t in result.selected_tests]
    
    def test_path_filter(self):
        """Test path-based filtering."""
        self.selector.add_path_filter("*/integration/*", FilterOperation.INCLUDE)
        result = self.selector.select_tests(self.test_items)
        
        # Only integration tests
        assert result.selected_count == 1
        assert "test_cluster_setup" in [t.name for t in result.selected_tests]
    
    def test_multiple_filters_and_logic(self):
        """Test multiple filters with AND logic."""
        # Include slow tests AND exclude auth tests -> should get nothing
        # (since the slow test is also an auth test)
        self.selector.add_marker_filter("slow", FilterOperation.INCLUDE)
        self.selector.add_pattern_filter("*auth*", FilterOperation.EXCLUDE)
        
        result = self.selector.select_tests(self.test_items)
        
        assert result.selected_count == 0
        assert result.excluded_count == 3
    
    def test_require_filter(self):
        """Test required marker filter."""
        self.selector.add_marker_filter("arango_cluster", FilterOperation.REQUIRE)
        result = self.selector.select_tests(self.test_items)
        
        # Only tests with cluster marker
        assert result.selected_count == 1
        assert "test_cluster_setup" in [t.name for t in result.selected_tests]
    
    def test_custom_filter(self):
        """Test custom filter function."""
        # Custom filter that selects tests with 'create' in the name
        custom_filter = lambda item: "create" in item.name
        self.selector.add_custom_filter(custom_filter)
        
        result = self.selector.select_tests(self.test_items)
        
        assert result.selected_count == 1
        assert "test_create_collection" in [t.name for t in result.selected_tests]
    
    def test_filter_chaining(self):
        """Test fluent interface for filter chaining."""
        result = (self.selector
                  .add_marker_filter("slow", FilterOperation.EXCLUDE)
                  .add_pattern_filter("*collection*", FilterOperation.INCLUDE)
                  .select_tests(self.test_items))
        
        # Should select collection tests that are not slow
        assert result.selected_count == 1
        assert "test_create_collection" in [t.name for t in result.selected_tests]
    
    def test_filter_summary(self):
        """Test filter summary generation."""
        self.selector.add_marker_filter("slow", FilterOperation.INCLUDE)
        self.selector.add_pattern_filter("*auth*", FilterOperation.EXCLUDE)
        
        summary = self.selector.get_filter_summary()
        
        assert summary['total_filters'] == 2
        assert summary['standard_filters'] == 2
        assert summary['custom_filters'] == 0
        assert 'marker_include' in summary['filter_breakdown']
        assert 'pattern_exclude' in summary['filter_breakdown']
    
    def test_clear_filters(self):
        """Test clearing all filters."""
        self.selector.add_marker_filter("slow", FilterOperation.INCLUDE)
        self.selector.add_pattern_filter("*auth*", FilterOperation.EXCLUDE)
        
        assert len(self.selector.filters) == 2
        
        self.selector.clear_filters()
        
        assert len(self.selector.filters) == 0
        assert len(self.selector.custom_filters) == 0
    
    def test_empty_test_collection(self):
        """Test behavior with empty test collection."""
        result = self.selector.select_tests([])
        
        assert result.selected_count == 0
        assert result.excluded_count == 0
        assert result.total_collected == 0
        assert result.selection_rate == 0.0


class TestConvenienceFunctions:
    """Test convenience functions for common selector patterns."""
    
    def setup_method(self):
        """Set up mock test items."""
        self.mock_test_slow = Mock()
        self.mock_test_slow.get_closest_marker = lambda name: Mock() if name == "slow" else None
        
        self.mock_test_fast = Mock()  
        self.mock_test_fast.get_closest_marker = lambda name: Mock() if name == "fast" else None
        
        self.test_items = [self.mock_test_slow, self.mock_test_fast]
    
    def test_create_marker_selector(self):
        """Test marker selector creation."""
        selector = create_marker_selector(
            include_markers=["slow"],
            exclude_markers=["flaky"],
            require_markers=["arango_single"]
        )
        
        summary = selector.get_filter_summary()
        assert summary['total_filters'] == 3
        assert 'marker_include' in summary['filter_breakdown']
        assert 'marker_exclude' in summary['filter_breakdown'] 
        assert 'marker_require' in summary['filter_breakdown']
    
    def test_create_pattern_selector(self):
        """Test pattern selector creation."""
        selector = create_pattern_selector(
            include_patterns=["test_auth_*"],
            exclude_patterns=["*_slow"]
        )
        
        summary = selector.get_filter_summary()
        assert summary['total_filters'] == 2
        assert 'pattern_include' in summary['filter_breakdown']
        assert 'pattern_exclude' in summary['filter_breakdown']
    
    def test_create_suite_selector(self):
        """Test suite selector creation."""
        selector = create_suite_selector("auth")
        
        summary = selector.get_filter_summary()
        assert summary['total_filters'] == 1
        assert 'tag_require' in summary['filter_breakdown']
        assert summary['filter_breakdown']['tag_require'] == ['auth']


class TestErrorHandling:
    """Test error handling in selector."""
    
    def test_malformed_pattern(self):
        """Test handling of malformed regex patterns."""
        selector = TestSelector()
        
        # This should not crash, even with a complex pattern
        selector.add_pattern_filter("[invalid regex", FilterOperation.INCLUDE)
        
        # Should still work with a simple test
        mock_test = Mock()
        mock_test.name = "test_simple"
        mock_test.nodeid = "test_simple"
        mock_test.get_closest_marker = lambda name: None
        
        result = selector.select_tests([mock_test])
        
        # Should handle gracefully
        assert isinstance(result, SelectionResult)
    
    def test_missing_test_attributes(self):
        """Test handling of test items with missing attributes."""
        selector = TestSelector()
        selector.add_pattern_filter("*test*", FilterOperation.INCLUDE)
        
        # Mock test with missing attributes
        incomplete_test = Mock()
        incomplete_test.name = None
        incomplete_test.nodeid = None
        incomplete_test.get_closest_marker = lambda name: None
        
        # Should not crash
        result = selector.select_tests([incomplete_test])
        assert isinstance(result, SelectionResult)


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""
    
    def test_typical_dev_workflow(self):
        """Test typical developer workflow filters."""
        selector = TestSelector()
        
        # Developer wants to run auth tests, but not slow ones
        selector.add_pattern_filter("*auth*", FilterOperation.INCLUDE)
        selector.add_marker_filter("slow", FilterOperation.EXCLUDE)
        
        # Mock realistic test collection
        fast_auth_test = Mock()
        fast_auth_test.name = "test_auth_login"
        fast_auth_test.nodeid = "tests/auth/test_login.py::test_auth_login"
        fast_auth_test.get_closest_marker = lambda name: None
        
        slow_auth_test = Mock()
        slow_auth_test.name = "test_auth_integration"  
        slow_auth_test.nodeid = "tests/auth/test_integration.py::test_auth_integration"
        slow_auth_test.get_closest_marker = lambda name: Mock() if name == "slow" else None
        
        non_auth_test = Mock()
        non_auth_test.name = "test_collections"
        non_auth_test.nodeid = "tests/collections/test_crud.py::test_collections"
        non_auth_test.get_closest_marker = lambda name: None
        
        tests = [fast_auth_test, slow_auth_test, non_auth_test]
        result = selector.select_tests(tests)
        
        # Should select only fast auth test
        assert result.selected_count == 1
        assert result.selected_tests[0].name == "test_auth_login"
    
    def test_ci_workflow(self):
        """Test CI/CD pipeline filter patterns."""
        selector = TestSelector()
        
        # CI wants all tests except flaky and nightly ones
        selector.add_marker_filter("flaky", FilterOperation.EXCLUDE)
        selector.add_marker_filter("nightly", FilterOperation.EXCLUDE)
        
        # Mock CI test collection
        stable_test = Mock()
        stable_test.get_closest_marker = lambda name: None
        
        flaky_test = Mock()
        flaky_test.get_closest_marker = lambda name: Mock() if name == "flaky" else None
        
        nightly_test = Mock()
        nightly_test.get_closest_marker = lambda name: Mock() if name == "nightly" else None
        
        tests = [stable_test, flaky_test, nightly_test]
        result = selector.select_tests(tests)
        
        # Should select only stable test
        assert result.selected_count == 1
        assert result.selected_tests[0] == stable_test
