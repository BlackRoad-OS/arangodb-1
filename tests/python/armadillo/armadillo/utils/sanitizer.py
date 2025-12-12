"""Sanitizer environment variable handling for ASAN/UBSAN/LSAN/TSAN."""

import os
from pathlib import Path
from typing import Dict, Optional, Set, List
from datetime import datetime
from ..core.log import get_logger

logger = get_logger(__name__)


class SanitizerHandler:
    """Handles sanitizer environment variables for ArangoDB processes.

    Configures ASAN_OPTIONS, LSAN_OPTIONS, UBSAN_OPTIONS, and TSAN_OPTIONS
    with appropriate log paths and suppressions.

    Based on JavaScript implementation in san-file-handler.js.
    """

    # Sanitizer types that share the same log file (ASAN/LSAN/UBSAN)
    ALUBSAN_SANITIZERS = {"ASAN_OPTIONS", "LSAN_OPTIONS", "UBSAN_OPTIONS"}
    TSAN_SANITIZERS = {"TSAN_OPTIONS"}
    ALL_SANITIZERS = ALUBSAN_SANITIZERS | TSAN_SANITIZERS

    def __init__(
        self,
        binary_path: Path,
        log_dir: Path,
        repo_root: Path,
        explicit_sanitizer: Optional[str] = None,
    ) -> None:
        """Initialize sanitizer handler.

        Args:
            binary_path: Path to the binary being executed
            log_dir: Directory where sanitizer logs should be written
            repo_root: Repository root for finding suppression files
            explicit_sanitizer: Explicit sanitizer from CLI ("tsan" or "alubsan")
        """
        self.binary_path = binary_path
        self.log_dir = log_dir
        self.repo_root = repo_root
        self._explicit_sanitizer = explicit_sanitizer
        self._detected_sanitizers = self._detect_sanitizers()

    def _detect_sanitizers(self) -> Set[str]:
        """Detect which sanitizers are active.

        Priority:
        1. Explicit CLI flag (highest)
        2. Environment variables (lowest)

        Returns:
            Set of sanitizer environment variable names (e.g., 'ASAN_OPTIONS')
        """
        detected = set()

        # Priority 1: Explicit sanitizer from CLI flag
        if self._explicit_sanitizer:
            if self._explicit_sanitizer == "tsan":
                detected.update(self.TSAN_SANITIZERS)
            elif self._explicit_sanitizer == "alubsan":
                detected.update(self.ALUBSAN_SANITIZERS)
            return detected

        # Priority 2: Check environment variables
        for san_var in self.ALL_SANITIZERS:
            if san_var in os.environ:
                detected.add(san_var)

        return detected

    def is_sanitizer_build(self) -> bool:
        """Check if any sanitizers are detected.

        Returns:
            True if sanitizers are active
        """
        return len(self._detected_sanitizers) > 0

    def get_env_vars(self) -> Dict[str, str]:
        """Generate sanitizer environment variables.

        Reads existing sanitizer options from environment, adds log paths
        and other required settings, and returns updated environment variables.

        Returns:
            Dictionary of environment variables to pass to subprocess
        """
        if not self.is_sanitizer_build():
            return {}

        env_vars = {}

        for san_var in self._detected_sanitizers:
            options = self._parse_existing_options(san_var)
            self._add_log_path(san_var, options)
            self._add_suppressions(san_var, options)
            self._add_standard_options(options)
            env_vars[san_var] = self._format_options(options)

        return env_vars

    def _get_default_options(self, san_var: str) -> Dict[str, str]:
        """Get default options for a sanitizer type when explicitly requested.

        Args:
            san_var: Sanitizer variable name (e.g., 'ASAN_OPTIONS')

        Returns:
            Dictionary of default option key-value pairs
        """
        if not self._explicit_sanitizer:
            return {}

        defaults: Dict[str, str] = {}

        if san_var == "ASAN_OPTIONS":
            defaults = {"halt_on_error": "0", "detect_leaks": "1"}
        elif san_var == "LSAN_OPTIONS":
            defaults = {"halt_on_error": "0"}
        elif san_var == "UBSAN_OPTIONS":
            defaults = {"halt_on_error": "0", "print_stacktrace": "1"}
        elif san_var == "TSAN_OPTIONS":
            defaults = {"halt_on_error": "0", "history_size": "7"}

        return defaults

    def _parse_existing_options(self, san_var: str) -> Dict[str, str]:
        """Parse existing sanitizer options from environment.

        Starts with defaults (if explicit sanitizer), then overlays user env vars.

        Args:
            san_var: Sanitizer variable name (e.g., 'ASAN_OPTIONS')

        Returns:
            Dictionary of option key-value pairs
        """
        # Start with defaults if explicitly requested
        options = self._get_default_options(san_var)

        # Overlay user-specified environment variables (they win)
        existing = os.environ.get(san_var, "")
        if existing:
            for item in existing.split(":"):
                if "=" in item:
                    key, value = item.split("=", 1)
                    options[key] = value

        return options

    def _add_log_path(self, san_var: str, options: Dict[str, str]) -> None:
        """Add log_path and log_exe_name to options.

        ASAN/LSAN/UBSAN share same log file (alubsan.log).
        TSAN uses separate file (tsan.log).

        Args:
            san_var: Sanitizer variable name
            options: Options dictionary to modify
        """
        if san_var in self.TSAN_SANITIZERS:
            log_name = "tsan.log"
        else:
            log_name = "alubsan.log"

        log_path = self.log_dir / log_name
        options["log_path"] = str(log_path)
        options["log_exe_name"] = "true"

    def _add_suppressions(self, san_var: str, options: Dict[str, str]) -> None:
        """Add suppressions file if it exists.

        Args:
            san_var: Sanitizer variable name
            options: Options dictionary to modify
        """
        # Extract sanitizer name (e.g., 'asan' from 'ASAN_OPTIONS')
        san_name = san_var.split("_")[0].lower()
        suppressions_file = self.repo_root / f"{san_name}_arangodb_suppressions.txt"

        if suppressions_file.exists():
            options["suppressions"] = str(suppressions_file)

    def _add_standard_options(self, options: Dict[str, str]) -> None:
        """Add standard options if not already present.

        Args:
            options: Options dictionary to modify
        """
        # Add any standard options here
        # Currently we only set log_path and log_exe_name via _add_log_path
        pass

    def _format_options(self, options: Dict[str, str]) -> str:
        """Format options dictionary as colon-separated string.

        Args:
            options: Options dictionary

        Returns:
            Formatted string like "key1=val1:key2=val2"
        """
        # Replace commas with underscores in values (like JS implementation)
        formatted_items = []
        for key, value in options.items():
            safe_value = value.replace(",", "_")
            formatted_items.append(f"{key}={safe_value}")

        return ":".join(formatted_items)

    def get_log_paths(self) -> Dict[str, Path]:
        """Get paths to sanitizer log files.

        Returns:
            Dictionary mapping sanitizer type to log file path
        """
        log_paths = {}

        if any(san in self._detected_sanitizers for san in self.ALUBSAN_SANITIZERS):
            log_paths["alubsan"] = self.log_dir / "alubsan.log"

        if any(san in self._detected_sanitizers for san in self.TSAN_SANITIZERS):
            log_paths["tsan"] = self.log_dir / "tsan.log"

        return log_paths

    def get_sanitizer_file_paths(self, pid: int) -> list[Path]:
        """Get paths to sanitizer log files for a given PID.

        Log files follow pattern: {log_path}.{binary_name}.{pid}

        Args:
            pid: Process ID to check for sanitizer logs

        Returns:
            List of Path objects for sanitizer log files that exist
        """
        if not self.is_sanitizer_build():
            return []

        binary_name = self.binary_path.name
        file_paths = []

        for log_type, base_log_path in self.get_log_paths().items():
            # Pattern: {base_log_path}.{binary_name}.{pid}
            log_file = Path(f"{base_log_path}.{binary_name}.{pid}")

            if log_file.exists():
                file_paths.append(log_file)

        return file_paths

    def check_sanitizer_logs(self, pid: int) -> List["SanitizerError"]:
        """Check for sanitizer logs and return structured data.

        Returns a list of SanitizerError objects with timestamps for matching.
        This replaces the old approach of returning concatenated strings.

        Args:
            pid: Process ID to check for sanitizer logs

        Returns:
            List of SanitizerError objects (empty list if no errors found)
        """
        # Import here to avoid circular dependency
        from ..core.types import SanitizerError

        if not self.is_sanitizer_build():
            return []

        errors = []
        binary_name = self.binary_path.name

        for log_type, base_log_path in self.get_log_paths().items():
            # Pattern: {base_log_path}.{binary_name}.{pid}
            log_file = Path(f"{base_log_path}.{binary_name}.{pid}")

            if not log_file.exists():
                continue

            try:
                content = log_file.read_text(encoding="utf-8", errors="replace")
                # Only include if content is meaningful (>10 chars, like JS implementation)
                if len(content) > 10:
                    # Get file modification time for matching
                    timestamp = datetime.fromtimestamp(os.path.getmtime(log_file))

                    error = SanitizerError(
                        content=content,
                        file_path=log_file,
                        timestamp=timestamp,
                        sanitizer_type=log_type,  # "alubsan" or "tsan"
                        server_id="",  # Will be set by caller
                    )
                    errors.append(error)
            except (OSError, UnicodeDecodeError) as e:
                # Log file read failures for debugging
                logger.warning(
                    "Failed to read sanitizer log file %s: %s",
                    log_file,
                    e
                )
                # Create error entry for read failures
                error = SanitizerError(
                    content=f"Error reading sanitizer file: {e}",
                    file_path=log_file,
                    timestamp=datetime.now(),
                    sanitizer_type=log_type,
                    server_id="",
                )
                errors.append(error)

        return errors


def create_sanitizer_handler(
    binary_path: Path,
    log_dir: Path,
    repo_root: Optional[Path] = None,
    explicit_sanitizer: Optional[str] = None,
) -> SanitizerHandler:
    """Factory function to create sanitizer handler with default repo root.

    Args:
        binary_path: Path to the binary being executed
        log_dir: Directory where sanitizer logs should be written
        repo_root: Repository root (defaults to current directory)
        explicit_sanitizer: Explicit sanitizer from CLI ("tsan" or "alubsan")

    Returns:
        Configured SanitizerHandler instance
    """
    if repo_root is None:
        repo_root = Path.cwd()

    return SanitizerHandler(binary_path, log_dir, repo_root, explicit_sanitizer)
