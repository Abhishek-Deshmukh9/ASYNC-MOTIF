"""Encrypt connector credentials (Notion tokens, Drive keys, Slack tokens) before they are stored."""
import base64
import hashlib
import json
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretsNotConfigured(RuntimeError):
    pass


def _fernet() -> Fernet:
    material = settings.CONNECTOR_ENCRYPTION_KEY or settings.SUPABASE_SECRET_KEY
    if not material:
        raise SecretsNotConfigured("Set CONNECTOR_ENCRYPTION_KEY (any long random string) in .env so connection tokens can be stored safely.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest()))


def encrypt_credentials(credentials: Dict[str, Any]) -> Dict[str, str]:
    return {"v": "1", "data": _fernet().encrypt(json.dumps(credentials).encode("utf-8")).decode("ascii")}


def decrypt_credentials(stored: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(stored["data"].encode("ascii")).decode("utf-8"))
    except (InvalidToken, KeyError, ValueError) as exc:
        raise SecretsNotConfigured("Stored connection credentials cannot be read. Was the encryption key changed? Reconnect the source.") from exc
