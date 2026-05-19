from claude_bridge.secret_store import LocalSecretStore


class TestLocalSecretStore:
    def test_set_and_get(self):
        store = LocalSecretStore("/tmp/test_secrets.json")
        store.set("test_key", "test_value")
        assert store.get("test_key") == "test_value"
        store.delete("test_key")

    def test_get_nonexistent(self):
        store = LocalSecretStore("/tmp/test_secrets2.json")
        assert store.get("nonexistent") is None

    def test_list(self):
        store = LocalSecretStore("/tmp/test_secrets3.json")
        store.set("key1", "val1")
        store.set("key2", "val2")
        keys = [m.name for m in store.list()]
        assert "key1" in keys
        assert "key2" in keys
        store.delete("key1")
        store.delete("key2")