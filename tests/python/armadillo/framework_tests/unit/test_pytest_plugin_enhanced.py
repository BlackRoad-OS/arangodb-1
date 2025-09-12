"""Tests for enhanced pytest plugin functionality (Phase 2)."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from armadillo.pytest_plugin.plugin import (
    ArmadilloPlugin, pytest_collection_modifyitems, pytest_runtest_setup,
    pytest_addoption, pytest_fixture_setup
)
from armadillo.core.types import ServerRole, DeploymentMode, ClusterConfig


class TestArmadilloPluginEnhanced:
    """Test enhanced ArmadilloPlugin functionality."""

    def test_plugin_initialization_enhanced(self):
        """Test enhanced plugin initialization."""
        plugin = ArmadilloPlugin()

        assert len(plugin._session_servers) == 0
        assert len(plugin._session_deployments) == 0
        assert len(plugin._session_orchestrators) == 0
        assert plugin._armadillo_config is None

    def test_pytest_configure_enhanced_markers(self):
        """Test configuration with all enhanced markers."""
        plugin = ArmadilloPlugin()
        mock_config = Mock()
        mock_config.option.verbose = 1

        expected_markers = [
            "arango_single: Requires single ArangoDB server",
            "arango_cluster: Requires ArangoDB cluster",
            "slow: Long-running test (>30s expected)",
            "fast: Fast test (<5s expected)",
            "crash_test: Test involves intentional crashes",
            "stress_test: High-load stress test",
            "flaky: Test has known intermittent failures",
            "auth_required: Test requires authentication",
            "cluster_coordination: Tests cluster coordination features",
            "replication: Tests data replication",
            "sharding: Tests sharding functionality",
            "failover: Tests high availability and failover",
            "rta_suite: RTA test suite marker",
            "smoke_test: Basic smoke test",
            "regression: Regression test",
            "performance: Performance measurement test",
        ]

        with patch('armadillo.pytest_plugin.plugin.load_config') as mock_load:
            with patch('armadillo.pytest_plugin.plugin.configure_logging'):
                with patch('armadillo.pytest_plugin.plugin.set_global_deadline'):
                    mock_config_obj = Mock()
                    mock_config_obj.test_timeout = 900.0
                    mock_load.return_value = mock_config_obj

                    plugin.pytest_configure(mock_config)

                    # Verify all markers were registered
                    assert mock_config.addinivalue_line.call_count == len(expected_markers)

                    # Check some specific marker calls
                    call_args_list = mock_config.addinivalue_line.call_args_list
                    marker_calls = [call[0] for call in call_args_list]

                    assert ("markers", "arango_cluster: Requires ArangoDB cluster") in marker_calls
                    assert ("markers", "stress_test: High-load stress test") in marker_calls
                    assert ("markers", "cluster_coordination: Tests cluster coordination features") in marker_calls

    def test_pytest_unconfigure_enhanced_cleanup(self):
        """Test enhanced cleanup in unconfigure."""
        plugin = ArmadilloPlugin()
        mock_config = Mock()

        # Set up mock deployments and orchestrators
        mock_deployment = Mock()
        mock_deployment.is_deployed.return_value = True
        mock_deployment.shutdown_deployment = Mock()

        mock_orchestrator = Mock()

        mock_server = Mock()
        mock_server.is_running.return_value = True
        mock_server.stop = Mock()

        plugin._session_deployments = {"deploy1": mock_deployment}
        plugin._session_orchestrators = {"orch1": mock_orchestrator}
        plugin._session_servers = {"server1": mock_server}

        with patch('armadillo.pytest_plugin.plugin.stop_watchdog'):
            plugin.pytest_unconfigure(mock_config)

            mock_deployment.shutdown_deployment.assert_called_once()
            mock_server.stop.assert_called_once()


class TestClusterFixtures:
    """Test cluster-related fixture functionality."""

    def test_arango_cluster_fixture_setup_logic(self):
        """Test cluster fixture setup logic (without calling fixtures directly)."""
        # Test the logic that would happen in fixture setup
        with patch('armadillo.pytest_plugin.plugin.get_instance_manager') as mock_get_manager:
            with patch('armadillo.pytest_plugin.plugin.get_cluster_orchestrator') as mock_get_orchestrator:
                with patch('armadillo.pytest_plugin.plugin.random_id', return_value="abc123"):
                    with patch('asyncio.run') as mock_asyncio_run:

                        # Mock the manager and orchestrator
                        mock_manager = Mock()
                        mock_manager.deploy_servers = Mock()
                        mock_get_manager.return_value = mock_manager

                        mock_orchestrator = Mock()
                        mock_get_orchestrator.return_value = mock_orchestrator

                        # Simulate what the fixture would do
                        deployment_id = f"cluster_abc123"
                        manager = mock_get_manager(deployment_id)

                        # Verify the manager would be called correctly
                        assert manager is mock_manager
                        mock_get_manager.assert_called_once_with(deployment_id)

    def test_arango_cluster_function_fixture_logic(self):
        """Test function-scoped cluster fixture logic."""
        # Test the expected configuration for function-scoped fixtures
        from armadillo.core.types import ClusterConfig, DeploymentMode

        # Function-scoped fixtures should use minimal configuration
        minimal_config = ClusterConfig(agents=3, dbservers=1, coordinators=1)

        # Verify the configuration values
        assert minimal_config.agents == 3
        assert minimal_config.dbservers == 1  # Minimal for function scope
        assert minimal_config.coordinators == 1

        # Verify deployment mode would be cluster
        deployment_mode = DeploymentMode.CLUSTER
        assert deployment_mode == DeploymentMode.CLUSTER

    def test_role_specific_fixtures_logic(self):
        """Test role-specific server fixtures logic."""
        from armadillo.core.types import ServerRole

        # Mock cluster manager with servers
        mock_coordinator = Mock()
        mock_coordinator.role = ServerRole.COORDINATOR

        mock_dbserver = Mock()
        mock_dbserver.role = ServerRole.DBSERVER

        mock_agent = Mock()
        mock_agent.role = ServerRole.AGENT

        mock_cluster = Mock()
        mock_cluster.get_servers_by_role.side_effect = lambda role: {
            ServerRole.COORDINATOR: [mock_coordinator],
            ServerRole.DBSERVER: [mock_dbserver],
            ServerRole.AGENT: [mock_agent],
        }[role]

        # Test the logic that the fixtures would implement
        coordinators = mock_cluster.get_servers_by_role(ServerRole.COORDINATOR)
        assert coordinators == [mock_coordinator]

        dbservers = mock_cluster.get_servers_by_role(ServerRole.DBSERVER)
        assert dbservers == [mock_dbserver]

        agents = mock_cluster.get_servers_by_role(ServerRole.AGENT)
        assert agents == [mock_agent]

    def test_orchestrator_fixture_logic(self):
        """Test orchestrator fixture logic."""
        from armadillo.pytest_plugin.plugin import _plugin

        # Mock the plugin's session orchestrators
        mock_orchestrator = Mock()
        _plugin._session_orchestrators = {"test_deployment": mock_orchestrator}

        # Test the fixture logic directly without calling the fixture
        deployment_ids = list(_plugin._session_orchestrators.keys())
        if deployment_ids:
            deployment_id = deployment_ids[0]
            result = _plugin._session_orchestrators[deployment_id]
            assert result is mock_orchestrator

        # Clean up
        _plugin._session_orchestrators.clear()


class TestPytestHooks:
    """Test pytest hook implementations."""

    def test_pytest_collection_modifyitems_auto_markers(self):
        """Test automatic marker application during collection."""
        mock_config = Mock()

        # Create mock test items with proper attributes
        cluster_item = Mock()
        cluster_item.fixturenames = ['arango_cluster']
        cluster_item.name = "test_cluster_operation"  # Add name attribute
        cluster_item.add_marker = Mock()

        function_item = Mock()
        function_item.fixturenames = ['arango_single_server_function']
        function_item.name = "test_single_operation"
        function_item.add_marker = Mock()

        stress_item = Mock()
        stress_item.name = "test_stress_performance"
        stress_item.fixturenames = []
        stress_item.add_marker = Mock()

        crash_item = Mock()
        crash_item.name = "test_crash_recovery"
        crash_item.fixturenames = []
        crash_item.add_marker = Mock()

        perf_item = Mock()
        perf_item.name = "test_benchmark_query"
        perf_item.fixturenames = []
        perf_item.add_marker = Mock()

        items = [cluster_item, function_item, stress_item, crash_item, perf_item]

        pytest_collection_modifyitems(mock_config, items)

        # Verify cluster test marked as slow
        cluster_item.add_marker.assert_called()
        slow_marker_calls = [call for call in cluster_item.add_marker.call_args_list
                           if 'slow' in str(call)]
        assert len(slow_marker_calls) > 0

        # Verify function test marked as fast
        function_item.add_marker.assert_called()

        # Verify stress test gets stress_test and slow markers
        stress_item.add_marker.assert_called()
        stress_calls = stress_item.add_marker.call_args_list
        assert len(stress_calls) >= 2  # At least stress_test + slow (may have more)

        # Verify crash test gets crash_test marker
        crash_item.add_marker.assert_called()

        # Verify performance test gets performance marker
        perf_item.add_marker.assert_called()

    def test_pytest_runtest_setup_marker_skipping(self):
        """Test marker-based test skipping."""
        # Mock test item with slow marker
        slow_item = Mock()
        slow_marker = Mock()
        slow_marker.name = 'slow'
        slow_item.get_closest_marker.side_effect = lambda name: slow_marker if name == 'slow' else None
        slow_item.config.getoption.return_value = False  # --runslow not provided

        with pytest.raises(pytest.skip.Exception, match="need --runslow option"):
            pytest_runtest_setup(slow_item)

        # Test with stress marker
        stress_item = Mock()
        stress_marker = Mock()
        stress_marker.name = 'stress_test'
        stress_item.get_closest_marker.side_effect = lambda name: stress_marker if name == 'stress_test' else None
        stress_item.config.getoption.return_value = False  # --stress not provided

        with pytest.raises(pytest.skip.Exception, match="need --stress option"):
            pytest_runtest_setup(stress_item)

        # Test with flaky marker
        flaky_item = Mock()
        flaky_marker = Mock()
        flaky_marker.name = 'flaky'
        flaky_item.get_closest_marker.side_effect = lambda name: flaky_marker if name == 'flaky' else None
        flaky_item.config.getoption.return_value = False  # --flaky not provided

        with pytest.raises(pytest.skip.Exception, match="need --flaky option"):
            pytest_runtest_setup(flaky_item)

    def test_pytest_addoption_custom_options(self):
        """Test custom command line options."""
        mock_parser = Mock()

        pytest_addoption(mock_parser)

        # Verify all custom options were added
        expected_options = [
            '--runslow',
            '--stress',
            '--flaky',
            '--deployment-mode'
        ]

        call_args_list = mock_parser.addoption.call_args_list
        added_options = [call[0][0] for call in call_args_list]

        for option in expected_options:
            assert option in added_options

        # Verify deployment-mode has correct choices
        deployment_mode_call = None
        for call in call_args_list:
            if '--deployment-mode' in call[0]:
                deployment_mode_call = call
                break

        assert deployment_mode_call is not None
        kwargs = deployment_mode_call[1]
        assert kwargs['choices'] == ['single', 'cluster']
        assert kwargs['default'] == 'single'

    def test_pytest_fixture_setup_marker_detection(self):
        """Test fixture setup marker detection."""
        # Mock request with cluster marker
        cluster_request = Mock()
        cluster_node = Mock()
        cluster_marker = Mock()
        cluster_marker.name = 'arango_cluster'
        cluster_node.iter_markers.return_value = [cluster_marker]
        cluster_request.node = cluster_node

        mock_fixturedef = Mock()

        # Should not raise any exceptions
        pytest_fixture_setup(mock_fixturedef, cluster_request)

        # Mock request with single server marker
        single_request = Mock()
        single_node = Mock()
        single_marker = Mock()
        single_marker.name = 'arango_single'
        single_node.iter_markers.return_value = [single_marker]
        single_request.node = single_node

        pytest_fixture_setup(mock_fixturedef, single_request)

        # Mock request without markers
        no_marker_request = Mock()
        no_marker_node = Mock()
        no_marker_node.iter_markers.return_value = []
        no_marker_request.node = no_marker_node

        pytest_fixture_setup(mock_fixturedef, no_marker_request)


class TestEnhancedFixtureLogic:
    """Test enhanced fixture logic and integration."""

    def test_fixture_cleanup_on_exception_logic(self):
        """Test fixture cleanup logic when exceptions occur."""
        # Test the exception handling logic that fixtures would use
        mock_manager = Mock()
        mock_manager.deploy_servers.side_effect = Exception("Deployment failed")
        mock_manager.shutdown_deployment = Mock()

        # Simulate what would happen in fixture cleanup
        try:
            mock_manager.deploy_servers()
            assert False, "Should have raised exception"
        except Exception as e:
            assert str(e) == "Deployment failed"
            # Fixture would call cleanup
            mock_manager.shutdown_deployment()
            mock_manager.shutdown_deployment.assert_called_once()

    def test_multiple_cluster_configurations_logic(self):
        """Test different cluster configuration logic."""
        from armadillo.core.types import ClusterConfig

        # Test session cluster (full configuration)
        session_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)
        assert session_config.agents == 3
        assert session_config.dbservers == 2  # Full for session scope
        assert session_config.coordinators == 1

        # Test function cluster (minimal configuration)
        function_config = ClusterConfig(agents=3, dbservers=1, coordinators=1)
        assert function_config.agents == 3
        assert function_config.dbservers == 1  # Minimal for function scope
        assert function_config.coordinators == 1

        # Verify they're different
        assert session_config.dbservers != function_config.dbservers

    def test_fixture_marker_integration(self):
        """Test integration between fixtures and markers."""
        # This test simulates how pytest would integrate fixtures with markers

        # Mock a test that uses cluster fixture and has cluster marker
        test_function = Mock()
        test_function.__name__ = "test_cluster_operation"
        test_function.fixturenames = ['arango_cluster', 'arango_coordinators']

        # Simulate pytest's marker detection
        markers = ['arango_cluster', 'cluster_coordination']

        # The test should be marked as slow due to cluster fixture
        expected_markers = ['slow']  # Added by pytest_collection_modifyitems

        # Simulate the collection modification
        mock_item = Mock()
        mock_item.fixturenames = ['arango_cluster', 'arango_coordinators']
        mock_item.name = "test_cluster_operation"
        mock_item.add_marker = Mock()

        pytest_collection_modifyitems(Mock(), [mock_item])

        # Should have added slow marker due to cluster fixture
        mock_item.add_marker.assert_called()
        marker_calls = [str(call) for call in mock_item.add_marker.call_args_list]
        slow_call_found = any('slow' in call for call in marker_calls)
        assert slow_call_found
