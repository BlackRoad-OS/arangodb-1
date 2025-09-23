"""Data codec abstraction with JSON implementation and future VPack support."""
import json
from typing import Any, Protocol, runtime_checkable
from datetime import datetime
from pathlib import Path
from ..core.errors import CodecError, SerializationError, DeserializationError
from ..core.log import get_logger
logger = get_logger(__name__)

@runtime_checkable
class DataCodec(Protocol):
    """Protocol for data encoding/decoding."""

    def encode(self, obj: Any) -> bytes:
        """Encode object to bytes."""

    def decode(self, data: bytes) -> Any:
        """Decode bytes to object."""

class JsonCodec(DataCodec):
    """JSON codec implementation with custom serialization support."""

    def __init__(self, indent: int=2, sort_keys: bool=True) -> None:
        self.indent = indent
        self.sort_keys = sort_keys

    def encode(self, obj: Any) -> bytes:
        """Encode object to JSON bytes."""
        try:
            json_str = json.dumps(obj, indent=self.indent, sort_keys=self.sort_keys, default=self._json_serializer, ensure_ascii=False)
            return json_str.encode('utf-8')
        except Exception as e:
            raise SerializationError(f'Failed to encode object to JSON: {e}') from e

    def decode(self, data: bytes) -> Any:
        """Decode JSON bytes to object."""
        try:
            json_str = data.decode('utf-8')
            return json.loads(json_str, object_hook=self._json_deserializer)
        except json.JSONDecodeError as e:
            raise DeserializationError(f'Invalid JSON data: {e}') from e
        except UnicodeDecodeError as e:
            raise DeserializationError(f'Invalid UTF-8 encoding: {e}') from e
        except Exception as e:
            raise DeserializationError(f'Failed to decode JSON: {e}') from e

    def encode_to_string(self, obj: Any) -> str:
        """Encode object to JSON string."""
        return self.encode(obj).decode('utf-8')

    def decode_from_string(self, json_str: str) -> Any:
        """Decode JSON string to object."""
        return self.decode(json_str.encode('utf-8'))

    def _json_serializer(self, obj: Any) -> Any:
        """Custom JSON serializer for special types."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, Path):
            return str(obj)
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        elif hasattr(obj, '_asdict'):
            return obj._asdict()
        else:
            raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')

    def _json_deserializer(self, dct: dict) -> dict:
        """Custom JSON deserializer hook."""
        return dct

class CompactJsonCodec(JsonCodec):
    """Compact JSON codec without indentation."""

    def __init__(self) -> None:
        super().__init__(indent=None, sort_keys=False)

class VPackCodec(DataCodec):
    """VPack codec placeholder - to be implemented when VPack support is added."""

    def __init__(self) -> None:
        logger.warning('VPack codec is not yet implemented - falling back to JSON')
        self._fallback = JsonCodec()

    def encode(self, obj: Any) -> bytes:
        """Encode using JSON fallback."""
        return self._fallback.encode(obj)

    def decode(self, data: bytes) -> Any:
        """Decode using JSON fallback."""
        return self._fallback.decode(data)

class CodecManager:
    """Manages codec instances and provides codec selection."""

    def __init__(self) -> None:
        self._codecs = {'json': JsonCodec(), 'json_compact': CompactJsonCodec(), 'vpack': VPackCodec()}
        self._default_codec = 'json'

    def get_codec(self, name: str=None) -> DataCodec:
        """Get codec by name."""
        if name is None:
            name = self._default_codec
        if name not in self._codecs:
            raise CodecError(f'Unknown codec: {name}')
        return self._codecs[name]

    def set_default_codec(self, name: str) -> None:
        """Set default codec."""
        if name not in self._codecs:
            raise CodecError(f'Unknown codec: {name}')
        self._default_codec = name
        logger.info('Default codec set to: %s', name)

    def register_codec(self, name: str, codec: DataCodec) -> None:
        """Register a custom codec."""
        self._codecs[name] = codec
        logger.info('Registered codec: %s', name)

    def list_codecs(self) -> list[str]:
        """List available codec names."""
        return list(self._codecs.keys())
_codec_manager = CodecManager()

def get_codec(name: str=None) -> DataCodec:
    """Get codec instance."""
    return _codec_manager.get_codec(name)

def set_default_codec(name: str) -> None:
    """Set default codec."""
    _codec_manager.set_default_codec(name)

def register_codec(name: str, codec: DataCodec) -> None:
    """Register custom codec."""
    _codec_manager.register_codec(name, codec)

def encode_json(obj: Any) -> bytes:
    """Encode object to JSON bytes."""
    return get_codec('json').encode(obj)

def decode_json(data: bytes) -> Any:
    """Decode JSON bytes to object."""
    return get_codec('json').decode(data)

def encode_json_compact(obj: Any) -> bytes:
    """Encode object to compact JSON bytes."""
    return get_codec('json_compact').encode(obj)

def to_json_string(obj: Any) -> str:
    """Convert object to JSON string."""
    codec = get_codec('json')
    if hasattr(codec, 'encode_to_string'):
        return codec.encode_to_string(obj)
    else:
        return codec.encode(obj).decode('utf-8')

def from_json_string(json_str: str) -> Any:
    """Parse JSON string to object."""
    codec = get_codec('json')
    if hasattr(codec, 'decode_from_string'):
        return codec.decode_from_string(json_str)
    else:
        return codec.decode(json_str.encode('utf-8'))