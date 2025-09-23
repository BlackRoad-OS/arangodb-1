"""Filesystem service for safe path operations and atomic writes."""

import os
import tempfile
import shutil
import uuid
from pathlib import Path
from typing import Union, Optional
from contextlib import contextmanager
from ..core.config import get_config, derive_sub_tmp
from ..core.errors import FilesystemError, PathError, AtomicWriteError
from ..core.log import get_logger

logger = get_logger(__name__)
_test_session_id: Optional[str] = None


class FilesystemService:
    """Provides safe filesystem operations with atomic writes and path management."""

    def __init__(self) -> None:
        self._work_dir: Optional[Path] = None

    def work_dir(self) -> Path:
        """Get the main working directory."""
        if self._work_dir is None:
            config = get_config()
            if config.work_dir:
                base_work_dir = config.work_dir
                if _test_session_id:
                    self._work_dir = base_work_dir / f"session_{_test_session_id}"
                else:
                    self._work_dir = base_work_dir
            else:
                base_work_dir = derive_sub_tmp("work")
                if _test_session_id:
                    self._work_dir = base_work_dir / f"session_{_test_session_id}"
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
        base_temp = derive_sub_tmp("temp")
        temp_path = Path(tempfile.mkdtemp(prefix=f"{prefix}_", dir=base_temp))
        return temp_path

    def atomic_write(
        self, path: Path, data: Union[str, bytes], mode: str = "w"
    ) -> None:
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

    def read_text(self, path: Path, encoding: str = "utf-8") -> str:
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

    def read_bytes(self, path: Path) -> bytes:
        """Read binary file with proper error handling."""
        try:
            return Path(path).read_bytes()
        except FileNotFoundError as e:
            raise PathError(f"File not found: {path}") from e
        except PermissionError as e:
            raise FilesystemError(f"Permission denied reading {path}") from e
        except OSError as e:
            raise FilesystemError(f"Error reading {path}: {e}") from e

    def ensure_dir(self, path: Path) -> Path:
        """Ensure directory exists and return it."""
        try:
            path = Path(path)
            path.mkdir(parents=True, exist_ok=True)
            return path
        except PermissionError as e:
            raise FilesystemError(f"Permission denied creating directory {path}") from e
        except OSError as e:
            raise FilesystemError(f"Error creating directory {path}: {e}") from e

    def safe_remove(self, path: Path) -> bool:
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

    def copy_file(self, src: Path, dst: Path, preserve_metadata: bool = True) -> None:
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
            raise FilesystemError(
                f"Permission denied copying from {src} to {dst}"
            ) from e
        except OSError as e:
            raise FilesystemError(f"Error copying {src} to {dst}: {e}") from e

    def get_size(self, path: Path) -> int:
        """Get file size in bytes."""
        try:
            return Path(path).stat().st_size
        except FileNotFoundError as e:
            raise PathError(f"File not found: {path}") from e
        except OSError as e:
            raise FilesystemError(f"Error getting size of {path}: {e}") from e

    def list_files(
        self, directory: Path, pattern: str = "*", recursive: bool = False
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


_filesystem_service = FilesystemService()


def work_dir() -> Path:
    """Get the main working directory."""
    return _filesystem_service.work_dir()


def server_dir(name: str) -> Path:
    """Get a directory for a specific server instance."""
    return _filesystem_service.server_dir(name)


def temp_dir(prefix: str = "armadillo") -> Path:
    """Create a temporary directory."""
    return _filesystem_service.temp_dir(prefix)


def atomic_write(path: Path, data: Union[str, bytes], mode: str = "w") -> None:
    """Atomically write data to a file."""
    _filesystem_service.atomic_write(path, data, mode)


def read_text(path: Path, encoding: str = "utf-8") -> str:
    """Read text file."""
    return _filesystem_service.read_text(path, encoding)


def read_bytes(path: Path) -> bytes:
    """Read binary file."""
    return _filesystem_service.read_bytes(path)


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists."""
    return _filesystem_service.ensure_dir(path)


def safe_remove(path: Path) -> bool:
    """Safely remove file or directory."""
    return _filesystem_service.safe_remove(path)


def cleanup_work_dir() -> None:
    """Clean up work directory."""
    _filesystem_service.cleanup_work_dir()


def set_test_session_id(session_id: Optional[str] = None) -> str:
    """Set a unique test session ID for directory isolation.

    Args:
        session_id: Optional session ID. If None, a random ID is generated.

    Returns:
        The session ID that was set
    """
    global _test_session_id
    if session_id is None:
        session_id = str(uuid.uuid4())[:8]
    _test_session_id = session_id
    logger.info("Set test session ID: %s", session_id)
    _filesystem_service._work_dir = None
    return session_id


def get_test_session_id() -> Optional[str]:
    """Get the current test session ID."""
    return _test_session_id


def clear_test_session() -> None:
    """Clear the test session ID and reset to shared directories."""
    global _test_session_id
    _test_session_id = None
    _filesystem_service._work_dir = None
    logger.info("Cleared test session ID")
