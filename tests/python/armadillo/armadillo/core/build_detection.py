"""Build directory detection and validation utilities."""

import os
import shutil
from pathlib import Path
from typing import Optional
from .log import get_logger

logger = get_logger(__name__)


class BuildDetector:
    """Detects and validates ArangoDB build directories."""

    def __init__(self) -> None:
        self.simple_patterns = ["build/bin", "bin"]

    def detect_build_directory(
        self, search_from: Optional[Path] = None
    ) -> Optional[Path]:
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
        logger.debug("Searching for ArangoDB build directory from: %s", search_from)
        arangod_in_path = shutil.which("arangod")
        if arangod_in_path:
            arangod_path = Path(arangod_in_path)
            logger.info("Found arangod in PATH: %s", arangod_path)
            return arangod_path.parent
        for pattern in self.simple_patterns:
            candidate = search_from / pattern
            if self.validate_build_directory(candidate):
                logger.info("Auto-detected ArangoDB build directory: %s", candidate)
                return candidate
        logger.debug("Simple patterns failed, searching filesystem...")
        search_roots = [
            search_from,
            search_from.parent,
            search_from.parent.parent,
            search_from.parent.parent.parent,
        ]
        for root in search_roots:
            if root.exists():
                found_path = self._filesystem_search(root)
                if found_path:
                    logger.warning(
                        "Using guessed arangod location: %s", found_path / "arangod"
                    )
                    return found_path
        logger.warning(
            "Could not auto-detect ArangoDB build directory. Use --build-dir to specify manually."
        )
        return None

    def _filesystem_search(self, search_from: Path) -> Optional[Path]:
        """Search filesystem for arangod binary (like scripts/unittest does).

        This is the fallback when simple patterns fail.
        """
        try:
            for arangod_path in search_from.rglob("arangod"):
                if arangod_path.is_file() and os.access(arangod_path, os.X_OK):
                    build_dir = arangod_path.parent
                    if self.validate_build_directory(build_dir):
                        return build_dir
        except (PermissionError, OSError) as e:
            logger.debug("Filesystem search failed: %s", e)
        return None

    def normalize_build_directory(self, build_dir: Path) -> Optional[Path]:
        """Normalize build directory to the directory containing arangod binary.

        Accepts both:
        - Direct path to directory containing arangod: /path/to/build/bin
        - Build root directory: /path/to/build (will check bin/ subdirectory)

        Args:
            build_dir: User-provided build directory path

        Returns:
            Path to directory containing arangod binary, or None if not found
        """
        if not build_dir.exists() or not build_dir.is_dir():
            return None

        # Try common locations for arangod binary
        # Check bin/ subdirectory first (more specific, avoids confusion with arangod/ source dir)
        candidate_paths = [
            build_dir / "bin" / "arangod",  # Standard CMake: /build/bin/arangod
            build_dir
            / "arangod",  # Direct: /build/bin/arangod (if user points to bin dir)
        ]

        for arangod_path in candidate_paths:
            # Check if it's a file (not directory) and executable
            if arangod_path.is_file() and os.access(arangod_path, os.X_OK):
                bin_dir = arangod_path.parent
                logger.debug(
                    "Found arangod at %s, using bin_dir: %s", arangod_path, bin_dir
                )
                return bin_dir

        # Not found
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
        arangod_path = build_dir / "arangod"
        if not arangod_path.exists():
            return False
        if not os.access(arangod_path, os.X_OK):
            logger.debug("Found arangod at %s but it's not executable", arangod_path)
            return False
        logger.debug("Validated build directory: %s", build_dir)
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


_build_detector = BuildDetector()


def normalize_build_directory(build_dir: Path) -> Optional[Path]:
    """Normalize build directory to the directory containing arangod binary.

    Accepts both build root (/path/to/build) and bin directory (/path/to/build/bin).
    """
    return _build_detector.normalize_build_directory(build_dir)


def detect_build_directory(search_from: Optional[Path] = None) -> Optional[Path]:
    """Detect ArangoDB build directory using heuristics."""
    return _build_detector.detect_build_directory(search_from)


def validate_build_directory(build_dir: Path) -> bool:
    """Validate that a directory contains a usable arangod binary."""
    return _build_detector.validate_build_directory(build_dir)


def get_arangod_path(build_dir: Path) -> Path:
    """Get the full path to arangod binary in the build directory."""
    return _build_detector.get_arangod_path(build_dir)
