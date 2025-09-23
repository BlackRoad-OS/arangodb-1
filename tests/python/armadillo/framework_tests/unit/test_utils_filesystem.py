"""Tests for filesystem utilities."""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, mock_open, Mock

from armadillo.utils.filesystem import (
    FilesystemService, work_dir, server_dir, temp_dir,
    atomic_write, read_text, read_bytes, ensure_dir, safe_remove
)
from armadillo.core.errors import FilesystemError, PathError, AtomicWriteError


class TestFilesystemService:
    """Test FilesystemService class."""

    def test_filesystem_service_creation(self):
        """Test FilesystemService creation."""
        service = FilesystemService()

        assert service._work_dir is None

    def test_work_dir_creation(self, temp_dir):
        """Test work directory creation and caching."""
        service = FilesystemService()

        with patch('armadillo.utils.filesystem.derive_sub_tmp', return_value=temp_dir):
            work_dir1 = service.work_dir()
            work_dir2 = service.work_dir()

            assert work_dir1 == work_dir2  # Should be cached
            assert work_dir1.exists()

    def test_work_dir_from_config(self, temp_dir):
        """Test work directory from configuration."""
        service = FilesystemService()

        with patch('armadillo.utils.filesystem.get_config') as mock_config:
            mock_config.return_value.work_dir = temp_dir

            work_dir = service.work_dir()

            assert work_dir == temp_dir
            assert work_dir.exists()

    def test_server_dir_creation(self, temp_dir):
        """Test server directory creation."""
        service = FilesystemService()

        with patch.object(service, 'work_dir', return_value=temp_dir):
            server_dir = service.server_dir("test_server")

            assert server_dir == temp_dir / "servers" / "test_server"
            assert server_dir.exists()

    def test_temp_dir_creation(self, temp_dir):
        """Test temporary directory creation."""
        service = FilesystemService()

        with patch('armadillo.utils.filesystem.derive_sub_tmp', return_value=temp_dir):
            with patch('tempfile.mkdtemp') as mock_mkdtemp:
                mock_mkdtemp.return_value = str(temp_dir / "temp_123")

                result = service.temp_dir("test")

                mock_mkdtemp.assert_called_once()
                assert result == Path(temp_dir / "temp_123")

    def test_atomic_write_text(self, temp_dir):
        """Test atomic write with text data."""
        service = FilesystemService()
        target_file = temp_dir / "test.txt"
        content = "Hello, World!"

        service.atomic_write(target_file, content)

        assert target_file.exists()
        assert target_file.read_text() == content

    def test_atomic_write_bytes(self, temp_dir):
        """Test atomic write with binary data."""
        service = FilesystemService()
        target_file = temp_dir / "test.bin"
        content = b"Binary content"

        service.atomic_write(target_file, content, "wb")

        assert target_file.exists()
        assert target_file.read_bytes() == content

    def test_atomic_write_creates_parent_dirs(self, temp_dir):
        """Test atomic write creates parent directories."""
        service = FilesystemService()
        target_file = temp_dir / "nested" / "deep" / "test.txt"
        content = "Nested content"

        service.atomic_write(target_file, content)

        assert target_file.exists()
        assert target_file.read_text() == content
        assert target_file.parent.exists()

    @patch('tempfile.NamedTemporaryFile')
    def test_atomic_write_failure_cleanup(self, mock_temp_file, temp_dir):
        """Test atomic write cleans up on failure."""
        service = FilesystemService()
        target_file = temp_dir / "test.txt"

        # Mock temporary file that fails during write
        mock_temp = Mock()
        mock_temp.name = str(temp_dir / ".test.txt.tmp123")
        mock_temp.__enter__ = Mock(side_effect=OSError("Write failed"))
        mock_temp.__exit__ = Mock(return_value=None)
        mock_temp_file.return_value = mock_temp

        with pytest.raises(AtomicWriteError):
            service.atomic_write(target_file, "content")

    def test_read_text_success(self, temp_dir):
        """Test successful text file reading."""
        service = FilesystemService()
        test_file = temp_dir / "test.txt"
        content = "Test content with üñíçödé"

        test_file.write_text(content, encoding='utf-8')

        result = service.read_text(test_file)
        assert result == content

    def test_read_text_file_not_found(self, temp_dir):
        """Test reading non-existent text file."""
        service = FilesystemService()
        nonexistent_file = temp_dir / "nonexistent.txt"

        with pytest.raises(PathError, match="File not found"):
            service.read_text(nonexistent_file)

    def test_read_text_permission_error(self, temp_dir):
        """Test reading text file with permission error."""
        service = FilesystemService()
        test_file = temp_dir / "restricted.txt"
        test_file.write_text("content")

        with patch('pathlib.Path.read_text', side_effect=PermissionError("Access denied")):
            with pytest.raises(FilesystemError, match="Permission denied"):
                service.read_text(test_file)

    def test_read_text_encoding_error(self, temp_dir):
        """Test reading text file with encoding error."""
        service = FilesystemService()
        test_file = temp_dir / "binary.txt"

        # Write binary data that can't be decoded as UTF-8
        test_file.write_bytes(b'\xff\xfe\x00\x00')

        with pytest.raises(FilesystemError, match="Encoding error"):
            service.read_text(test_file)

    def test_read_bytes_success(self, temp_dir):
        """Test successful binary file reading."""
        service = FilesystemService()
        test_file = temp_dir / "test.bin"
        content = b'\x00\x01\x02\x03\xff\xfe\xfd'

        test_file.write_bytes(content)

        result = service.read_bytes(test_file)
        assert result == content

    def test_read_bytes_file_not_found(self, temp_dir):
        """Test reading non-existent binary file."""
        service = FilesystemService()
        nonexistent_file = temp_dir / "nonexistent.bin"

        with pytest.raises(PathError, match="File not found"):
            service.read_bytes(nonexistent_file)

    def test_ensure_dir_new_directory(self, temp_dir):
        """Test ensuring new directory exists."""
        service = FilesystemService()
        new_dir = temp_dir / "new" / "nested" / "directory"

        result = service.ensure_dir(new_dir)

        assert result == new_dir
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_ensure_dir_existing_directory(self, temp_dir):
        """Test ensuring existing directory."""
        service = FilesystemService()
        existing_dir = temp_dir / "existing"
        existing_dir.mkdir()

        result = service.ensure_dir(existing_dir)

        assert result == existing_dir
        assert existing_dir.exists()

    def test_ensure_dir_permission_error(self, temp_dir):
        """Test ensure directory with permission error."""
        service = FilesystemService()

        with patch('pathlib.Path.mkdir', side_effect=PermissionError("Access denied")):
            with pytest.raises(FilesystemError, match="Permission denied"):
                service.ensure_dir(temp_dir / "restricted")

    def test_safe_remove_file(self, temp_dir):
        """Test safely removing a file."""
        service = FilesystemService()
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        result = service.safe_remove(test_file)

        assert result is True
        assert not test_file.exists()

    def test_safe_remove_directory(self, temp_dir):
        """Test safely removing a directory."""
        service = FilesystemService()
        test_dir = temp_dir / "test_dir"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")

        result = service.safe_remove(test_dir)

        assert result is True
        assert not test_dir.exists()

    def test_safe_remove_nonexistent(self, temp_dir):
        """Test safely removing non-existent path."""
        service = FilesystemService()
        nonexistent = temp_dir / "nonexistent"

        result = service.safe_remove(nonexistent)

        assert result is False

    def test_safe_remove_error_handling(self, temp_dir):
        """Test safe remove with error (should not raise)."""
        service = FilesystemService()
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        with patch('pathlib.Path.unlink', side_effect=OSError("Permission denied")):
            result = service.safe_remove(test_file)

            assert result is False
            # File should still exist due to mocked error

    def test_copy_file_success(self, temp_dir):
        """Test successful file copying."""
        service = FilesystemService()
        src_file = temp_dir / "source.txt"
        dst_file = temp_dir / "destination.txt"
        content = "File content"

        src_file.write_text(content)

        service.copy_file(src_file, dst_file)

        assert dst_file.exists()
        assert dst_file.read_text() == content

    def test_copy_file_creates_parent_dirs(self, temp_dir):
        """Test copy file creates parent directories."""
        service = FilesystemService()
        src_file = temp_dir / "source.txt"
        dst_file = temp_dir / "nested" / "deep" / "destination.txt"
        content = "File content"

        src_file.write_text(content)

        service.copy_file(src_file, dst_file)

        assert dst_file.exists()
        assert dst_file.read_text() == content

    def test_copy_file_preserve_metadata(self, temp_dir):
        """Test copy file with metadata preservation."""
        service = FilesystemService()
        src_file = temp_dir / "source.txt"
        dst_file = temp_dir / "destination.txt"

        src_file.write_text("content")

        with patch('shutil.copy2') as mock_copy2:
            service.copy_file(src_file, dst_file, preserve_metadata=True)
            mock_copy2.assert_called_once_with(src_file, dst_file)

    def test_copy_file_no_preserve_metadata(self, temp_dir):
        """Test copy file without metadata preservation."""
        service = FilesystemService()
        src_file = temp_dir / "source.txt"
        dst_file = temp_dir / "destination.txt"

        src_file.write_text("content")

        with patch('shutil.copy') as mock_copy:
            service.copy_file(src_file, dst_file, preserve_metadata=False)
            mock_copy.assert_called_once_with(src_file, dst_file)

    def test_copy_file_source_not_found(self, temp_dir):
        """Test copying non-existent source file."""
        service = FilesystemService()
        src_file = temp_dir / "nonexistent.txt"
        dst_file = temp_dir / "destination.txt"

        with pytest.raises(PathError, match="Source file not found"):
            service.copy_file(src_file, dst_file)

    def test_get_size(self, temp_dir):
        """Test getting file size."""
        service = FilesystemService()
        test_file = temp_dir / "test.txt"
        content = "This is test content"

        test_file.write_text(content)

        size = service.get_size(test_file)

        assert size == len(content.encode('utf-8'))

    def test_get_size_file_not_found(self, temp_dir):
        """Test getting size of non-existent file."""
        service = FilesystemService()
        nonexistent_file = temp_dir / "nonexistent.txt"

        with pytest.raises(PathError, match="File not found"):
            service.get_size(nonexistent_file)

    def test_list_files_simple(self, temp_dir):
        """Test listing files in directory."""
        service = FilesystemService()

        # Create test files
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.txt").write_text("content2")
        (temp_dir / "other.log").write_text("log content")

        files = service.list_files(temp_dir, "*.txt")

        file_names = {f.name for f in files}
        assert file_names == {"file1.txt", "file2.txt"}

    def test_list_files_recursive(self, temp_dir):
        """Test recursive file listing."""
        service = FilesystemService()

        # Create nested structure
        (temp_dir / "file1.txt").write_text("content1")
        nested_dir = temp_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / "file2.txt").write_text("content2")

        files = service.list_files(temp_dir, "*.txt", recursive=True)

        file_names = {f.name for f in files}
        assert file_names == {"file1.txt", "file2.txt"}

    def test_list_files_directory_not_found(self, temp_dir):
        """Test listing files in non-existent directory."""
        service = FilesystemService()
        nonexistent_dir = temp_dir / "nonexistent"

        with pytest.raises(FilesystemError, match="Error listing files|Directory not found"):
            service.list_files(nonexistent_dir)

    def test_temp_file_context_manager(self, temp_dir):
        """Test temporary file context manager."""
        service = FilesystemService()

        with patch.object(service, 'temp_dir', return_value=temp_dir):
            with service.temp_file(suffix=".txt", prefix="test") as temp_file:
                assert temp_file.exists()
                assert temp_file.suffix == ".txt"
                temp_file.write_text("temp content")

            # File should be cleaned up after context exit
            assert not temp_file.exists()

    def test_cleanup_work_dir(self, temp_dir):
        """Test work directory cleanup."""
        service = FilesystemService()
        service._work_dir = temp_dir

        # Create some content
        (temp_dir / "test.txt").write_text("content")

        service.cleanup_work_dir()

        assert not temp_dir.exists()


class TestGlobalFilesystemFunctions:
    """Test global filesystem utility functions."""

    def test_global_work_dir(self):
        """Test global work_dir function."""
        with patch('armadillo.utils.filesystem._filesystem_service') as mock_service:
            mock_service.work_dir.return_value = Path("/tmp/work")

            result = work_dir()

            mock_service.work_dir.assert_called_once()
            assert result == Path("/tmp/work")

    def test_global_server_dir(self):
        """Test global server_dir function."""
        with patch('armadillo.utils.filesystem._filesystem_service') as mock_service:
            mock_service.server_dir.return_value = Path("/tmp/servers/test")

            result = server_dir("test")

            mock_service.server_dir.assert_called_once_with("test")
            assert result == Path("/tmp/servers/test")

    def test_global_temp_dir(self):
        """Test global temp_dir function."""
        with patch('armadillo.utils.filesystem._filesystem_service') as mock_service:
            mock_service.temp_dir.return_value = Path("/tmp/temp123")

            result = temp_dir("prefix")

            mock_service.temp_dir.assert_called_once_with("prefix")
            assert result == Path("/tmp/temp123")

    def test_global_atomic_write(self, temp_dir):
        """Test global atomic_write function."""
        test_file = temp_dir / "test.txt"
        content = "Global write test"

        atomic_write(test_file, content)

        assert test_file.exists()
        assert test_file.read_text() == content

    def test_global_read_text(self, temp_dir):
        """Test global read_text function."""
        test_file = temp_dir / "test.txt"
        content = "Global read test"
        test_file.write_text(content)

        result = read_text(test_file)

        assert result == content

    def test_global_read_bytes(self, temp_dir):
        """Test global read_bytes function."""
        test_file = temp_dir / "test.bin"
        content = b"Global read bytes test"
        test_file.write_bytes(content)

        result = read_bytes(test_file)

        assert result == content

    def test_global_ensure_dir(self, temp_dir):
        """Test global ensure_dir function."""
        new_dir = temp_dir / "new_dir"

        result = ensure_dir(new_dir)

        assert result == new_dir
        assert new_dir.exists()

    def test_global_safe_remove(self, temp_dir):
        """Test global safe_remove function."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        result = safe_remove(test_file)

        assert result is True
        assert not test_file.exists()
