import importlib

import pytest


@pytest.fixture
def storage(tmp_path, monkeypatch):
    import storage as storage_mod
    importlib.reload(storage_mod)
    # Point the auth/history DB at a throwaway file per test, then re-init schema.
    monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")
    storage_mod._init_schema()
    return storage_mod


def test_register_and_login(storage):
    ok, _ = storage.register_user("Alice", "s3cret")
    assert ok
    ok, _ = storage.login_user("alice", "s3cret")  # username case-insensitive
    assert ok


def test_wrong_password_rejected(storage):
    storage.register_user("bob", "rightpw")
    ok, msg = storage.login_user("bob", "wrongpw")
    assert not ok and "Incorrect" in msg


def test_duplicate_username_rejected(storage):
    storage.register_user("carol", "pw")
    ok, msg = storage.login_user("carol", "pw")
    assert ok
    ok2, _ = storage.register_user("carol", "other")
    assert not ok2


def test_hash_is_salted_and_not_plaintext(storage):
    storage.register_user("dave", "samepw")
    storage.register_user("erin", "samepw")
    rows = dict(storage._fetchall("SELECT username, password_hash FROM users"))
    # Salted: identical passwords → different stored hashes; never plaintext.
    assert rows["dave"] != rows["erin"]
    assert "samepw" not in rows["dave"]
    assert rows["dave"].startswith("pbkdf2$")
