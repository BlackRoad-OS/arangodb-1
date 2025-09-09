"""Tests for data codec utilities."""

import pytest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from armadillo.utils.codec import (
    JsonCodec, CompactJsonCodec, VPackCodec, CodecManager,
    get_codec, set_default_codec, register_codec,
    encode_json, decode_json, encode_json_compact,
    to_json_string, from_json_string
)
from armadillo.core.errors import CodecError, SerializationError, DeserializationError


class TestJsonCodec:
    """Test JsonCodec implementation."""

    def test_json_codec_creation(self):
        """Test JsonCodec creation with default parameters."""
        codec = JsonCodec()

        assert codec.indent == 2
        assert codec.sort_keys is True

    def test_json_codec_custom_params(self):
        """Test JsonCodec creation with custom parameters."""
        codec = JsonCodec(indent=4, sort_keys=False)

        assert codec.indent == 4
        assert codec.sort_keys is False

    def test_encode_simple_data(self):
        """Test encoding simple data types."""
        codec = JsonCodec()

        data = {
            'string': 'hello',
            'number': 42,
            'float': 3.14,
            'boolean': True,
            'null': None,
            'list': [1, 2, 3],
            'nested': {'key': 'value'}
        }

        encoded = codec.encode(data)

        assert isinstance(encoded, bytes)

        # Should be valid JSON
        decoded_dict = json.loads(encoded.decode('utf-8'))
        assert decoded_dict == data

    def test_encode_with_indentation(self):
        """Test encoding with proper indentation."""
        codec = JsonCodec(indent=2)

        data = {'key': 'value', 'nested': {'inner': 'data'}}
        encoded = codec.encode(data)
        json_str = encoded.decode('utf-8')

        # Should have indentation
        assert '  ' in json_str
        assert json_str.count('\n') > 0

    def test_encode_with_sorting(self):
        """Test encoding with key sorting."""
        codec = JsonCodec(sort_keys=True)

        data = {'z': 1, 'a': 2, 'm': 3}
        encoded = codec.encode(data)
        json_str = encoded.decode('utf-8')

        # Keys should be sorted alphabetically
        assert json_str.index('"a"') < json_str.index('"m"') < json_str.index('"z"')

    def test_decode_simple_data(self):
        """Test decoding simple JSON data."""
        codec = JsonCodec()

        data = {'key': 'value', 'number': 42}
        json_bytes = json.dumps(data).encode('utf-8')

        decoded = codec.decode(json_bytes)

        assert decoded == data

    def test_encode_decode_round_trip(self):
        """Test encode/decode round trip maintains data integrity."""
        codec = JsonCodec()

        original_data = {
            'string': 'test string',
            'number': 12345,
            'float': 3.14159,
            'boolean_true': True,
            'boolean_false': False,
            'null_value': None,
            'empty_list': [],
            'list_with_data': [1, 'two', 3.0, True, None],
            'empty_dict': {},
            'nested_dict': {
                'level1': {
                    'level2': {
                        'level3': 'deep_value'
                    }
                }
            },
            'unicode': 'Hello 世界! 🌍'
        }

        encoded = codec.encode(original_data)
        decoded = codec.decode(encoded)

        assert decoded == original_data

    def test_encode_special_types(self):
        """Test encoding special types like datetime and Path."""
        codec = JsonCodec()

        now = datetime.now()
        path = Path("/tmp/test")

        data = {
            'datetime': now,
            'path': path,
        }

        encoded = codec.encode(data)
        decoded = codec.decode(encoded)

        # Should serialize to strings
        assert decoded['datetime'] == now.isoformat()
        assert decoded['path'] == str(path)

    def test_encode_dataclass_object(self):
        """Test encoding dataclass objects."""
        from dataclasses import dataclass

        @dataclass
        class TestData:
            name: str
            value: int

        codec = JsonCodec()
        obj = TestData("test", 42)

        encoded = codec.encode({'obj': obj})
        decoded = codec.decode(encoded)

        assert decoded['obj']['name'] == "test"
        assert decoded['obj']['value'] == 42

    def test_encode_to_string(self):
        """Test encoding to JSON string."""
        codec = JsonCodec()

        data = {'key': 'value'}
        result = codec.encode_to_string(data)

        assert isinstance(result, str)
        assert json.loads(result) == data

    def test_decode_from_string(self):
        """Test decoding from JSON string."""
        codec = JsonCodec()

        data = {'key': 'value'}
        json_str = json.dumps(data)

        result = codec.decode_from_string(json_str)

        assert result == data

    def test_encode_invalid_type(self):
        """Test encoding invalid/unserializable type."""
        codec = JsonCodec()

        class UnserializableClass:
            pass

        data = {'obj': UnserializableClass()}

        with pytest.raises(SerializationError):
            codec.encode(data)

    def test_decode_invalid_json(self):
        """Test decoding invalid JSON."""
        codec = JsonCodec()

        invalid_json = b'{"invalid": json, "missing": "quote}'

        with pytest.raises(DeserializationError):
            codec.decode(invalid_json)

    def test_decode_invalid_utf8(self):
        """Test decoding invalid UTF-8 bytes."""
        codec = JsonCodec()

        invalid_utf8 = b'\xff\xfe\x00\x00'

        with pytest.raises(DeserializationError):
            codec.decode(invalid_utf8)


class TestCompactJsonCodec:
    """Test CompactJsonCodec implementation."""

    def test_compact_codec_creation(self):
        """Test CompactJsonCodec creation."""
        codec = CompactJsonCodec()

        assert codec.indent is None
        assert codec.sort_keys is False

    def test_compact_encoding(self):
        """Test compact encoding produces minimal JSON."""
        codec = CompactJsonCodec()

        data = {'key': 'value', 'nested': {'inner': 'data'}}
        encoded = codec.encode(data)
        json_str = encoded.decode('utf-8')

        # Should not have indentation or extra whitespace
        assert '  ' not in json_str
        assert '\n' not in json_str
        assert json_str.count(' ') == 0  # No spaces around colons/commas


class TestVPackCodec:
    """Test VPackCodec placeholder implementation."""

    def test_vpack_codec_creation(self):
        """Test VPackCodec creation."""
        codec = VPackCodec()

        # Should have fallback to JsonCodec
        assert hasattr(codec, '_fallback')
        assert isinstance(codec._fallback, JsonCodec)

    def test_vpack_encode_fallback(self):
        """Test VPackCodec encode falls back to JSON."""
        codec = VPackCodec()

        data = {'key': 'value'}
        encoded = codec.encode(data)

        # Should produce JSON output (fallback)
        decoded_dict = json.loads(encoded.decode('utf-8'))
        assert decoded_dict == data

    def test_vpack_decode_fallback(self):
        """Test VPackCodec decode falls back to JSON."""
        codec = VPackCodec()

        data = {'key': 'value'}
        json_bytes = json.dumps(data).encode('utf-8')

        decoded = codec.decode(json_bytes)

        assert decoded == data


class TestCodecManager:
    """Test CodecManager class."""

    def test_codec_manager_creation(self):
        """Test CodecManager creation with default codecs."""
        manager = CodecManager()

        assert 'json' in manager._codecs
        assert 'json_compact' in manager._codecs
        assert 'vpack' in manager._codecs
        assert manager._default_codec == 'json'

    def test_get_codec_default(self):
        """Test getting default codec."""
        manager = CodecManager()

        codec = manager.get_codec()

        assert isinstance(codec, JsonCodec)

    def test_get_codec_by_name(self):
        """Test getting codec by name."""
        manager = CodecManager()

        json_codec = manager.get_codec('json')
        compact_codec = manager.get_codec('json_compact')
        vpack_codec = manager.get_codec('vpack')

        assert isinstance(json_codec, JsonCodec)
        assert isinstance(compact_codec, CompactJsonCodec)
        assert isinstance(vpack_codec, VPackCodec)

    def test_get_codec_invalid_name(self):
        """Test getting codec with invalid name."""
        manager = CodecManager()

        with pytest.raises(CodecError, match="Unknown codec"):
            manager.get_codec('nonexistent')

    def test_set_default_codec(self):
        """Test setting default codec."""
        manager = CodecManager()

        manager.set_default_codec('json_compact')

        assert manager._default_codec == 'json_compact'

        # Default should now return compact codec
        codec = manager.get_codec()
        assert isinstance(codec, CompactJsonCodec)

    def test_set_default_codec_invalid(self):
        """Test setting invalid default codec."""
        manager = CodecManager()

        with pytest.raises(CodecError, match="Unknown codec"):
            manager.set_default_codec('nonexistent')

    def test_register_codec(self):
        """Test registering custom codec."""
        manager = CodecManager()

        class CustomCodec:
            def encode(self, obj):
                return b'custom'
            def decode(self, data):
                return {'custom': True}

        custom_codec = CustomCodec()
        manager.register_codec('custom', custom_codec)

        assert 'custom' in manager._codecs
        retrieved_codec = manager.get_codec('custom')
        assert retrieved_codec is custom_codec

    def test_list_codecs(self):
        """Test listing available codecs."""
        manager = CodecManager()

        codecs = manager.list_codecs()

        assert 'json' in codecs
        assert 'json_compact' in codecs
        assert 'vpack' in codecs


class TestGlobalCodecFunctions:
    """Test global codec utility functions."""

    def test_get_codec_function(self):
        """Test global get_codec function."""
        with patch('armadillo.utils.codec._codec_manager') as mock_manager:
            mock_codec = JsonCodec()
            mock_manager.get_codec.return_value = mock_codec

            result = get_codec('json')

            mock_manager.get_codec.assert_called_once_with('json')
            assert result is mock_codec

    def test_set_default_codec_function(self):
        """Test global set_default_codec function."""
        with patch('armadillo.utils.codec._codec_manager') as mock_manager:
            set_default_codec('json_compact')

            mock_manager.set_default_codec.assert_called_once_with('json_compact')

    def test_register_codec_function(self):
        """Test global register_codec function."""
        with patch('armadillo.utils.codec._codec_manager') as mock_manager:
            codec = JsonCodec()
            register_codec('test', codec)

            mock_manager.register_codec.assert_called_once_with('test', codec)

    def test_encode_json_function(self):
        """Test global encode_json function."""
        data = {'key': 'value'}

        result = encode_json(data)

        assert isinstance(result, bytes)
        decoded = json.loads(result.decode('utf-8'))
        assert decoded == data

    def test_decode_json_function(self):
        """Test global decode_json function."""
        data = {'key': 'value'}
        json_bytes = json.dumps(data).encode('utf-8')

        result = decode_json(json_bytes)

        assert result == data

    def test_encode_json_compact_function(self):
        """Test global encode_json_compact function."""
        data = {'key': 'value'}

        result = encode_json_compact(data)

        assert isinstance(result, bytes)
        json_str = result.decode('utf-8')
        assert '\n' not in json_str  # Should be compact

    def test_to_json_string_function(self):
        """Test global to_json_string function."""
        data = {'key': 'value'}

        result = to_json_string(data)

        assert isinstance(result, str)
        assert json.loads(result) == data

    def test_from_json_string_function(self):
        """Test global from_json_string function."""
        data = {'key': 'value'}
        json_str = json.dumps(data)

        result = from_json_string(json_str)

        assert result == data


class TestCodecEdgeCases:
    """Test codec edge cases and error conditions."""

    def test_large_data_encoding(self):
        """Test encoding large data structures."""
        codec = JsonCodec()

        # Create large nested structure
        large_data = {'items': [{'id': i, 'data': 'x' * 1000} for i in range(100)]}

        encoded = codec.encode(large_data)
        decoded = codec.decode(encoded)

        assert decoded == large_data

    def test_deeply_nested_data(self):
        """Test encoding deeply nested data structures."""
        codec = JsonCodec()

        # Create deeply nested structure
        nested_data = {}
        current = nested_data
        for i in range(50):
            current['level'] = i
            current['nested'] = {}
            current = current['nested']
        current['final'] = 'value'

        encoded = codec.encode(nested_data)
        decoded = codec.decode(encoded)

        assert decoded == nested_data

    def test_unicode_handling(self):
        """Test proper Unicode handling in codecs."""
        codec = JsonCodec()

        unicode_data = {
            'english': 'Hello World',
            'chinese': '你好世界',
            'emoji': '🌍🚀✨',
            'mixed': 'Hello 世界! 🌍'
        }

        encoded = codec.encode(unicode_data)
        decoded = codec.decode(encoded)

        assert decoded == unicode_data

    def test_empty_data_structures(self):
        """Test encoding empty data structures."""
        codec = JsonCodec()

        empty_data = {
            'empty_dict': {},
            'empty_list': [],
            'empty_string': '',
            'null_value': None
        }

        encoded = codec.encode(empty_data)
        decoded = codec.decode(encoded)

        assert decoded == empty_data
