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
