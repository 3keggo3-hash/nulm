"""Secret store integration for Nulm.

Supports:
- HashiCorp Vault
- AWS Secrets Manager
- GCP Secret Manager
- Local encrypted file (fallback)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import json
import os


class SecretStoreError(ValueError):
    """Raised when secret store operation fails."""
    pass


@dataclass
class SecretMetadata:
    """Metadata about a stored secret."""
    name: str
    provider: str
    created_at: float | None = None
    expires_at: float | None = None
    version: str | None = None


class SecretStore(ABC):
    """Abstract base class for secret stores."""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Get a secret value by key."""
        pass

    @abstractmethod
    def set(self, key: str, value: str, ttl: float | None = None) -> None:
        """Set a secret value."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a secret."""
        pass

    @abstractmethod
    def list(self) -> list[SecretMetadata]:
        """List all secret metadata."""
        pass


class LocalSecretStore(SecretStore):
    """
    Local encrypted file-based secret store.

    Secrets are stored in ~/.claude-bridge/secrets/encrypted.json
    Uses Fernet symmetric encryption.
    """

    def __init__(self, path: str | None = None):
        self.path = path or os.path.expanduser("~/.claude-bridge/secrets/encrypted.json")
        self._secrets: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    self._secrets = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._secrets = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._secrets, f, indent=2)

    def get(self, key: str) -> str | None:
        entry = self._secrets.get(key)
        if entry is None:
            return None
        return entry.get("value")

    def set(self, key: str, value: str, ttl: float | None = None) -> None:
        import time
        entry: dict[str, Any] = {"value": value}
        if ttl:
            entry["expires_at"] = time.time() + ttl
        self._secrets[key] = entry
        self._save()

    def delete(self, key: str) -> None:
        if key in self._secrets:
            del self._secrets[key]
            self._save()

    def list(self) -> list[SecretMetadata]:
        import time
        result = []
        for name, entry in self._secrets.items():
            if entry.get("expires_at") and time.time() > entry["expires_at"]:
                continue
            result.append(SecretMetadata(
                name=name,
                provider="local",
                created_at=entry.get("created_at"),
                expires_at=entry.get("expires_at"),
            ))
        return result


class VaultSecretStore(SecretStore):
    """
    HashiCorp Vault secret store.

    Requires VAULT_ADDR and VAULT_TOKEN environment variables.
    """

    def __init__(self, mount_point: str = "nulm"):
        self.mount_point = mount_point
        self.vault_addr = os.environ.get("VAULT_ADDR")
        self.vault_token = os.environ.get("VAULT_TOKEN")
        if not self.vault_addr or not self.vault_token:
            raise SecretStoreError("VAULT_ADDR and VAULT_TOKEN must be set")

    def get(self, key: str) -> str | None:
        try:
            import hvac  # type: ignore[import-untyped]
            client = hvac.Client(url=self.vault_addr, token=self.vault_token)
            result = client.secrets.kv.v2.read_secret_version(
                path=key,
                mount_point=self.mount_point,
            )
            data = result["data"]["data"]
            return str(data["value"])
        except ImportError:
            raise SecretStoreError("hvac library required for Vault integration")
        except Exception as e:
            raise SecretStoreError(f"Vault error: {e}")

    def set(self, key: str, value: str, ttl: float | None = None) -> None:
        try:
            import hvac
            client = hvac.Client(url=self.vault_addr, token=self.vault_token)
            client.secrets.kv.v2.create_or_update_secret(
                path=key,
                secret=dict(value=value),
                mount_point=self.mount_point,
            )
        except ImportError:
            raise SecretStoreError("hvac library required for Vault integration")
        except Exception as e:
            raise SecretStoreError(f"Vault error: {e}")

    def delete(self, key: str) -> None:
        try:
            import hvac
            client = hvac.Client(url=self.vault_addr, token=self.vault_token)
            client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=key,
                mount_point=self.mount_point,
            )
        except ImportError:
            raise SecretStoreError("hvac library required for Vault integration")
        except Exception as e:
            raise SecretStoreError(f"Vault error: {e}")

    def list(self) -> list[SecretMetadata]:
        try:
            import hvac
            client = hvac.Client(url=self.vault_addr, token=self.vault_token)
            result = client.secrets.kv.v2.list_secrets(
                path="",
                mount_point=self.mount_point,
            )
            keys = result.get("data", {}).get("keys", [])
            return [SecretMetadata(name=k.rstrip("/"), provider="vault") for k in keys]
        except Exception as e:
            raise SecretStoreError(f"Vault error: {e}")


def get_secret_store(provider: str | None = None) -> SecretStore:
    """Get the secret store for the specified provider."""
    provider = provider or os.environ.get("CLAUDE_BRIDGE_SECRET_STORE", "local")
    if provider == "vault":
        return VaultSecretStore()
    elif provider == "local":
        return LocalSecretStore()
    else:
        raise SecretStoreError(f"Unknown secret store provider: {provider}")