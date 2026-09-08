"""Local object store backend tests (Phase 19)."""

import uuid

import pytest

from app.objectstore.factory import get_object_store, reset_object_store
from app.objectstore.local import LocalObjectStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORE_LOCAL_PATH", str(tmp_path / "objects"))
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "")
    reset_object_store()
    s = get_object_store()
    yield s
    reset_object_store()


def test_put_get_delete_exists(store):
    key = f"test/{uuid.uuid4().hex}.txt"
    assert not store.exists(key)
    with pytest.raises(FileNotFoundError):
        store.get(key)
    store.put(key, b"hello", mime_type="text/plain")
    assert store.exists(key)
    assert store.get(key) == b"hello"
    assert store.delete(key) is True
    assert not store.exists(key)
    assert store.delete(key) is False


def test_workspace_isolation_via_keys(store):
    # Keys are namespaced by workspace prefix; a direct store doesn't enforce
    # ACL, but the API layer must. Here we just verify distinct keys don't collide.
    k1 = f"ws_a/{uuid.uuid4().hex}.bin"
    k2 = f"ws_b/{uuid.uuid4().hex}.bin"
    store.put(k1, b"a")
    store.put(k2, b"b")
    assert store.get(k1) == b"a"
    assert store.get(k2) == b"b"
    store.delete(k1)
    assert not store.exists(k1)
    assert store.exists(k2)
