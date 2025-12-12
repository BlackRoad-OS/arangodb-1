"""Tests for sanitizer utilities."""

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from armadillo.utils.sanitizer import SanitizerHandler, create_sanitizer_handler


@pytest.fixture
def temp_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create temporary directories for testing."""
    binary_dir = tmp_path / "bin"
    log_dir = tmp_path / "logs"
    repo_root = tmp_path / "repo"

    binary_dir.mkdir()
    log_dir.mkdir()
    repo_root.mkdir()

    return binary_dir, log_dir, repo_root


@pytest.fixture
def mock_binary(temp_dirs: tuple[Path, Path, Path]) -> Path:
    """Create a mock binary file."""
    binary_dir, _, _ = temp_dirs
    binary = binary_dir / "arangod"
    binary.touch()
    return binary


class TestSanitizerHandler:
    """Test SanitizerHandler class."""

    def test_creation(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test basic creation of SanitizerHandler."""
        _, log_dir, repo_root = temp_dirs

        handler = SanitizerHandler(mock_binary, log_dir, repo_root)

        assert handler.binary_path == mock_binary
        assert handler.log_dir == log_dir
        assert handler.repo_root == repo_root

    def test_no_sanitizers_detected_by_default(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test that no sanitizers are detected without env vars or explicit flag."""
        _, log_dir, repo_root = temp_dirs

        # Clear sanitizer env vars
        with patch.dict(os.environ, {}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            assert not handler.is_sanitizer_build()
            assert handler.get_env_vars() == {}

    def test_detect_sanitizer_from_env_var(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test detecting sanitizer from environment variable."""
        _, log_dir, repo_root = temp_dirs

        with patch.dict(os.environ, {"ASAN_OPTIONS": "detect_leaks=1"}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            assert handler.is_sanitizer_build()
            assert "ASAN_OPTIONS" in handler._detected_sanitizers

    def test_parse_existing_options(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test parsing existing sanitizer options from environment."""
        _, log_dir, repo_root = temp_dirs

        env_value = "detect_leaks=1:verbosity=1:log_path=/tmp/asan.log"
        with patch.dict(os.environ, {"ASAN_OPTIONS": env_value}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            assert "ASAN_OPTIONS" in env_vars

            # Check that existing options are preserved
            result = env_vars["ASAN_OPTIONS"]
            assert "detect_leaks=1" in result
            assert "verbosity=1" in result

    def test_add_log_path_alubsan(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test that log_path and log_exe_name are added for ASAN/LSAN/UBSAN."""
        _, log_dir, repo_root = temp_dirs

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            assert "ASAN_OPTIONS" in env_vars

            result = env_vars["ASAN_OPTIONS"]
            expected_log_path = str(log_dir / "alubsan.log")
            assert f"log_path={expected_log_path}" in result
            assert "log_exe_name=true" in result

    def test_add_log_path_tsan(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test that TSAN uses separate log file."""
        _, log_dir, repo_root = temp_dirs

        with patch.dict(os.environ, {"TSAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            assert "TSAN_OPTIONS" in env_vars

            result = env_vars["TSAN_OPTIONS"]
            expected_log_path = str(log_dir / "tsan.log")
            assert f"log_path={expected_log_path}" in result
            assert "log_exe_name=true" in result

    def test_alubsan_share_same_log_file(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test that ASAN/LSAN/UBSAN all use the same log file."""
        _, log_dir, repo_root = temp_dirs

        env_dict = {
            "ASAN_OPTIONS": "",
            "LSAN_OPTIONS": "",
            "UBSAN_OPTIONS": "",
        }
        with patch.dict(os.environ, env_dict, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            expected_log_path = str(log_dir / "alubsan.log")

            for san_var in ["ASAN_OPTIONS", "LSAN_OPTIONS", "UBSAN_OPTIONS"]:
                assert san_var in env_vars
                assert f"log_path={expected_log_path}" in env_vars[san_var]

    def test_suppressions_file_added_if_exists(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test that suppressions file is added when it exists."""
        _, log_dir, repo_root = temp_dirs

        # Create suppressions file
        suppressions_file = repo_root / "asan_arangodb_suppressions.txt"
        suppressions_file.write_text("leak:known_leak\n")

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            result = env_vars["ASAN_OPTIONS"]

            assert f"suppressions={str(suppressions_file)}" in result

    def test_suppressions_file_not_added_if_missing(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test that suppressions file is not added when it doesn't exist."""
        _, log_dir, repo_root = temp_dirs

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            result = env_vars["ASAN_OPTIONS"]

            assert "suppressions=" not in result

    def test_comma_replacement_in_values(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test that commas in option values are replaced with underscores."""
        _, log_dir, repo_root = temp_dirs

        env_value = "option=value,with,commas"
        with patch.dict(os.environ, {"ASAN_OPTIONS": env_value}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            result = env_vars["ASAN_OPTIONS"]

            # Comma should be replaced with underscore
            assert "option=value_with_commas" in result

    def test_format_options_colons_between_pairs(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test that options are formatted with colons between key=value pairs."""
        _, log_dir, repo_root = temp_dirs

        with patch.dict(
            os.environ, {"ASAN_OPTIONS": "opt1=val1:opt2=val2"}, clear=True
        ):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            result = env_vars["ASAN_OPTIONS"]

            # Should maintain colon-separated format
            parts = result.split(":")
            assert len(parts) >= 2  # At least opt1, opt2, plus log_path, log_exe_name

    def test_get_log_paths(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test get_log_paths returns expected log file paths."""
        _, log_dir, repo_root = temp_dirs

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            log_paths = handler.get_log_paths()
            assert "alubsan" in log_paths
            assert log_paths["alubsan"] == log_dir / "alubsan.log"

    def test_get_log_paths_tsan(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test get_log_paths for TSAN."""
        _, log_dir, repo_root = temp_dirs

        with patch.dict(os.environ, {"TSAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            log_paths = handler.get_log_paths()
            assert "tsan" in log_paths
            assert log_paths["tsan"] == log_dir / "tsan.log"

    def test_multiple_sanitizers(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test handling multiple sanitizers simultaneously."""
        _, log_dir, repo_root = temp_dirs

        env_dict = {
            "ASAN_OPTIONS": "detect_leaks=1",
            "LSAN_OPTIONS": "verbosity=1",
        }
        with patch.dict(os.environ, env_dict, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)

            env_vars = handler.get_env_vars()
            assert "ASAN_OPTIONS" in env_vars
            assert "LSAN_OPTIONS" in env_vars

            # Both should have log paths
            assert "log_path=" in env_vars["ASAN_OPTIONS"]
            assert "log_path=" in env_vars["LSAN_OPTIONS"]


class TestExplicitSanitizer:
    """Test explicit sanitizer from CLI flag."""

    def test_explicit_tsan_sanitizer(self, tmp_path: Path) -> None:
        """Test explicit TSAN sanitizer from CLI."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        with patch.dict(os.environ, {}, clear=True):
            handler = SanitizerHandler(
                binary_path=binary,
                log_dir=log_dir,
                repo_root=tmp_path,
                explicit_sanitizer="tsan",
            )
            assert handler.is_sanitizer_build()
            assert "TSAN_OPTIONS" in handler._detected_sanitizers

    def test_explicit_alubsan_sanitizer(self, tmp_path: Path) -> None:
        """Test explicit ALUBSAN sanitizer from CLI."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        with patch.dict(os.environ, {}, clear=True):
            handler = SanitizerHandler(
                binary_path=binary,
                log_dir=log_dir,
                repo_root=tmp_path,
                explicit_sanitizer="alubsan",
            )
            assert handler.is_sanitizer_build()
            assert "ASAN_OPTIONS" in handler._detected_sanitizers
            assert "LSAN_OPTIONS" in handler._detected_sanitizers
            assert "UBSAN_OPTIONS" in handler._detected_sanitizers

    def test_explicit_tsan_applies_defaults(self, tmp_path: Path) -> None:
        """Test TSAN defaults applied when explicitly requested."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        with patch.dict(os.environ, {}, clear=True):
            handler = SanitizerHandler(
                binary_path=binary,
                log_dir=log_dir,
                repo_root=tmp_path,
                explicit_sanitizer="tsan",
            )
            env_vars = handler.get_env_vars()
            assert "TSAN_OPTIONS" in env_vars
            assert "halt_on_error=0" in env_vars["TSAN_OPTIONS"]
            assert "history_size=7" in env_vars["TSAN_OPTIONS"]

    def test_explicit_alubsan_applies_defaults(self, tmp_path: Path) -> None:
        """Test ALUBSAN defaults applied when explicitly requested."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        with patch.dict(os.environ, {}, clear=True):
            handler = SanitizerHandler(
                binary_path=binary,
                log_dir=log_dir,
                repo_root=tmp_path,
                explicit_sanitizer="alubsan",
            )
            env_vars = handler.get_env_vars()

            # ASAN defaults
            assert "ASAN_OPTIONS" in env_vars
            assert "halt_on_error=0" in env_vars["ASAN_OPTIONS"]
            assert "detect_leaks=1" in env_vars["ASAN_OPTIONS"]

            # LSAN defaults
            assert "LSAN_OPTIONS" in env_vars
            assert "halt_on_error=0" in env_vars["LSAN_OPTIONS"]

            # UBSAN defaults
            assert "UBSAN_OPTIONS" in env_vars
            assert "halt_on_error=0" in env_vars["UBSAN_OPTIONS"]
            assert "print_stacktrace=1" in env_vars["UBSAN_OPTIONS"]

    def test_user_env_overrides_defaults(self, tmp_path: Path) -> None:
        """Test user environment variables override CLI defaults."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        with patch.dict(os.environ, {"TSAN_OPTIONS": "verbosity=2"}, clear=True):
            handler = SanitizerHandler(
                binary_path=binary,
                log_dir=log_dir,
                repo_root=tmp_path,
                explicit_sanitizer="tsan",
            )
            env_vars = handler.get_env_vars()
            # Should have both defaults and user override
            assert "halt_on_error=0" in env_vars["TSAN_OPTIONS"]
            assert "history_size=7" in env_vars["TSAN_OPTIONS"]
            assert "verbosity=2" in env_vars["TSAN_OPTIONS"]

    def test_explicit_takes_priority_over_env_vars(self, tmp_path: Path) -> None:
        """Test explicit sanitizer takes priority over environment variables."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        # Environment suggests ASAN, but we explicitly request TSAN
        with patch.dict(os.environ, {"ASAN_OPTIONS": "detect_leaks=1"}, clear=True):
            handler = SanitizerHandler(
                binary_path=binary,
                log_dir=log_dir,
                repo_root=tmp_path,
                explicit_sanitizer="tsan",
            )
            assert handler.is_sanitizer_build()
            # Should only detect TSAN, not ASAN
            assert "TSAN_OPTIONS" in handler._detected_sanitizers
            assert "ASAN_OPTIONS" not in handler._detected_sanitizers

    def test_no_defaults_when_auto_detected(
        self, mock_binary: Path, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test no defaults applied when sanitizer is auto-detected (not explicit)."""
        _, log_dir, repo_root = temp_dirs

        # Auto-detect via env var (not explicit)
        with patch.dict(os.environ, {"TSAN_OPTIONS": "verbosity=1"}, clear=True):
            handler = SanitizerHandler(mock_binary, log_dir, repo_root)
            env_vars = handler.get_env_vars()

            # Should have user options but NOT defaults
            assert "verbosity=1" in env_vars["TSAN_OPTIONS"]
            # Defaults should NOT be present (no explicit sanitizer)
            assert "halt_on_error=0" not in env_vars["TSAN_OPTIONS"]
            assert "history_size=7" not in env_vars["TSAN_OPTIONS"]


class TestCreateSanitizerHandler:
    """Test create_sanitizer_handler factory function."""

    def test_factory_function(self, temp_dirs: tuple[Path, Path, Path]) -> None:
        """Test factory function creates handler correctly."""
        binary_dir, log_dir, repo_root = temp_dirs
        binary = binary_dir / "arangod"
        binary.touch()

        handler = create_sanitizer_handler(binary, log_dir, repo_root)

        assert isinstance(handler, SanitizerHandler)
        assert handler.binary_path == binary
        assert handler.log_dir == log_dir
        assert handler.repo_root == repo_root

    def test_factory_function_default_repo_root(
        self, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test factory function uses cwd as default repo root."""
        binary_dir, log_dir, _ = temp_dirs
        binary = binary_dir / "arangod"
        binary.touch()

        handler = create_sanitizer_handler(binary, log_dir)

        assert isinstance(handler, SanitizerHandler)
        assert handler.repo_root == Path.cwd()

    def test_factory_function_with_explicit_sanitizer(
        self, temp_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test factory function passes through explicit sanitizer."""
        binary_dir, log_dir, repo_root = temp_dirs
        binary = binary_dir / "arangod"
        binary.touch()

        handler = create_sanitizer_handler(
            binary, log_dir, repo_root, explicit_sanitizer="tsan"
        )

        assert isinstance(handler, SanitizerHandler)
        assert handler._explicit_sanitizer == "tsan"
        assert handler.is_sanitizer_build()
        assert "TSAN_OPTIONS" in handler._detected_sanitizers


class TestCheckSanitizerLogs:
    """Test check_sanitizer_logs functionality."""

    def test_no_logs_when_not_sanitizer_build(self, tmp_path: Path) -> None:
        """Test that no logs are checked when not a sanitizer build."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        with patch.dict(os.environ, {}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.check_sanitizer_logs(12345)

            assert result == []

    def test_no_logs_when_files_dont_exist(self, tmp_path: Path) -> None:
        """Test that empty list is returned when sanitizer log files don't exist."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.check_sanitizer_logs(12345)

            assert result == []

    def test_reads_alubsan_log_file(self, tmp_path: Path) -> None:
        """Test reading ALUBSAN sanitizer log file."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 12345
        log_content = "ERROR: AddressSanitizer: heap-use-after-free\ndetails here..."

        # Create log file with PID suffix
        log_file = log_dir / f"alubsan.log.arangod.{pid}"
        log_file.write_text(log_content)

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.check_sanitizer_logs(pid)

            assert len(result) == 1
            assert result[0].content == log_content
            assert result[0].sanitizer_type == "alubsan"
            assert result[0].file_path == log_file

    def test_reads_tsan_log_file(self, tmp_path: Path) -> None:
        """Test reading TSAN sanitizer log file."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 67890
        log_content = "WARNING: ThreadSanitizer: data race\ndetails here..."

        # Create log file with PID suffix
        log_file = log_dir / f"tsan.log.arangod.{pid}"
        log_file.write_text(log_content)

        with patch.dict(os.environ, {"TSAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.check_sanitizer_logs(pid)

            assert len(result) == 1
            assert result[0].content == log_content
            assert result[0].sanitizer_type == "tsan"
            assert result[0].file_path == log_file

    def test_reads_multiple_sanitizer_logs(self, tmp_path: Path) -> None:
        """Test reading multiple sanitizer log files for same PID."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 11111
        alubsan_content = "ERROR: AddressSanitizer: leak detected"
        tsan_content = "WARNING: ThreadSanitizer: data race"

        # Create both log files
        alubsan_log = log_dir / f"alubsan.log.arangod.{pid}"
        tsan_log = log_dir / f"tsan.log.arangod.{pid}"
        alubsan_log.write_text(alubsan_content)
        tsan_log.write_text(tsan_content)

        with patch.dict(
            os.environ, {"ASAN_OPTIONS": "", "TSAN_OPTIONS": ""}, clear=True
        ):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.check_sanitizer_logs(pid)

            assert len(result) == 2
            # Both sanitizer types should be present
            sanitizer_types = {error.sanitizer_type for error in result}
            assert sanitizer_types == {"alubsan", "tsan"}
            # Both content strings should be present
            contents = {error.content for error in result}
            assert alubsan_content in contents
            assert tsan_content in contents

    def test_ignores_short_content(self, tmp_path: Path) -> None:
        """Test that files with <10 chars of content are ignored."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 22222
        short_content = "short"  # Less than 10 chars

        log_file = log_dir / f"alubsan.log.arangod.{pid}"
        log_file.write_text(short_content)

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.check_sanitizer_logs(pid)

            assert result == []

    def test_handles_read_errors_gracefully(self, tmp_path: Path) -> None:
        """Test that read errors are handled gracefully."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 33333

        # Create a log file path but make it a directory (will cause read error)
        log_file = log_dir / f"alubsan.log.arangod.{pid}"
        log_file.mkdir()

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.check_sanitizer_logs(pid)

            # Should include error message in SanitizerError object
            assert len(result) == 1
            assert "Error reading" in result[0].content

    def test_different_binary_names(self, tmp_path: Path) -> None:
        """Test that different binary names are handled correctly."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangosh"  # Different binary name
        binary.touch()

        pid = 44444
        log_content = "ERROR: AddressSanitizer: heap-buffer-overflow"

        # Log file should use binary name
        log_file = log_dir / f"alubsan.log.arangosh.{pid}"
        log_file.write_text(log_content)

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.check_sanitizer_logs(pid)

            assert len(result) == 1
            assert result[0].content == log_content
            assert result[0].file_path == log_file
            assert "arangosh" in str(result[0].file_path)


class TestCheckSanitizerLogsErrorHandling:
    """Test error handling in check_sanitizer_logs."""

    def test_file_read_error_logged_and_creates_error_object(
        self, tmp_path: Path
    ) -> None:
        """Test file read errors are logged and create SanitizerError objects."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 55555

        # Create a log file path but make it a directory (causes OSError)
        log_file = log_dir / f"alubsan.log.arangod.{pid}"
        log_file.mkdir()

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            # Should log warning and create error object
            result = handler.check_sanitizer_logs(pid)

            assert len(result) == 1
            assert "Error reading sanitizer file" in result[0].content
            assert result[0].sanitizer_type == "alubsan"
            assert result[0].file_path == log_file

    def test_unicode_decode_error_handled(self, tmp_path: Path) -> None:
        """Test unicode decode errors are handled gracefully."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 66666

        # Create log file with invalid UTF-8 bytes
        log_file = log_dir / f"alubsan.log.arangod.{pid}"
        # Write invalid UTF-8 sequence
        log_file.write_bytes(b"\x80\x81\x82 Invalid UTF-8 sequence here")

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            # Should handle gracefully with errors="replace"
            result = handler.check_sanitizer_logs(pid)

            # Content should be readable (with replacement characters)
            assert len(result) == 1
            assert len(result[0].content) > 10  # Not short
            assert result[0].sanitizer_type == "alubsan"

    def test_permission_error_creates_error_object(self, tmp_path: Path) -> None:
        """Test permission errors create SanitizerError objects."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 77777
        log_file = log_dir / f"alubsan.log.arangod.{pid}"
        log_file.write_text("ERROR: Some sanitizer error here")

        with patch.dict(os.environ, {"ASAN_OPTIONS": ""}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            # Mock read_text to raise PermissionError
            with patch.object(
                Path, "read_text", side_effect=PermissionError("Access denied")
            ):
                result = handler.check_sanitizer_logs(pid)

                # Should create error object
                assert len(result) == 1
                assert "Error reading sanitizer file" in result[0].content
                assert "Access denied" in result[0].content


class TestGetSanitizerFilePaths:
    """Test get_sanitizer_file_paths functionality."""

    def test_returns_empty_list_when_not_sanitizer_build(self, tmp_path: Path) -> None:
        """Test empty list returned when not a sanitizer build."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        with patch.dict(os.environ, {}, clear=True):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.get_sanitizer_file_paths(12345)

            assert result == []

    def test_returns_existing_files_only(self, tmp_path: Path) -> None:
        """Test only returns files that actually exist."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 88888

        # Create only ASAN log file, not TSAN
        alubsan_log = log_dir / f"alubsan.log.arangod.{pid}"
        alubsan_log.write_text("Some error")

        with patch.dict(
            os.environ, {"ASAN_OPTIONS": "", "TSAN_OPTIONS": ""}, clear=True
        ):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.get_sanitizer_file_paths(pid)

            # Should only return the file that exists
            assert len(result) == 1
            assert result[0] == alubsan_log

    def test_returns_all_matching_files(self, tmp_path: Path) -> None:
        """Test returns all sanitizer log files for given PID."""
        binary_dir = tmp_path / "bin"
        log_dir = tmp_path / "logs"
        binary_dir.mkdir()
        log_dir.mkdir()
        binary = binary_dir / "arangod"
        binary.touch()

        pid = 99999

        # Create both log files
        alubsan_log = log_dir / f"alubsan.log.arangod.{pid}"
        tsan_log = log_dir / f"tsan.log.arangod.{pid}"
        alubsan_log.write_text("ASAN error")
        tsan_log.write_text("TSAN error")

        with patch.dict(
            os.environ, {"ASAN_OPTIONS": "", "TSAN_OPTIONS": ""}, clear=True
        ):
            handler = SanitizerHandler(binary, log_dir, tmp_path)

            result = handler.get_sanitizer_file_paths(pid)

            # Should return both files
            assert len(result) == 2
            assert alubsan_log in result
            assert tsan_log in result
