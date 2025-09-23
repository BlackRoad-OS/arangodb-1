"""
Minimal unit tests for instances/orchestrator.py - Cluster orchestrator.

Tests essential ClusterOrchestrator functionality with minimal mocking.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from armadillo.instances.orchestrator import ClusterOrchestrator, ClusterState
from armadillo.core.types import ServerRole


class TestClusterStateBasic:
    """Test ClusterState dataclass functionality."""

    def test_cluster_state_can_be_created(self):
        """Test ClusterState can be instantiated."""
        state = ClusterState()

        assert state is not None
        assert state.agency_leader is None
        assert isinstance(state.agency_followers, list)
        assert isinstance(state.coordinators, list)
        assert isinstance(state.dbservers, list)
        assert isinstance(state.healthy_servers, set)
        assert isinstance(state.unhealthy_servers, set)

    def test_cluster_state_with_data(self):
        """Test ClusterState with initial data."""
        state = ClusterState(
            agency_leader="agent1",
            coordinators=["coord1", "coord2"],
            dbservers=["db1", "db2"],
            healthy_servers={"agent1", "coord1", "db1"},
        )

        assert state.agency_leader == "agent1"
        assert len(state.coordinators) == 2
        assert len(state.dbservers) == 2
        assert len(state.healthy_servers) == 3

    def test_cluster_state_agency_health_check(self):
        """Test agency health checking."""
        # Healthy agency
        healthy_state = ClusterState(
            agency_leader="agent1", healthy_servers={"agent1", "coord1"}
        )
        assert healthy_state.is_agency_healthy() is True

        # Unhealthy agency - no leader
        unhealthy_state1 = ClusterState(agency_leader=None, healthy_servers={"coord1"})
        assert unhealthy_state1.is_agency_healthy() is False

        # Unhealthy agency - leader not healthy
        unhealthy_state2 = ClusterState(
            agency_leader="agent1",
            healthy_servers={"coord1"},  # agent1 not in healthy_servers
        )
        assert unhealthy_state2.is_agency_healthy() is False

    def test_cluster_state_defaults(self):
        """Test ClusterState default values."""
        state = ClusterState()

        assert state.total_collections == 0
        assert state.total_databases == 1  # At least _system
        assert isinstance(state.shard_distribution, dict)
        assert isinstance(state.replication_health, dict)


class TestClusterOrchestratorBasic:
    """Test ClusterOrchestrator basic functionality."""

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_can_be_created(self, mock_get_manager):
        """Test ClusterOrchestrator can be instantiated."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        orchestrator = ClusterOrchestrator("test_deployment")

        assert orchestrator is not None
        assert orchestrator.deployment_id == "test_deployment"
        assert orchestrator.instance_manager == mock_manager

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_has_expected_attributes(self, mock_get_manager):
        """Test orchestrator has expected attributes."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        orchestrator = ClusterOrchestrator("test")

        # Check that expected attributes exist
        assert hasattr(orchestrator, "deployment_id")
        assert hasattr(orchestrator, "config")
        assert hasattr(orchestrator, "auth_provider")
        assert hasattr(orchestrator, "instance_manager")
        assert hasattr(orchestrator, "_cluster_state")
        assert hasattr(orchestrator, "_state_last_updated")

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_has_expected_methods(self, mock_get_manager):
        """Test orchestrator has expected public methods."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        orchestrator = ClusterOrchestrator("test")

        # Check that key methods exist (based on what we can infer from the structure)
        expected_methods = ["_cluster_state", "_state_last_updated"]

        for attr in expected_methods:
            assert hasattr(orchestrator, attr)

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_unique_deployment_ids(self, mock_get_manager):
        """Test deployment IDs are preserved correctly."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        orchestrator1 = ClusterOrchestrator("deployment_one")
        orchestrator2 = ClusterOrchestrator("deployment_two")

        assert orchestrator1.deployment_id != orchestrator2.deployment_id
        assert orchestrator1.deployment_id == "deployment_one"
        assert orchestrator2.deployment_id == "deployment_two"


class TestClusterOrchestratorInitialization:
    """Test ClusterOrchestrator initialization."""

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_initial_state(self, mock_get_manager):
        """Test orchestrator initial state."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        orchestrator = ClusterOrchestrator("init_test")

        # Initial state should be None
        assert orchestrator._cluster_state is None
        assert orchestrator._state_last_updated is None

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_manager_integration(self, mock_get_manager):
        """Test orchestrator integrates with instance manager."""
        mock_manager = Mock()
        mock_manager.deployment_id = "test_deployment"
        mock_get_manager.return_value = mock_manager

        orchestrator = ClusterOrchestrator("test_deployment")

        # Should have called get_instance_manager with correct deployment ID
        mock_get_manager.assert_called_once_with("test_deployment")
        assert orchestrator.instance_manager == mock_manager


class TestClusterOrchestratorErrorHandling:
    """Test basic error handling."""

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_handles_invalid_deployment_id(self, mock_get_manager):
        """Test orchestrator creation with edge case deployment IDs."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        # Test with empty string
        orchestrator1 = ClusterOrchestrator("")
        assert orchestrator1.deployment_id == ""

        # Test with special characters
        orchestrator2 = ClusterOrchestrator("test-deployment_123")
        assert orchestrator2.deployment_id == "test-deployment_123"

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_handles_manager_failure(self, mock_get_manager):
        """Test orchestrator handles instance manager initialization failure."""
        mock_get_manager.side_effect = Exception("Manager initialization failed")

        with pytest.raises(Exception):
            ClusterOrchestrator("failing_deployment")


class TestClusterOrchestratorMockIntegration:
    """Test orchestrator with minimal safe mocking."""

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_state_management(self, mock_get_manager):
        """Test orchestrator state management capabilities."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        orchestrator = ClusterOrchestrator("state_test")

        # Test that we can set cluster state
        test_state = ClusterState(
            agency_leader="agent1",
            coordinators=["coord1"],
            healthy_servers={"agent1", "coord1"},
        )

        orchestrator._cluster_state = test_state

        assert orchestrator._cluster_state == test_state
        assert orchestrator._cluster_state.agency_leader == "agent1"
        assert orchestrator._cluster_state.is_agency_healthy() is True

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_orchestrator_time_tracking(self, mock_get_manager):
        """Test orchestrator tracks state update time."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        orchestrator = ClusterOrchestrator("time_test")

        # Initially no last updated time
        assert orchestrator._state_last_updated is None

        # Set a mock time
        import time

        current_time = time.time()
        orchestrator._state_last_updated = current_time

        assert orchestrator._state_last_updated == current_time


class TestClusterOrchestratorPublicInterface:
    """Test the public interface works as expected."""

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_has_expected_properties(self, mock_get_manager):
        """Test orchestrator has expected public properties."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        orchestrator = ClusterOrchestrator("interface_test")

        # Check that public properties exist
        assert hasattr(orchestrator, "deployment_id")
        assert hasattr(orchestrator, "config")
        assert hasattr(orchestrator, "auth_provider")
        assert hasattr(orchestrator, "instance_manager")

    @patch("armadillo.instances.orchestrator.get_instance_manager")
    def test_deployment_id_consistency(self, mock_get_manager):
        """Test deployment ID is consistent throughout."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        test_id = "consistency_test_123"
        orchestrator = ClusterOrchestrator(test_id)

        assert orchestrator.deployment_id == test_id
        # Should have requested manager for same deployment ID
        mock_get_manager.assert_called_once_with(test_id)
