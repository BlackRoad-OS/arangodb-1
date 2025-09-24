"""Index API tests - converted from JavaScript to Python.

Original source: tests/js/client/shell/api/index.js
Tests the /_api/index* endpoints
"""

import re
from typing import Dict
import uuid

import pytest
from arango.exceptions import IndexMissingError, IndexGetError


RE_FULL_ID = re.compile(r"^[A-Za-z0-9_\-]+/\d+$")


def _bool(val):
    return bool(val) if val is not None else False


class TestIndexAPI:
    """Test suite for ArangoDB index API endpoints - deployment agnostic."""

    @pytest.fixture
    def collection(self, adb):
        """Create a temporary collection for a test and drop it afterwards."""
        name = "UnitTestsCollectionIndexes"
        adb.create_collection(name)
        try:
            yield adb.collection(name)
        finally:
            adb.delete_collection(name, ignore_missing=True)

    def test_error_unknown_collection_and_index(self, adb):
        # Unknown collection should raise with driver
        with pytest.raises(Exception):
            # Try to get a collection that doesn't exist
            adb.collection("NonExistentCollection123456").get_index("0")

    def test_error_unknown_index_identifier(self, collection):
        col = collection
        with pytest.raises(Exception):
            col.get_index("123456")

    def test_create_unique_hash_index_new_then_existing(self, collection):
        col = collection

        b1 = col.add_index(
            {"type": "hash", "fields": ["a", "b"], "unique": True, "sparse": False}
        )
        # Index ID format is just the numeric ID, not collection/id
        assert b1["id"] is not None
        assert b1["type"] == "hash"
        assert _bool(b1.get("unique")) is True
        assert _bool(b1.get("sparse")) is False
        assert b1.get("fields") == ["a", "b"]
        assert _bool(b1.get("isNewlyCreated") or b1.get("is_newly_created")) is True
        iid = b1["id"]

        b2 = col.add_index(
            {"type": "hash", "fields": ["a", "b"], "unique": True, "sparse": False}
        )
        assert b2["id"] == iid
        assert b2["type"] == "hash"
        assert _bool(b2.get("unique")) is True
        assert _bool(b2.get("sparse")) is False
        assert b2.get("fields") == ["a", "b"]
        assert _bool(b2.get("isNewlyCreated") or b2.get("is_newly_created")) is False
        # teardown handled by fixture

    def test_create_unique_sparse_hash_index(self, collection):
        col = collection

        b1 = col.add_index(
            {"type": "hash", "fields": ["a", "b"], "unique": True, "sparse": True}
        )
        assert b1["type"] == "hash"
        assert _bool(b1.get("unique")) is True
        assert _bool(b1.get("sparse")) is True
        assert b1.get("fields") == ["a", "b"]
        iid = b1["id"]

        b2 = col.add_index(
            {"type": "hash", "fields": ["a", "b"], "unique": True, "sparse": True}
        )
        assert b2["id"] == iid
        assert _bool(b2.get("unique")) is True
        assert _bool(b2.get("sparse")) is True
        # teardown handled by fixture

    def test_create_hash_index_new_then_existing(self, collection):
        col = collection

        b1 = col.add_index(
            {"type": "hash", "fields": ["a", "b"], "unique": False, "sparse": False}
        )
        assert _bool(b1.get("unique")) is False
        assert _bool(b1.get("sparse")) is False

        iid = b1["id"]
        b2 = col.add_index(
            {"type": "hash", "fields": ["a", "b"], "unique": False, "sparse": False}
        )
        assert b2["id"] == iid
        assert _bool(b2.get("unique")) is False
        assert _bool(b2.get("sparse")) is False
        # teardown handled by fixture

    def test_create_hash_index_mixed_sparsity(self, collection):
        col = collection

        b1 = col.add_index(
            {"type": "hash", "fields": ["a", "b"], "unique": False, "sparse": False}
        )
        iid1 = b1["id"]

        b2 = col.add_index(
            {"type": "hash", "fields": ["a", "b"], "unique": False, "sparse": True}
        )
        iid2 = b2["id"]
        assert iid2 != iid1
        # teardown handled by fixture

    def test_skiplist_indexes(self, collection):
        col = collection

        b1 = col.add_index(
            {"type": "skiplist", "fields": ["a", "b"], "unique": False, "sparse": False}
        )
        iid = b1["id"]
        b2 = col.add_index(
            {"type": "skiplist", "fields": ["a", "b"], "unique": False, "sparse": False}
        )
        assert b2["id"] == iid

        b3 = col.add_index(
            {"type": "skiplist", "fields": ["a", "b"], "unique": False, "sparse": True}
        )
        assert _bool(b3.get("sparse")) is True
        # teardown handled by fixture

    def test_reading_all_indexes(self, collection):
        col = collection

        col.add_index(
            {"type": "hash", "fields": ["a"], "unique": False, "sparse": False}
        )
        col.add_index(
            {"type": "hash", "fields": ["b"], "unique": False, "sparse": False}
        )

        idxs = col.indexes()
        assert isinstance(idxs, list)
        # Just check that we have indexes, not the ID format since it's numeric only
        assert len(idxs) >= 3  # primary index + 2 created indexes
        # teardown handled by fixture

    def test_reading_primary_index(self, collection):
        col = collection
        # Get the primary index (index 0)
        b = col.get_index("0")
        assert b["id"] == "0"
        assert b["type"] == "primary"

    def test_deleting_an_index(self, collection):
        col = collection
        b1 = col.add_index(
            {"type": "skiplist", "fields": ["a", "b"], "unique": True, "sparse": False}
        )
        iid = b1["id"]

        assert col.delete_index(iid) is True
        with pytest.raises((IndexMissingError, IndexGetError, Exception)):
            col.get_index(iid)
        # teardown handled by fixture
