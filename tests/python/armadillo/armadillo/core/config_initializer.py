"""Configuration initialization with side effects separated from validation.

This module provides the initialize_config() function which performs all
side-effect operations on configuration:
- Directory creation
- Build detection
- Path normalization

This is intentionally separated from config validation to maintain a clear
distinction between pure validation and I/O-heavy initialization.

Usage:
    # Step 1: Create and validate config (no side effects)
    config = ArmadilloConfig(
        deployment_mode=DeploymentMode.SINGLE_SERVER,
        bin_dir=Path("/path/to/build"),
    )

    # Step 2: Initialize config (side effects: create dirs, detect builds)
    config = initialize_config(config)

    # Step 3: Use initialized config
    app_context = ApplicationContext.create(config)
"""

from pathlib import Path
from .types import ArmadilloConfig
from .build_detection import detect_build_directory, normalize_build_directory
from .errors import PathError
from .log import get_logger

logger = get_logger(__name__)


def initialize_config(config: ArmadilloConfig) -> ArmadilloConfig:
    """Initialize configuration with side effects.

    This function is called AFTER config validation and performs:
    - Default value setting for optional paths
    - Directory creation
    - Build directory detection and normalization
    - Path validation

    Side Effects:
        - Creates directories on filesystem
        - Walks filesystem to detect build directory
        - May modify config fields (temp_dir, bin_dir, work_dir)

    Args:
        config: Validated configuration object

    Returns:
        Initialized configuration (may have modified fields)

    Raises:
        PathError: If required paths cannot be created or detected
        OSError: If filesystem operations fail

    Example:
        >>> config = ArmadilloConfig(deployment_mode=DeploymentMode.SINGLE_SERVER)
        >>> config = initialize_config(config)
        >>> assert config.temp_dir.exists()
    """
    logger.debug("Initializing configuration with side effects")

    # Set default temp directory if not specified
    if config.temp_dir is None:
        config.temp_dir = Path("/tmp/armadillo")
        logger.debug("Using default temp_dir: %s", config.temp_dir)

    # Create temp directory
    try:
        config.temp_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Created temp directory: %s", config.temp_dir)
    except OSError as e:
        raise PathError(
            f"Failed to create temp directory {config.temp_dir}: {e}"
        ) from e

    # Handle bin_dir: normalize or auto-detect (only if not in test mode)
    if config.bin_dir is not None:
        # User explicitly provided a build directory - normalize it
        logger.debug("Normalizing provided bin_dir: %s", config.bin_dir)
        normalized_bin_dir = normalize_build_directory(config.bin_dir)
        if normalized_bin_dir is None:
            # Directory exists but no arangod found
            raise PathError(
                f"Could not find arangod binary in build directory: {config.bin_dir}\n"
                f"Looked in:\n"
                f"  - {config.bin_dir}/arangod\n"
                f"  - {config.bin_dir}/bin/arangod\n"
                f"Please ensure the build directory contains a compiled arangod executable."
            )
        config.bin_dir = normalized_bin_dir
        logger.info("Using arangod from: %s", config.bin_dir)
    elif not config.is_test_mode:
        # No explicit bin_dir and not in test mode - try auto-detection
        logger.debug("Attempting auto-detection of build directory")
        detected_build_dir = detect_build_directory()
        if detected_build_dir:
            config.bin_dir = detected_build_dir
            logger.info("Auto-detected arangod from: %s", config.bin_dir)
        else:
            logger.warning(
                "Could not auto-detect build directory. "
                "Tests requiring arangod binary will fail. "
                "Set bin_dir explicitly or ensure arangod is in a standard build location."
            )
    else:
        logger.debug("Test mode enabled - skipping build directory detection")

    # Create work directory if specified
    if config.work_dir is not None:
        if not config.work_dir.exists():
            try:
                config.work_dir.mkdir(parents=True, exist_ok=True)
                logger.debug("Created work directory: %s", config.work_dir)
            except OSError as e:
                raise PathError(
                    f"Failed to create work directory {config.work_dir}: {e}"
                ) from e

    logger.info("Configuration initialization complete")
    return config
