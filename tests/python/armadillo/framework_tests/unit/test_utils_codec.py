"""Tests for codec utilities."""

import pytest
from datetime import datetime
from pathlib import Path

from armadillo.utils.codec import to_json_string, from_json_string
from armadillo.core.errors import SerializationError, DeserializationError


class TestJsonUtils:
    """Test JSON utility functions."""

    def test_to_json_string_simple_data(self):
        """Test encoding simple data types."""
        data = {"name": "test", "value": 42, "active": True}
        result = to_json_string(data)

        assert isinstance(result, str)
        assert "test" in result
        assert "42" in result
        assert "true" in result

    def test_from_json_string_simple_data(self):
        """Test decoding simple JSON data."""
        json_str = '{"name": "test", "value": 42, "active": true}'
        result = from_json_string(json_str)

        assert result == {"name": "test", "value": 42, "active": True}

    def test_round_trip_maintains_data_integrity(self):
        """Test encode/decode round trip maintains data integrity."""
        original_data = {
            "string": "hello world",
            "number": 123,
            "float": 45.67,
            "boolean": True,
            "null": None,
            "array": [1, 2, 3],
            "nested": {"key": "value"},
        }

        json_str = to_json_string(original_data)
        decoded_data = from_json_string(json_str)

        assert decoded_data == original_data

    def test_custom_serialization_datetime(self):
        """Test encoding special types like datetime and Path."""
        dt = datetime(2023, 1, 1, 12, 0, 0)
        path = Path("/tmp/test")

        data = {"timestamp": dt, "path": path}
        result = to_json_string(data)

        assert "2023-01-01T12:00:00" in result
        assert "/tmp/test" in result

    def test_custom_serialization_object_with_dict(self):
        """Test encoding object with __dict__ attribute."""

        class TestData:
            def __init__(self, name, value):
                self.name = name
                self.value = value

        obj = TestData("test", 42)
        result = to_json_string(obj)

        assert "test" in result
        assert "42" in result

    def test_to_json_string_formatting(self):
        """Test JSON string formatting (indented, sorted)."""
        data = {"z": 1, "a": 2}
        result = to_json_string(data)

        # Should be indented (contains newlines)
        assert "\n" in result
        # Should be sorted (a comes before z)
        assert result.index('"a"') < result.index('"z"')

    def test_serialization_error_handling(self):
        """Test encoding invalid/unserializable type."""
        # Use a type that can't be serialized (like a set, which isn't JSON serializable)
        data = {"invalid": {1, 2, 3}}

        with pytest.raises(SerializationError, match="Failed to encode object to JSON"):
            to_json_string(data)

    def test_deserialization_error_handling(self):
        """Test decoding invalid JSON."""
        invalid_json = '{"invalid": json}'

        with pytest.raises(DeserializationError, match="Failed to decode JSON string"):
            from_json_string(invalid_json)

    def test_empty_data_structures(self):
        """Test encoding empty data structures."""
        empty_dict = {}
        empty_list = []

        assert from_json_string(to_json_string(empty_dict)) == {}
        assert from_json_string(to_json_string(empty_list)) == []

    def test_unicode_handling(self):
        """Test proper Unicode handling in codecs."""
        unicode_data = {"message": "Hello 世界", "emoji": "🚀"}

        json_str = to_json_string(unicode_data)
        decoded = from_json_string(json_str)

        assert decoded == unicode_data
        assert "世界" in json_str
        assert "🚀" in json_str
