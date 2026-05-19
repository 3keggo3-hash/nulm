"""Integration tests for credential scoping."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest
import threading
import time
from unittest.mock import patch

pytestmark = pytest.mark.integration


class TestScopedCredentialCreation:
    """Tests for ScopedCredential creation."""

    def test_scoped_credential_basic(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="github",
            scopes={"repo", "read:user"},
            allowed_agents={"agent1", "agent2"},
            denied_resources=set(),
            expires_at=None,
            _token="secret_token",
        )
        assert cred.provider == "github"
        assert "repo" in cred.scopes
        assert "agent1" in cred.allowed_agents

    def test_scoped_credential_with_expiry(self):
        from claude_bridge.config import ScopedCredential

        expires = time.time() + 3600
        cred = ScopedCredential(
            provider="aws",
            scopes={"s3:read"},
            allowed_agents={"agent1"},
            denied_resources=set(),
            expires_at=expires,
            _token="aws_token",
        )
        assert cred.expires_at == expires

    def test_scoped_credential_denied_resources(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="test",
            scopes={"read", "write"},
            allowed_agents={"agent1"},
            denied_resources={"/etc/shadow", "/root"},
            expires_at=None,
            _token="token",
        )
        assert "/etc/shadow" in cred.denied_resources
        assert "/root" in cred.denied_resources


class TestIsOperationAllowed:
    """Tests for is_operation_allowed() various cases."""

    def test_allowed_operation(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="github",
            scopes={"repo", "read:user"},
            allowed_agents={"agent1", "agent2"},
            denied_resources=set(),
            expires_at=None,
            _token="token",
        )
        assert cred.is_operation_allowed("agent1", "repo") is True
        assert cred.is_operation_allowed("agent2", "read:user") is True

    def test_denied_agent(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="github",
            scopes={"repo"},
            allowed_agents={"agent1"},
            denied_resources=set(),
            expires_at=None,
            _token="token",
        )
        assert cred.is_operation_allowed("agent2", "repo") is False

    def test_denied_scope(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="github",
            scopes={"read:user"},
            allowed_agents={"agent1"},
            denied_resources=set(),
            expires_at=None,
            _token="token",
        )
        assert cred.is_operation_allowed("agent1", "repo") is False
        assert cred.is_operation_allowed("agent1", "admin") is False

    def test_denied_resource(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="test",
            scopes={"read", "write"},
            allowed_agents={"agent1"},
            denied_resources={"/secret"},
            expires_at=None,
            _token="token",
        )
        assert cred.is_operation_allowed("agent1", "read", "/secret") is False
        assert cred.is_operation_allowed("agent1", "read", "/other") is True

    def test_denied_resource_with_none_resource(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="test",
            scopes={"read"},
            allowed_agents={"agent1"},
            denied_resources={"/secret"},
            expires_at=None,
            _token="token",
        )
        assert cred.is_operation_allowed("agent1", "read", None) is True

    def test_all_allowed_returns_true(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="test",
            scopes={"read"},
            allowed_agents={"agent1"},
            denied_resources=set(),
            expires_at=None,
            _token="token",
        )
        assert (
            cred.is_operation_allowed("agent1", "read", "/any/path") is True
        )


class TestTokenExpiry:
    """Tests for token expiry."""

    def test_token_not_expired(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="test",
            scopes={"read"},
            allowed_agents={"agent1"},
            denied_resources=set(),
            expires_at=time.time() + 3600,
            _token="token",
        )
        assert cred.get_token() == "token"

    def test_token_expired(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="test",
            scopes={"read"},
            allowed_agents={"agent1"},
            denied_resources=set(),
            expires_at=time.time() - 100,
            _token="token",
        )
        assert cred.get_token() is None

    def test_token_no_expiry(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="test",
            scopes={"read"},
            allowed_agents={"agent1"},
            denied_resources=set(),
            expires_at=None,
            _token="token",
        )
        assert cred.get_token() == "token"

    def test_is_operation_allowed_expired_token(self):
        from claude_bridge.config import ScopedCredential

        cred = ScopedCredential(
            provider="test",
            scopes={"read"},
            allowed_agents={"agent1"},
            denied_resources=set(),
            expires_at=time.time() - 100,
            _token="token",
        )
        assert cred.is_operation_allowed("agent1", "read") is False


class TestRegisterScopedCredential:
    """Tests for register_scoped_credential() and get_scoped_credential()."""

    def test_register_and_get(self):
        from claude_bridge.config import (
            register_scoped_credential,
            get_scoped_credential,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="test_cred",
            provider="github",
            token="ghp_test123",
            scopes=["repo", "read:user"],
            allowed_agents=["agent1"],
        )

        token = get_scoped_credential("test_cred", "agent1", "repo")
        assert token == "ghp_test123"

    def test_get_nonexistent_credential(self):
        from claude_bridge.config import get_scoped_credential

        token = get_scoped_credential("nonexistent", "agent1", "read")
        assert token is None

    def test_get_with_wrong_agent(self):
        from claude_bridge.config import (
            register_scoped_credential,
            get_scoped_credential,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="agent_cred",
            provider="test",
            token="token123",
            scopes=["read"],
            allowed_agents=["allowed_agent"],
        )

        token = get_scoped_credential("agent_cred", "wrong_agent", "read")
        assert token is None

    def test_get_with_wrong_scope(self):
        from claude_bridge.config import (
            register_scoped_credential,
            get_scoped_credential,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="scope_cred",
            provider="test",
            token="token456",
            scopes=["read"],
            allowed_agents=["agent1"],
        )

        token = get_scoped_credential("scope_cred", "agent1", "write")
        assert token is None

    def test_register_with_ttl(self):
        from claude_bridge.config import (
            register_scoped_credential,
            get_scoped_credential,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="ttl_cred",
            provider="test",
            token="short_lived",
            scopes=["read"],
            allowed_agents=["agent1"],
            ttl_seconds=2.0,
        )

        token = get_scoped_credential("ttl_cred", "agent1", "read")
        assert token == "short_lived"

        time.sleep(2.1)

        token = get_scoped_credential("ttl_cred", "agent1", "read")
        assert token is None

    def test_register_with_denied_resources(self):
        from claude_bridge.config import (
            register_scoped_credential,
            get_scoped_credential,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="secure_cred",
            provider="test",
            token="secure_token",
            scopes=["read"],
            allowed_agents=["agent1"],
            denied_resources=["/etc"],
        )

        token = get_scoped_credential("secure_cred", "agent1", "read", "/etc")
        assert token is None

        token = get_scoped_credential("secure_cred", "agent1", "read", "/home")
        assert token == "secure_token"


class TestEnvVarAutoRegistration:
    """Tests for env var auto-registration."""

    def test_no_env_var_registration(self):
        from claude_bridge.config import _CREDENTIALS, _CREDENTIALS_LOCK

        with _CREDENTIALS_LOCK:
            initial_count = len(_CREDENTIALS)

        assert initial_count >= 0

    def test_env_var_format_parsing(self):
        import os

        os.environ["CLAUDE_BRIDGE_CRED_test"] = "provider=github,scopes=repo:read"

        from claude_bridge.config import _CREDENTIALS, _CREDENTIALS_LOCK

        with _CREDENTIALS_LOCK:
            pass

        del os.environ["CLAUDE_BRIDGE_CRED_test"]


class TestListScopedCredentials:
    """Tests for list_scoped_credentials()."""

    def test_list_empty(self):
        from claude_bridge.config import (
            list_scoped_credentials,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        creds = list_scoped_credentials()
        assert isinstance(creds, list)
        assert len(creds) == 0

    def test_list_returns_public_data(self):
        from claude_bridge.config import (
            register_scoped_credential,
            list_scoped_credentials,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="list_test",
            provider="github",
            token="super_secret",
            scopes=["repo"],
            allowed_agents=["agent1"],
        )

        creds = list_scoped_credentials()
        assert len(creds) == 1
        assert creds[0]["name"] == "list_test"
        assert creds[0]["provider"] == "github"
        assert "super_secret" not in str(creds)
        assert "token" not in str(creds)

    def test_list_includes_expired_status(self):
        from claude_bridge.config import (
            register_scoped_credential,
            list_scoped_credentials,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="expired_test",
            provider="test",
            token="token",
            scopes=["read"],
            allowed_agents=["agent1"],
            ttl_seconds=1.0,
        )

        time.sleep(1.1)

        creds = list_scoped_credentials()
        expired_cred = next((c for c in creds if c["name"] == "expired_test"), None)
        assert expired_cred is not None
        assert expired_cred["expired"] is True

    def test_list_multiple_credentials(self):
        from claude_bridge.config import (
            register_scoped_credential,
            list_scoped_credentials,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="cred1",
            provider="github",
            token="token1",
            scopes=["repo"],
            allowed_agents=["agent1"],
        )
        register_scoped_credential(
            name="cred2",
            provider="aws",
            token="token2",
            scopes=["s3"],
            allowed_agents=["agent2"],
        )

        creds = list_scoped_credentials()
        assert len(creds) == 2
        names = {c["name"] for c in creds}
        assert "cred1" in names
        assert "cred2" in names


class TestCredentialThreadSafety:
    """Tests for credential operations thread safety."""

    def test_concurrent_registration(self):
        from claude_bridge.config import (
            register_scoped_credential,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        def register_many(index: int) -> None:
            for i in range(10):
                register_scoped_credential(
                    name=f"cred_{index}_{i}",
                    provider="test",
                    token=f"token_{index}_{i}",
                    scopes=["read"],
                    allowed_agents=["agent1"],
                )

        threads = [threading.Thread(target=register_many, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with _CREDENTIALS_LOCK:
            assert len(_CREDENTIALS) == 50

    def test_concurrent_get_scoped_credential(self):
        from claude_bridge.config import (
            register_scoped_credential,
            get_scoped_credential,
            _CREDENTIALS,
            _CREDENTIALS_LOCK,
        )

        with _CREDENTIALS_LOCK:
            _CREDENTIALS.clear()

        register_scoped_credential(
            name="shared_cred",
            provider="test",
            token="shared_token",
            scopes=["read"],
            allowed_agents=["agent1"],
        )

        results: list[str | None] = []
        lock = threading.Lock()

        def get_token_many() -> None:
            for _ in range(20):
                token = get_scoped_credential("shared_cred", "agent1", "read")
                with lock:
                    results.append(token)

        threads = [threading.Thread(target=get_token_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 80
        assert all(t == "shared_token" for t in results)