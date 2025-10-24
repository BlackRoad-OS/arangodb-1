"""Filesystem service for safe path operations and atomic writes."""

import os
import tempfile
import shutil
import uuid
from pathlib import Path
from typing import Union, Optional
from contextlib import contextmanager
from ..core.errors import FilesystemError, PathError, AtomicWriteError
from ..core.log import get_logger
from ..core.types import ArmadilloConfig

logger = get_logger(__name__)


# =============================================================================
# Pure Utility Functions (no state required)
# =============================================================================


def atomic_write(path: Path, data: Union[str, bytes], mode: str = "w") -> None:
    """Atomically write data to a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_binary = isinstance(data, bytes) or "b" in mode
    write_mode = mode if is_binary else mode.replace("b", "")
    try:
        with tempfile.NamedTemporaryFile(
            mode=write_mode,
            dir=path.parent,
            delete=False,
            prefix=f".{path.name}.tmp",
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        tmp_path.replace(path)
        logger.debug(
            "Atomically wrote %s %s to %s",
            len(data),
            "bytes" if is_binary else "chars",
            path,
        )
    except OSError as e:
        if "tmp_path" in locals() and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise AtomicWriteError(f"Failed to atomically write to {path}: {e}") from e


def read_text(path: Path, encoding: str = "utf-8") -> str:
    """Read text file with proper error handling."""
    try:
        return Path(path).read_text(encoding=encoding)
    except FileNotFoundError as e:
        raise PathError(f"File not found: {path}") from e
    except PermissionError as e:
        raise FilesystemError(f"Permission denied reading {path}") from e
    except UnicodeDecodeError as e:
        raise FilesystemError(f"Encoding error reading {path}: {e}") from e
    except OSError as e:
        raise FilesystemError(f"Error reading {path}: {e}") from e


def read_bytes(path: Path) -> bytes:
    """Read binary file with proper error handling."""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError as e:
        raise PathError(f"File not found: {path}") from e
    except PermissionError as e:
        raise FilesystemError(f"Permission denied reading {path}") from e
    except OSError as e:
        raise FilesystemError(f"Error reading {path}: {e}") from e


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists and return it."""
    try:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path
    except PermissionError as e:
        raise FilesystemError(f"Permission denied creating directory {path}") from e
    except OSError as e:
        raise FilesystemError(f"Error creating directory {path}: {e}") from e


def safe_remove(path: Path) -> bool:
    """Safely remove a file or directory, returning success status."""
    try:
        path = Path(path)
        if path.is_file():
            path.unlink()
            return True
        elif path.is_dir():
            shutil.rmtree(path)
            return True
        else:
            return False
    except OSError as e:
        logger.warning("Failed to remove %s: %s", path, e)
        return False


def copy_file(src: Path, dst: Path, preserve_metadata: bool = True) -> None:
    """Copy file with proper error handling."""
    try:
        src = Path(src)
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if preserve_metadata:
            shutil.copy2(src, dst)
        else:
            shutil.copy(src, dst)
        logger.debug("Copied %s to %s", src, dst)
    except FileNotFoundError as e:
        raise PathError(f"Source file not found: {src}") from e
    except PermissionError as e:
        raise FilesystemError(f"Permission denied copying from {src} to {dst}") from e
    except OSError as e:
        raise FilesystemError(f"Error copying {src} to {dst}: {e}") from e


def get_size(path: Path) -> int:
    """Get file size in bytes."""
    try:
        return Path(path).stat().st_size
    except FileNotFoundError as e:
        raise PathError(f"File not found: {path}") from e
    except OSError as e:
        raise FilesystemError(f"Error getting size of {path}: {e}") from e


def list_files(
    directory: Path, pattern: str = "*", recursive: bool = False
) -> list[Path]:
    """List files in directory with pattern matching."""
    try:
        directory = Path(directory)
        if not directory.exists():
            raise PathError(f"Directory not found: {directory}")
        if recursive:
            return list(directory.rglob(pattern))
        else:
            return list(directory.glob(pattern))
    except OSError as e:
        raise FilesystemError(f"Error listing files in {directory}: {e}") from e


# =============================================================================
# FilesystemService (stateful operations requiring configuration)
# =============================================================================


class FilesystemService:
    """Provides safe filesystem operations with atomic writes and path management.

    This service requires explicit configuration instead of using global state.
    """

    def __init__(self, config: ArmadilloConfig) -> None:
        """Initialize filesystem service with explicit configuration.

        Args:
            config: Framework configuration
        """
        self._config = config
        self._work_dir: Optional[Path] = None
        self._test_session_id: Optional[str] = None

    def set_test_session_id(self, session_id: str) -> None:
        """Set test session ID for directory isolation.

        Args:
            session_id: Unique test session identifier
        """
        self._test_session_id = session_id
        self._work_dir = None  # Reset to force recalculation

    def work_dir(self) -> Path:
        """Get the main working directory."""
        if self._work_dir is None:
            if self._config.work_dir:
                base_work_dir = self._config.work_dir
            else:
                # Use temp_dir/work as base
                base_work_dir = self._config.temp_dir / "work"

            if self._test_session_id:
                self._work_dir = base_work_dir / f"session_{self._test_session_id}"
            else:
                self._work_dir = base_work_dir

        self._work_dir.mkdir(parents=True, exist_ok=True)
        return self._work_dir

    def server_dir(self, name: str) -> Path:
        """Get a directory for a specific server instance."""
        server_path = self.work_dir() / "servers" / name
        server_path.mkdir(parents=True, exist_ok=True)
        return server_path

    def temp_dir(self, prefix: str = "armadillo") -> Path:
        """Create a temporary directory."""
        base_temp = self._config.temp_dir / "temp"
        base_temp.mkdir(parents=True, exist_ok=True)
        temp_path = Path(tempfile.mkdtemp(prefix=f"{prefix}_", dir=base_temp))
        return temp_path

    @contextmanager
    def temp_file(self, suffix: str = "", prefix: str = "armadillo", text: bool = True):
        """Context manager for temporary files."""
        temp_directory = self.temp_dir()
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+t" if text else "w+b",
                suffix=suffix,
                prefix=prefix,
                dir=temp_directory,
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                yield tmp_path
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError as e:
                    logger.warning("Failed to clean up temp file %s: %s", tmp_path, e)

    def cleanup_work_dir(self) -> None:
        """Clean up the work directory."""
        if self._work_dir and self._work_dir.exists():
            try:
                shutil.rmtree(self._work_dir)
                logger.info("Cleaned up work directory: %s", self._work_dir)
            except OSError as e:
                logger.error(
                    "Failed to clean up work directory %s: %s", self._work_dir, e
                )
