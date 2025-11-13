"""Unit tests for config initialization with side effects.

Tests verify that:
1. Config validation has no side effects
2. Config initialization performs required I/O
3. Separation of concerns is maintained
"""

import pytest
from pathlib import Path

from armadillo.core.types import ArmadilloConfig, DeploymentMode
from armadillo.core.config_initializer import initialize_config
from armadillo.core.errors import PathError


class TestConfigValidationPurity:
    """Test that config validation has no side effects."""

    def test_validation_does_not_create_directories(self, tmp_path) -> None:
        """Config validation should NOT create directories."""
        non_existent = tmp_path / "does_not_exist"

        # Create config - this should only validate, not create directories
        config = ArmadilloConfig(
            temp_dir=non_existent,
            deployment_mode=DeploymentMode.SINGLE_SERVER,
        )

        # Directory should NOT be created by validation
        assert not non_existent.exists()

    def test_validation_does_not_detect_build(self, tmp_path) -> None:
        """Config validation should NOT perform build detection."""
        # Create config without bin_dir
        config = ArmadilloConfig(
            temp_dir=tmp_path,
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            is_test_mode=False,  # Even without test mode
        )

        # bin_dir should still be None after validation
        assert config.bin_dir is None

    def test_validation_performs_logical_checks(self) -> None:
        """Config validation SHOULD perform logical validation."""
        # Invalid cluster config should raise during validation
        with pytest.raises(Exception):  # ConfigurationError
            ArmadilloConfig(
                deployment_mode=DeploymentMode.CLUSTER,
                cluster={"agents": 0, "dbservers": 1, "coordinators": 1},
            )

        # Invalid timeout should raise during validation
        with pytest.raises(Exception):  # ConfigurationError
            ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER,
                test_timeout=-1.0,
            )


class TestConfigInitialization:
    """Test config initialization with side effects."""

    def test_initialization_creates_temp_directory(self, tmp_path) -> None:
        """Config initialization SHOULD create temp directory."""
        temp_dir = tmp_path / "armadillo_temp"

        config = ArmadilloConfig(
            temp_dir=temp_dir,
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            is_test_mode=True,
        )

        # Directory should NOT exist before initialization
        assert not temp_dir.exists()

        # Initialize config
        initialized = initialize_config(config)

        # Directory SHOULD exist after initialization
        assert initialized.temp_dir.exists()
        assert initialized.temp_dir == temp_dir

    def test_initialization_sets_default_temp_dir(self) -> None:
        """Config initialization SHOULD set default temp_dir if None."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            is_test_mode=True,
        )

        assert config.temp_dir is None

        initialized = initialize_config(config)

        assert initialized.temp_dir is not None
        assert initialized.temp_dir == Path("/tmp/armadillo")

    def test_initialization_creates_work_directory(self, tmp_path) -> None:
        """Config initialization SHOULD create work directory if specified."""
        work_dir = tmp_path / "work"

        config = ArmadilloConfig(
            temp_dir=tmp_path / "temp",
            work_dir=work_dir,
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            is_test_mode=True,
        )

        assert not work_dir.exists()

        initialized = initialize_config(config)

        assert initialized.work_dir.exists()

    def test_initialization_skips_build_detection_in_test_mode(self, tmp_path) -> None:
        """Config initialization SHOULD skip build detection in test mode."""
        config = ArmadilloConfig(
            temp_dir=tmp_path,
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            is_test_mode=True,  # Explicit test mode
        )

        initialized = initialize_config(config)

        # bin_dir should still be None in test mode
        assert initialized.bin_dir is None

    def test_initialization_normalizes_provided_bin_dir(self, tmp_path) -> None:
        """Config initialization SHOULD normalize provided bin_dir."""
        # Create a fake build directory with arangod
        build_dir = tmp_path / "build"
        bin_dir = build_dir / "bin"
        bin_dir.mkdir(parents=True)
        arangod_path = bin_dir / "arangod"
        arangod_path.touch()
        arangod_path.chmod(0o755)  # Make executable

        config = ArmadilloConfig(
            temp_dir=tmp_path / "temp",
            bin_dir=build_dir,  # Provide build dir (not bin dir)
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            is_test_mode=True,
        )

        initialized = initialize_config(config)

        # Should normalize to actual bin directory
        assert initialized.bin_dir == bin_dir

    def test_initialization_raises_on_invalid_bin_dir(self, tmp_path) -> None:
        """Config initialization SHOULD raise if bin_dir has no arangod."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        # No arangod in this directory

        config = ArmadilloConfig(
            temp_dir=tmp_path / "temp",
            bin_dir=build_dir,
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            is_test_mode=True,
        )

        with pytest.raises(PathError) as exc_info:
            initialize_config(config)

        assert "Could not find arangod binary" in str(exc_info.value)


class TestConfigInitializationIdempotency:
    """Test that initialization can be called multiple times safely."""

    def test_initialization_is_idempotent(self, tmp_path) -> None:
        """Calling initialize_config multiple times should be safe."""
        config = ArmadilloConfig(
            temp_dir=tmp_path / "temp",
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            is_test_mode=True,
        )

        # Initialize twice
        config1 = initialize_config(config)
        config2 = initialize_config(config1)

        # Should produce same results
        assert config1.temp_dir == config2.temp_dir
        assert config1.temp_dir.exists()
        assert config2.temp_dir.exists()


class TestConfigWorkflow:
    """Test the recommended workflow: validate then initialize."""

    def test_recommended_workflow(self, tmp_path) -> None:
        """Test the validate -> initialize workflow."""
        # Step 1: Create config (validation happens automatically)
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=tmp_path / "armadillo",
            test_timeout=120.0,
            is_test_mode=True,
        )

        # At this point: validated but not initialized
        assert not config.temp_dir.exists()

        # Step 2: Initialize (side effects happen here)
        config = initialize_config(config)

        # At this point: initialized and ready to use
        assert config.temp_dir.exists()

        # Step 3: Use in ApplicationContext
        from armadillo.core.context import ApplicationContext

        ctx = ApplicationContext.create(config)
        assert ctx.config is config
