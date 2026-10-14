"""Secrets live in Windows Credential Manager via keyring, never in the database."""
import keyring
from keyring.errors import KeyringError

from core.config import KEYRING_SERVICE


def get_secret(name: str) -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, name)
    except KeyringError:
        return None


def set_secret(name: str, value: str):
    keyring.set_password(KEYRING_SERVICE, name, value)


def delete_secret(name: str):
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except KeyringError:
        pass
