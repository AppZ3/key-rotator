"""
Keyring-backed secret storage. All management credentials and key backups
live here — never in plaintext config or logs.
"""
import keyring
from typing import Optional

_SERVICE = "key-rotator"


def _k(key_id: str, field: str) -> str:
    return f"{key_id}.{field}"


def store(key_id: str, field: str, value: str) -> None:
    keyring.set_password(_SERVICE, _k(key_id, field), value)


def get(key_id: str, field: str) -> Optional[str]:
    return keyring.get_password(_SERVICE, _k(key_id, field))


def delete(key_id: str, field: str) -> None:
    try:
        keyring.delete_password(_SERVICE, _k(key_id, field))
    except keyring.errors.PasswordDeleteError:
        pass


def backup_value(key_id: str, value: str) -> None:
    store(key_id, "backup_value", value)


def get_backup_value(key_id: str) -> Optional[str]:
    return get(key_id, "backup_value")


def get_mgmt_cred(key_id: str, cred_name: str) -> Optional[str]:
    return get(key_id, f"mgmt.{cred_name}")


def store_mgmt_cred(key_id: str, cred_name: str, value: str) -> None:
    store(key_id, f"mgmt.{cred_name}", value)
