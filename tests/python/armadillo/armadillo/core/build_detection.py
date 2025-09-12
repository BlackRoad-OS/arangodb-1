"""Build directory detection and validation utilities."""

import os
import shutil
from pathlib import Path
from typing import Optional, List
from .log import get_logger

logger = get_logger(__name__)


class BuildDetector:
    """Detects and validates ArangoDB build directories."""

    def __init__(self) -> None:
        # Simple patterns to try first (like JS process-utils.js)
        self.simple_patterns = [
            "build/bin",  # Standard CMake build
            "bin",        # Current directory has binaries
        ]

    def detect_build_directory(self, search_from: Optional[Path] = None) -> Optional[Path]:
        """Detect ArangoDB build directory using the same logic as the old framework.

        This mirrors the approach from scripts/unittest:
        1. First check if arangod is in PATH
        2. Try simple heuristics (build/bin, bin)
        3. Fall back to filesystem search with warning

        Args:
            search_from: Starting directory for search (defaults to current working dir)

        Returns:
            Path to build directory containing arangod, or None if not found
        """
        if search_from is None:
            search_from = Path.cwd()

        logger.debug(f"Searching for ArangoDB build directory from: {search_from}")

        # Step 1: Check if arangod is already in PATH
        arangod_in_path = shutil.which("arangod")
        if arangod_in_path:
            arangod_path = Path(arangod_in_path)
            logger.info(f"Found arangod in PATH: {arangod_path}")
            return arangod_path.parent

        # Step 2: Try simple heuristics first (like JS process-utils.js)
        for pattern in self.simple_patterns:
            candidate = search_from / pattern
            if self.validate_build_directory(candidate):
                logger.info(f"Auto-detected ArangoDB build directory: {candidate}")
                return candidate

        # Step 3: Fall back to filesystem search (like scripts/unittest)
        logger.debug("Simple patterns failed, searching filesystem...")

        # Search from potential source roots (like the old scripts/unittest did)
        search_roots = [
            search_from,  # Current directory
            search_from.parent,  # Parent directory
            search_from.parent.parent,  # Grandparent directory
            search_from.parent.parent.parent,  # Great-grandparent directory
        ]

        for root in search_roots:
            if root.exists():
                found_path = self._filesystem_search(root)
                if found_path:
                    logger.warning(f"Using guessed arangod location: {found_path / 'arangod'}")
                    return found_path

        logger.warning("Could not auto-detect ArangoDB build directory. Use --build-dir to specify manually.")
        return None

    def _filesystem_search(self, search_from: Path) -> Optional[Path]:
        """Search filesystem for arangod binary (like scripts/unittest does).

        This is the fallback when simple patterns fail.
        """
        try:
            # Search for any arangod executable in the source tree
            # Using rglob to search recursively
            for arangod_path in search_from.rglob("arangod"):
                if (arangod_path.is_file() and os.access(arangod_path, os.X_OK)):
                    build_dir = arangod_path.parent
                    if self.validate_build_directory(build_dir):
                        return build_dir
        except (PermissionError, OSError) as e:
            logger.debug(f"Filesystem search failed: {e}")

        return None

    def validate_build_directory(self, build_dir: Path) -> bool:
        """Validate that a directory contains a usable arangod binary.

        Args:
            build_dir: Directory to validate

        Returns:
            True if directory contains arangod binary, False otherwise
        """
        if not build_dir.exists() or not build_dir.is_dir():
            return False

        # Check for arangod binary
        arangod_path = build_dir / "arangod"
        if not arangod_path.exists():
            return False

        # Check if it's executable
        if not os.access(arangod_path, os.X_OK):
            logger.debug(f"Found arangod at {arangod_path} but it's not executable")
            return False

        logger.debug(f"Validated build directory: {build_dir}")
        return True

    def get_arangod_path(self, build_dir: Path) -> Path:
        """Get the full path to arangod binary in the build directory.

        Args:
            build_dir: Build directory containing arangod

        Returns:
            Full path to arangod binary

        Raises:
            FileNotFoundError: If arangod binary not found in build directory
        """
        arangod_path = build_dir / "arangod"
        if not self.validate_build_directory(build_dir):
            raise FileNotFoundError(f"arangod binary not found in {build_dir}")
        return arangod_path


# Global detector instance
_build_detector = BuildDetector()


def detect_build_directory(search_from: Optional[Path] = None) -> Optional[Path]:
    """Detect ArangoDB build directory using heuristics."""
    return _build_detector.detect_build_directory(search_from)


def validate_build_directory(build_dir: Path) -> bool:
    """Validate that a directory contains a usable arangod binary."""
    return _build_detector.validate_build_directory(build_dir)


def get_arangod_path(build_dir: Path) -> Path:
    """Get the full path to arangod binary in the build directory."""
    return _build_detector.get_arangod_path(build_dir)
