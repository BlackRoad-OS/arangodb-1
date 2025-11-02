"""Simple JSON utilities for data serialization."""

import json
from typing import Any
from datetime import datetime
from pathlib import Path
from ..core.errors import SerializationError, DeserializationError


def to_json_string(obj: Any) -> str:
    """Convert object to JSON string with custom serialization support."""
    try:
        return json.dumps(
            obj,
            indent=2,
            sort_keys=True,
            default=_json_serializer,
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as e:
        raise SerializationError(f"Failed to encode object to JSON: {e}") from e


def from_json_string(json_str: str) -> Any:
    """Parse JSON string to object."""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise DeserializationError(f"Failed to decode JSON string: {e}") from e


def _json_serializer(obj: Any) -> Any:
    """Custom JSON serializer for special types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Path):
        return str(obj)
    elif hasattr(obj, "model_dump"):
        # Pydantic v2 BaseModel
        return obj.model_dump()
    elif hasattr(obj, "_asdict"):
        return obj._asdict()
    elif hasattr(obj, "__dict__"):
        return obj.__dict__
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
