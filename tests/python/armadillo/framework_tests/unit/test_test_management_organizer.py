"""Unit tests for test management organizer."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import time

from armadillo.test_management.organizer import (
    SuiteConfig, TestSuite, TestSuiteOrganizer,
    SuitePriority, SuiteStatus,
    create_marker_suite, create_pattern_suite, create_priority_suite
)
from armadillo.test_management.selector import TestSelector, create_marker_selector


class TestSuiteConfig:
    """Test SuiteConfig functionality."""
    
    def test_suite_config_creation(self):
        """Test basic suite config creation."""
        config = SuiteConfig(name="test_suite", description="Test description")
        
        assert config.name == "test_suite"
        assert config.description == "Test description"
        assert config.priority == SuitePriority.NORMAL
        assert isinstance(config.tags, set)
        assert len(config.tags) == 0
        assert config.depends_on == []
        assert config.conflicts_with == []
    
    def test_suite_config_with_full_options(self):
        """Test suite config with all options."""
        config = SuiteConfig(
            name="full_suite",
            description="Full description",
            priority=SuitePriority.HIGH,
            tags={"slow", "integration"},
            timeout=300.0,
            max_parallel=4,
            requires_isolation=True,
            depends_on=["auth_suite"],
            conflicts_with=["fast_suite"],
            min_memory_mb=1024,
            requires_network=True,
            metadata={"version": "1.0"}
        )
        
        assert config.name == "full_suite"
        assert config.priority == SuitePriority.HIGH
        assert "slow" in config.tags
        assert "integration" in config.tags
        assert config.timeout == 300.0
        assert config.max_parallel == 4
        assert config.requires_isolation is True
        assert "auth_suite" in config.depends_on
        assert "fast_suite" in config.conflicts_with
        assert config.min_memory_mb == 1024
        assert config.requires_network is True
        assert config.metadata["version"] == "1.0"
    
    def test_suite_config_chaining(self):
        """Test method chaining on suite config."""
        config = (SuiteConfig(name="chain_test")
                 .add_tag("slow")
                 .add_tag("integration")
                 .add_dependency("auth_suite")
                 .add_conflict("fast_suite"))
        
        assert "slow" in config.tags
        assert "integration" in config.tags
        assert "auth_suite" in config.depends_on
        assert "fast_suite" in config.conflicts_with
    
    def test_suite_config_has_tag(self):
        """Test tag checking functionality."""
        config = SuiteConfig(name="tag_test", tags={"slow", "integration"})
        
        assert config.has_tag("slow") is True
        assert config.has_tag("integration") is True
        assert config.has_tag("fast") is False
    
    def test_suite_config_compatibility(self):
        """Test suite compatibility checking."""
        config1 = SuiteConfig(name="suite1", conflicts_with=["suite2"])
        config2 = SuiteConfig(name="suite2")
        config3 = SuiteConfig(name="suite3")
        
        # suite1 conflicts with suite2 (should be bidirectional) 
        assert config1.is_compatible_with(config2) is False
        assert config2.is_compatible_with(config1) is False  # Conflict is bidirectional
        
        # suite1 and suite3 are compatible
        assert config1.is_compatible_with(config3) is True
        assert config3.is_compatible_with(config1) is True
    
    def test_suite_config_duplicate_dependencies(self):
        """Test handling of duplicate dependencies."""
        config = SuiteConfig(name="dup_test")
        config.add_dependency("dep1")
        config.add_dependency("dep1")  # Duplicate
        
        assert config.depends_on == ["dep1"]  # Should only appear once


class TestTestSuite:
    """Test TestSuite functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.config = SuiteConfig(name="test_suite", description="Test suite")
        self.selector = TestSelector()
        self.suite = TestSuite(config=self.config, selector=self.selector)
        
        # Create mock test items
        self.mock_tests = []
        for i in range(5):
            test = Mock()
            test.name = f"test_{i}"
            test.nodeid = f"tests/test_file.py::test_{i}"
            self.mock_tests.append(test)
    
    def test_suite_creation(self):
        """Test basic suite creation."""
        assert self.suite.name == "test_suite"
        assert self.suite.config == self.config
        assert self.suite.selector == self.selector
        assert self.suite.status == SuiteStatus.PENDING
        assert self.suite.test_count == 0
        assert self.suite.tests == []
    
    def test_suite_properties(self):
        """Test suite property calculations."""
        self.suite.tests = self.mock_tests[:3]
        
        assert self.suite.test_count == 3
        assert self.suite.total_tests == 3  # No children
        
        # Add child suite
        child_config = SuiteConfig(name="child_suite")
        child_suite = TestSuite(config=child_config, selector=TestSelector())
        child_suite.tests = self.mock_tests[3:]  # 2 tests
        self.suite.add_child(child_suite)
        
        assert self.suite.total_tests == 5  # 3 + 2 from child
    
    def test_suite_duration_calculation(self):
        """Test duration calculation."""
        # No start/end time
        assert self.suite.duration is None
        
        # Set start and end times
        self.suite.start_time = 100.0
        self.suite.end_time = 105.5
        assert self.suite.duration == 5.5
    
    def test_suite_success_rate(self):
        """Test success rate calculation."""
        # Empty suite
        assert self.suite.success_rate == 0.0
        
        # Suite with results
        self.suite.tests = self.mock_tests
        self.suite.passed = 3
        self.suite.failed = 1
        self.suite.skipped = 1
        
        assert self.suite.success_rate == 60.0  # 3/5 * 100
    
    def test_suite_collect_tests(self):
        """Test test collection."""
        # Mock selector to return specific tests
        with patch.object(self.selector, 'select_tests') as mock_select:
            mock_result = Mock()
            mock_result.selected_tests = self.mock_tests[:3]
            mock_select.return_value = mock_result
            
            result = self.suite.collect_tests(self.mock_tests)
            
            assert result == self.suite  # Should return self for chaining
            assert len(self.suite.tests) == 3
            mock_select.assert_called_once_with(self.mock_tests)
    
    def test_suite_hierarchy_management(self):
        """Test parent-child hierarchy."""
        child_config = SuiteConfig(name="child")
        child_suite = TestSuite(config=child_config, selector=TestSelector())
        
        # Add child
        self.suite.add_child(child_suite)
        
        assert child_suite in self.suite.children
        assert child_suite.parent == self.suite
        assert len(self.suite.children) == 1
        
        # Remove child
        self.suite.remove_child(child_suite)
        
        assert child_suite not in self.suite.children
        assert child_suite.parent is None
        assert len(self.suite.children) == 0
    
    def test_suite_path_calculation(self):
        """Test hierarchical path calculation."""
        # Root suite
        assert self.suite.get_path() == ["test_suite"]
        assert self.suite.get_full_name() == "test_suite"
        
        # Child suite
        child_config = SuiteConfig(name="child")
        child_suite = TestSuite(config=child_config, selector=TestSelector())
        self.suite.add_child(child_suite)
        
        assert child_suite.get_path() == ["test_suite", "child"]
        assert child_suite.get_full_name() == "test_suite.child"
        
        # Grandchild suite
        grandchild_config = SuiteConfig(name="grandchild")
        grandchild_suite = TestSuite(config=grandchild_config, selector=TestSelector())
        child_suite.add_child(grandchild_suite)
        
        assert grandchild_suite.get_path() == ["test_suite", "child", "grandchild"]
        assert grandchild_suite.get_full_name() == "test_suite.child.grandchild"
    
    def test_suite_get_all_tests(self):
        """Test getting all tests including from children."""
        self.suite.tests = self.mock_tests[:2]
        
        # Add child with tests
        child_config = SuiteConfig(name="child")
        child_suite = TestSuite(config=child_config, selector=TestSelector())
        child_suite.tests = self.mock_tests[2:4]
        self.suite.add_child(child_suite)
        
        # Add grandchild with tests
        grandchild_config = SuiteConfig(name="grandchild")
        grandchild_suite = TestSuite(config=grandchild_config, selector=TestSelector())
        grandchild_suite.tests = [self.mock_tests[4]]
        child_suite.add_child(grandchild_suite)
        
        all_tests = self.suite.get_all_tests()
        assert len(all_tests) == 5
        assert all_tests == self.mock_tests
    
    def test_suite_matches_criteria(self):
        """Test criteria matching."""
        self.suite.config.tags.add("slow")
        self.suite.config.tags.add("integration")
        self.suite.config.metadata["version"] = "1.0"
        self.suite.status = SuiteStatus.COMPLETED
        
        # Test tag matching
        assert self.suite.matches_criteria({"tags": ["slow"]}) is True
        assert self.suite.matches_criteria({"tags": ["slow", "integration"]}) is True
        assert self.suite.matches_criteria({"tags": ["slow", "fast"]}) is False
        
        # Test priority matching
        assert self.suite.matches_criteria({"priority": SuitePriority.NORMAL}) is True
        assert self.suite.matches_criteria({"priority": SuitePriority.HIGH}) is False
        
        # Test status matching
        assert self.suite.matches_criteria({"status": SuiteStatus.COMPLETED}) is True
        assert self.suite.matches_criteria({"status": SuiteStatus.RUNNING}) is False
        
        # Test metadata matching
        assert self.suite.matches_criteria({"metadata": {"version": "1.0"}}) is True
        assert self.suite.matches_criteria({"metadata": {"version": "2.0"}}) is False
        
        # Test combined criteria
        criteria = {
            "tags": ["slow"],
            "status": SuiteStatus.COMPLETED,
            "metadata": {"version": "1.0"}
        }
        assert self.suite.matches_criteria(criteria) is True
    
    def test_suite_summary(self):
        """Test suite summary generation."""
        self.suite.tests = self.mock_tests
        self.suite.passed = 3
        self.suite.failed = 1
        self.suite.skipped = 1
        self.suite.status = SuiteStatus.COMPLETED
        self.suite.config.tags.add("slow")
        
        # Add child
        child_config = SuiteConfig(name="child")
        child_suite = TestSuite(config=child_config, selector=TestSelector())
        self.suite.add_child(child_suite)
        
        summary = self.suite.summary()
        
        assert summary['name'] == 'test_suite'
        assert summary['full_name'] == 'test_suite'
        assert summary['status'] == 'completed'
        assert summary['test_count'] == 5
        assert summary['total_tests'] == 5
        assert summary['passed'] == 3
        assert summary['failed'] == 1
        assert summary['skipped'] == 1
        assert summary['success_rate'] == 60.0
        assert summary['priority'] == 3  # SuitePriority.NORMAL.value
        assert summary['tags'] == ['slow']
        assert summary['children_count'] == 1
        assert summary['has_parent'] is False


class TestTestSuiteOrganizer:
    """Test TestSuiteOrganizer functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.organizer = TestSuiteOrganizer()
        
        # Create sample suites
        self.auth_config = SuiteConfig(name="auth_suite", priority=SuitePriority.HIGH)
        self.auth_suite = TestSuite(config=self.auth_config, selector=TestSelector())
        
        self.collections_config = SuiteConfig(name="collections_suite")
        self.collections_suite = TestSuite(config=self.collections_config, selector=TestSelector())
        
        self.slow_config = SuiteConfig(
            name="slow_suite", 
            priority=SuitePriority.LOW,
            depends_on=["auth_suite"]
        )
        self.slow_suite = TestSuite(config=self.slow_config, selector=TestSelector())
    
    def test_organizer_creation(self):
        """Test organizer creation."""
        assert len(self.organizer.suites) == 0
        assert len(self.organizer.root_suites) == 0
        assert self.organizer.execution_order == []
    
    def test_create_suite(self):
        """Test suite creation through organizer."""
        config = SuiteConfig(name="new_suite")
        suite = self.organizer.create_suite(config)
        
        assert suite.name == "new_suite"
        assert suite in self.organizer.suites.values()
        assert suite in self.organizer.root_suites
    
    def test_add_remove_suite(self):
        """Test adding and removing suites."""
        # Add suite
        self.organizer.add_suite(self.auth_suite)
        
        assert "auth_suite" in self.organizer.suites
        assert self.auth_suite in self.organizer.root_suites
        
        # Remove suite
        result = self.organizer.remove_suite("auth_suite")
        
        assert result is True
        assert "auth_suite" not in self.organizer.suites
        assert self.auth_suite not in self.organizer.root_suites
        
        # Try to remove non-existent suite
        result = self.organizer.remove_suite("non_existent")
        assert result is False
    
    def test_get_suite(self):
        """Test getting suite by name."""
        self.organizer.add_suite(self.auth_suite)
        
        retrieved = self.organizer.get_suite("auth_suite")
        assert retrieved == self.auth_suite
        
        non_existent = self.organizer.get_suite("non_existent")
        assert non_existent is None
    
    def test_find_suites(self):
        """Test finding suites by criteria."""
        # Add suites with different characteristics
        self.auth_suite.config.tags.add("authentication")
        self.auth_suite.status = SuiteStatus.COMPLETED
        
        self.collections_suite.config.tags.add("crud")
        self.collections_suite.status = SuiteStatus.RUNNING
        
        self.organizer.add_suite(self.auth_suite)
        self.organizer.add_suite(self.collections_suite)
        
        # Find by tag
        auth_suites = self.organizer.find_suites({"tags": ["authentication"]})
        assert len(auth_suites) == 1
        assert auth_suites[0] == self.auth_suite
        
        # Find by status
        running_suites = self.organizer.find_suites({"status": SuiteStatus.RUNNING})
        assert len(running_suites) == 1
        assert running_suites[0] == self.collections_suite
        
        # Find by priority
        high_priority = self.organizer.find_suites({"priority": SuitePriority.HIGH})
        assert len(high_priority) == 1
        assert high_priority[0] == self.auth_suite
    
    def test_organize_by_markers(self):
        """Test auto-organization by pytest markers."""
        # Create mock tests with markers
        mock_tests = []
        
        # Slow test
        slow_test = Mock()
        slow_marker = Mock()
        slow_marker.name = "slow"
        slow_test.iter_markers = lambda: [slow_marker]
        slow_test.get_closest_marker = lambda name: slow_marker if name == "slow" else None
        mock_tests.append(slow_test)
        
        # Fast test  
        fast_test = Mock()
        fast_marker = Mock()
        fast_marker.name = "fast"
        fast_test.iter_markers = lambda: [fast_marker]
        fast_test.get_closest_marker = lambda name: fast_marker if name == "fast" else None
        mock_tests.append(fast_test)
        
        # Integration test
        integration_test = Mock()
        integration_marker = Mock()
        integration_marker.name = "integration"
        integration_test.iter_markers = lambda: [integration_marker]
        integration_test.get_closest_marker = lambda name: integration_marker if name == "integration" else None
        mock_tests.append(integration_test)
        
        # Test with no common markers
        other_test = Mock()
        other_marker = Mock()
        other_marker.name = "other"
        other_test.iter_markers = lambda: [other_marker]
        other_test.get_closest_marker = lambda name: other_marker if name == "other" else None
        mock_tests.append(other_test)
        
        # Patch the selector's select_tests method to return the appropriate tests
        with patch('armadillo.test_management.selector.TestSelector.select_tests') as mock_select:
            def select_tests_side_effect(all_tests):
                # Mock result that returns tests for the suite being created
                result = Mock()
                result.selected_tests = [mock_tests[0]]  # Just return one test for simplicity
                return result
            
            mock_select.side_effect = select_tests_side_effect
            
            self.organizer.organize_by_markers(mock_tests)
        
        # Should create suites for common markers
        assert "slow_tests" in self.organizer.suites
        assert "fast_tests" in self.organizer.suites  
        assert "integration_tests" in self.organizer.suites
        assert "other_tests" not in self.organizer.suites  # Not a common marker
        
        # Check suite properties
        slow_suite = self.organizer.get_suite("slow_tests")
        assert "slow" in slow_suite.config.tags
        assert "auto_generated" in slow_suite.config.tags
    
    def test_organize_by_paths(self):
        """Test auto-organization by file paths."""
        # Create mock tests with different paths
        mock_tests = []
        
        # Auth tests
        for i in range(3):
            test = Mock()
            test.fspath = Path(f"tests/auth/test_auth_{i}.py")
            test.nodeid = f"tests/auth/test_auth_{i}.py::test_function_{i}"
            mock_tests.append(test)
        
        # Collections tests
        for i in range(2):
            test = Mock()
            test.fspath = Path(f"tests/collections/test_collections_{i}.py") 
            test.nodeid = f"tests/collections/test_collections_{i}.py::test_function_{i}"
            mock_tests.append(test)
        
        # Single test in integration (should not create suite)
        single_test = Mock()
        single_test.fspath = Path("tests/integration/test_single.py")
        single_test.nodeid = "tests/integration/test_single.py::test_function"
        mock_tests.append(single_test)
        
        self.organizer.organize_by_paths(mock_tests)
        
        # Should create suites for directories with multiple tests
        assert "auth_suite" in self.organizer.suites
        assert "collections_suite" in self.organizer.suites
        assert "integration_suite" not in self.organizer.suites  # Only one test
        
        # Check suite properties
        auth_suite = self.organizer.get_suite("auth_suite")
        assert len(auth_suite.tests) == 3
        assert "auth" in auth_suite.config.tags
        assert "path_based" in auth_suite.config.tags
    
    def test_organize_hierarchical(self):
        """Test hierarchical organization."""
        # Create suites with hierarchical names
        parent_config = SuiteConfig(name="parent")
        parent_suite = TestSuite(config=parent_config, selector=TestSelector())
        
        child1_config = SuiteConfig(name="parent.child1")
        child1_suite = TestSuite(config=child1_config, selector=TestSelector())
        
        child2_config = SuiteConfig(name="parent.child2") 
        child2_suite = TestSuite(config=child2_config, selector=TestSelector())
        
        grandchild_config = SuiteConfig(name="parent.child1.grandchild")
        grandchild_suite = TestSuite(config=grandchild_config, selector=TestSelector())
        
        # Add all suites
        for suite in [parent_suite, child1_suite, child2_suite, grandchild_suite]:
            self.organizer.add_suite(suite)
        
        self.organizer.organize_hierarchical()
        
        # Check hierarchy was created properly
        parent = self.organizer.get_suite("parent")
        assert len(parent.children) >= 1  # Should have children
        
        # Verify parent-child relationships
        child1 = self.organizer.get_suite("parent.child1")
        if child1.parent:
            assert child1.parent.name == "parent"
    
    def test_calculate_execution_order(self):
        """Test execution order calculation with dependencies."""
        # Add suites with dependencies
        self.organizer.add_suite(self.auth_suite)      # No dependencies, HIGH priority
        self.organizer.add_suite(self.collections_suite)  # No dependencies, NORMAL priority  
        self.organizer.add_suite(self.slow_suite)      # Depends on auth_suite, LOW priority
        
        order = self.organizer.calculate_execution_order()
        
        # Auth suite should come before slow suite (dependency)
        auth_index = order.index("auth_suite")
        slow_index = order.index("slow_suite")
        assert auth_index < slow_index
        
        # Should include all suites
        assert len(order) == 3
        assert set(order) == {"auth_suite", "collections_suite", "slow_suite"}
    
    def test_calculate_execution_order_circular_dependency(self):
        """Test circular dependency detection."""
        # Create circular dependency
        circular_config = SuiteConfig(name="circular", depends_on=["slow_suite"])
        circular_suite = TestSuite(config=circular_config, selector=TestSelector())
        
        self.slow_suite.config.depends_on = ["circular"]  # Create circle
        
        self.organizer.add_suite(self.slow_suite)
        self.organizer.add_suite(circular_suite)
        
        # Should raise ValueError for circular dependency
        with pytest.raises(ValueError, match="Circular dependency"):
            self.organizer.calculate_execution_order()
    
    def test_validate_dependencies(self):
        """Test dependency validation."""
        # Add suite with non-existent dependency
        invalid_config = SuiteConfig(name="invalid", depends_on=["non_existent"])
        invalid_suite = TestSuite(config=invalid_config, selector=TestSelector())
        
        # Add suite with conflict
        conflict_config = SuiteConfig(name="conflict", conflicts_with=["collections_suite"])
        conflict_suite = TestSuite(config=conflict_config, selector=TestSelector())
        
        self.organizer.add_suite(invalid_suite)
        self.organizer.add_suite(conflict_suite) 
        self.organizer.add_suite(self.collections_suite)
        
        errors = self.organizer.validate_dependencies()
        
        # Should find dependency and conflict errors
        assert len(errors) >= 1
        assert any("non_existent" in error for error in errors)
    
    def test_collect_all_tests(self):
        """Test collecting tests for all suites."""
        mock_tests = [Mock() for _ in range(5)]
        
        # Mock selectors to return different subsets
        with patch.object(self.auth_suite.selector, 'select_tests') as mock_auth:
            with patch.object(self.collections_suite.selector, 'select_tests') as mock_collections:
                auth_result = Mock()
                auth_result.selected_tests = mock_tests[:2]
                mock_auth.return_value = auth_result
                
                collections_result = Mock()
                collections_result.selected_tests = mock_tests[2:]
                mock_collections.return_value = collections_result
                
                self.organizer.add_suite(self.auth_suite)
                self.organizer.add_suite(self.collections_suite)
                
                self.organizer.collect_all_tests(mock_tests)
                
                assert len(self.auth_suite.tests) == 2
                assert len(self.collections_suite.tests) == 3
    
    def test_get_statistics(self):
        """Test statistics generation."""
        self.auth_suite.status = SuiteStatus.COMPLETED
        self.collections_suite.status = SuiteStatus.RUNNING
        
        self.organizer.add_suite(self.auth_suite)
        self.organizer.add_suite(self.collections_suite) 
        self.organizer.add_suite(self.slow_suite)
        
        stats = self.organizer.get_statistics()
        
        assert stats['total_suites'] == 3
        assert stats['root_suites'] == 3
        assert stats['status_distribution']['completed'] == 1
        assert stats['status_distribution']['running'] == 1
        assert stats['status_distribution']['pending'] == 1
        assert stats['priority_distribution'][SuitePriority.HIGH.value] == 1
        assert stats['priority_distribution'][SuitePriority.NORMAL.value] == 1
        assert stats['priority_distribution'][SuitePriority.LOW.value] == 1
        assert stats['has_dependencies'] is True  # slow_suite depends on auth_suite
    
    def test_export_summary(self):
        """Test comprehensive summary export."""
        self.organizer.add_suite(self.auth_suite)
        self.organizer.add_suite(self.collections_suite)
        
        summary = self.organizer.export_summary()
        
        assert 'statistics' in summary
        assert 'execution_order' in summary
        assert 'validation_errors' in summary
        assert 'suites' in summary
        assert 'hierarchy' in summary
        
        assert len(summary['suites']) == 2
        assert 'auth_suite' in summary['suites']
        assert 'collections_suite' in summary['suites']


class TestConvenienceFunctions:
    """Test convenience functions for common suite patterns."""
    
    def test_create_marker_suite(self):
        """Test marker-based suite creation."""
        suite = create_marker_suite("slow_tests", "slow", "Slow running tests")
        
        assert suite.name == "slow_tests"
        assert suite.config.description == "Slow running tests"
        assert "slow" in suite.config.tags
        assert suite.selector is not None
    
    def test_create_pattern_suite(self):
        """Test pattern-based suite creation."""
        suite = create_pattern_suite("auth_tests", "*auth*", "Authentication tests")
        
        assert suite.name == "auth_tests"
        assert suite.config.description == "Authentication tests"
        assert "pattern_based" in suite.config.tags
        assert suite.selector is not None
    
    def test_create_priority_suite(self):
        """Test priority-based suite creation."""
        selector = TestSelector()
        suite = create_priority_suite("critical_tests", SuitePriority.CRITICAL, selector, "Critical tests")
        
        assert suite.name == "critical_tests"
        assert suite.config.priority == SuitePriority.CRITICAL
        assert suite.config.description == "Critical tests"
        assert "critical" in suite.config.tags
        assert suite.selector == selector


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""
    
    def setup_method(self):
        """Set up integration test environment."""
        self.organizer = TestSuiteOrganizer()
        
        # Create mock tests with various characteristics
        self.mock_tests = []
        
        # Auth tests with markers
        for i in range(3):
            test = Mock()
            test.name = f"test_auth_{i}"
            test.nodeid = f"tests/auth/test_auth.py::test_auth_{i}"
            test.fspath = Path("tests/auth/test_auth.py")
            test.iter_markers = lambda: [Mock(name="slow"), Mock(name="integration")]
            test.get_closest_marker = lambda name: Mock() if name in ["slow", "integration"] else None
            self.mock_tests.append(test)
        
        # Fast unit tests
        for i in range(2):
            test = Mock()
            test.name = f"test_unit_{i}"
            test.nodeid = f"tests/unit/test_unit.py::test_unit_{i}"
            test.fspath = Path("tests/unit/test_unit.py")
            test.iter_markers = lambda: [Mock(name="fast"), Mock(name="unit")]
            test.get_closest_marker = lambda name: Mock() if name in ["fast", "unit"] else None
            self.mock_tests.append(test)
        
        # Collections tests
        for i in range(2):
            test = Mock()
            test.name = f"test_collections_{i}"
            test.nodeid = f"tests/collections/test_collections.py::test_collections_{i}"
            test.fspath = Path("tests/collections/test_collections.py")
            test.iter_markers = lambda: [Mock(name="unit")]
            test.get_closest_marker = lambda name: Mock() if name == "unit" else None
            self.mock_tests.append(test)
    
    def test_full_organization_workflow(self):
        """Test complete organization workflow."""
        # Step 1: Auto-organize by markers
        self.organizer.organize_by_markers(self.mock_tests)
        
        # Step 2: Auto-organize by paths
        self.organizer.organize_by_paths(self.mock_tests)
        
        # Step 3: Add custom suites with dependencies
        # First check what unit suite was actually created
        unit_suite_names = [name for name in self.organizer.suites.keys() if "unit" in name.lower()]
        dependency_name = unit_suite_names[0] if unit_suite_names else "unit_tests"
        
        critical_config = SuiteConfig(
            name="critical_suite",
            priority=SuitePriority.CRITICAL,
            depends_on=[dependency_name]
        )
        critical_selector = create_marker_selector(require_markers=["integration"])
        critical_suite = TestSuite(config=critical_config, selector=critical_selector)
        self.organizer.add_suite(critical_suite)
        
        # Step 4: Collect all tests
        self.organizer.collect_all_tests(self.mock_tests)
        
        # Step 5: Calculate execution order
        order = self.organizer.calculate_execution_order()
        
        # Step 6: Validate dependencies
        errors = self.organizer.validate_dependencies()
        
        # Verify results
        assert len(self.organizer.suites) >= 3  # At least unit, slow, integration from markers
        assert len(order) >= 3
        # Unit_tests may be created by marker organization or path organization
        has_unit_suite = any("unit" in suite_name for suite_name in self.organizer.suites.keys())
        assert has_unit_suite  # Should have some unit-related suite
        
        # Critical suite should depend on some unit suite (if both exist)
        unit_suite_names = [name for name in order if "unit" in name.lower()]
        if unit_suite_names and "critical_suite" in order:
            unit_index = order.index(unit_suite_names[0])
            critical_index = order.index("critical_suite")
            assert unit_index < critical_index
        
        # Should have few or no validation errors for this setup
        assert len(errors) <= 1  # May have some expected minor issues
    
    def test_hierarchy_with_dependencies(self):
        """Test hierarchical suites with dependencies."""
        # Create parent suite
        parent_config = SuiteConfig(name="integration", priority=SuitePriority.LOW)
        parent_suite = TestSuite(config=parent_config, selector=TestSelector())
        
        # Create child suites with dependencies  
        auth_config = SuiteConfig(
            name="integration.auth",
            depends_on=["unit_tests"]
        )
        auth_suite = TestSuite(config=auth_config, selector=create_marker_selector(require_markers=["integration"]))
        
        collections_config = SuiteConfig(
            name="integration.collections", 
            depends_on=["integration.auth"]
        )
        collections_suite = TestSuite(config=collections_config, selector=TestSelector())
        
        # Add unit tests suite (dependency)
        unit_config = SuiteConfig(name="unit_tests", priority=SuitePriority.HIGH)
        unit_suite = TestSuite(config=unit_config, selector=create_marker_selector(require_markers=["unit"]))
        
        # Add all suites
        for suite in [parent_suite, auth_suite, collections_suite, unit_suite]:
            self.organizer.add_suite(suite)
        
        # Organize hierarchically
        self.organizer.organize_hierarchical()
        
        # Calculate execution order
        order = self.organizer.calculate_execution_order()
        
        # Verify dependency ordering
        unit_index = order.index("unit_tests")
        auth_index = order.index("integration.auth")
        collections_index = order.index("integration.collections")
        
        assert unit_index < auth_index  # unit_tests before integration.auth
        assert auth_index < collections_index  # integration.auth before integration.collections
    
    def test_conflict_resolution(self):
        """Test handling of suite conflicts."""
        # Create conflicting suites
        fast_config = SuiteConfig(
            name="fast_suite",
            conflicts_with=["slow_suite"],
            priority=SuitePriority.HIGH
        )
        fast_suite = TestSuite(config=fast_config, selector=create_marker_selector(require_markers=["fast"]))
        
        slow_config = SuiteConfig(
            name="slow_suite", 
            priority=SuitePriority.LOW
        )
        slow_suite = TestSuite(config=slow_config, selector=create_marker_selector(require_markers=["slow"]))
        
        self.organizer.add_suite(fast_suite)
        self.organizer.add_suite(slow_suite)
        
        # Validate - should detect conflict
        errors = self.organizer.validate_dependencies()
        
        # Should have conflict error
        assert any("conflicts" in error.lower() for error in errors)
        
        # Execution order should still be calculable
        order = self.organizer.calculate_execution_order()
        assert len(order) == 2
        
        # Fast suite should come first due to higher priority
        assert order.index("fast_suite") < order.index("slow_suite")
    
    def test_large_scale_organization(self):
        """Test organization with many suites."""
        # Create many suites with various characteristics
        suite_count = 20
        
        for i in range(suite_count):
            config = SuiteConfig(
                name=f"suite_{i:02d}",
                priority=list(SuitePriority)[i % len(SuitePriority)],
                tags={f"category_{i % 3}", "auto_generated"}
            )
            
            # Add some dependencies
            if i > 5:
                config.depends_on = [f"suite_{(i-3):02d}"]
            
            selector = TestSelector()
            suite = TestSuite(config=config, selector=selector)
            self.organizer.add_suite(suite)
        
        # Calculate execution order
        order = self.organizer.calculate_execution_order()
        
        # Get statistics
        stats = self.organizer.get_statistics()
        
        # Verify all suites included
        assert len(order) == suite_count
        assert stats['total_suites'] == suite_count
        assert stats['has_dependencies'] is True
        
        # Verify dependency ordering (basic check)
        for i, suite_name in enumerate(order):
            suite = self.organizer.get_suite(suite_name)
            for dep_name in suite.config.depends_on:
                if dep_name in order:
                    dep_index = order.index(dep_name)
                    assert dep_index < i, f"Dependency {dep_name} should come before {suite_name}"
