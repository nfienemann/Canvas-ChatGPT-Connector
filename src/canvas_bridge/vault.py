import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Vault:
    """AES-GCM with principal/connection binding; key supplied separately from DB."""

    def __init__(self, key_file: Path):
        key = key_file.read_bytes()
        if len(key) != 32:
            raise ValueError("Vault key must contain exactly 32 random bytes.")
        self.cipher = AESGCM(key)

    def seal(self, payload: dict, owner: str, connection: str) -> str:
        nonce = os.urandom(12)
        aad = f"{owner}:{connection}".encode()
        encrypted = self.cipher.encrypt(nonce, json.dumps(payload).encode(), aad)
        return base64.urlsafe_b64encode(nonce + encrypted).decode()

    def open(self, value: str, owner: str, connection: str) -> dict:
        raw = base64.urlsafe_b64decode(value)
        aad = f"{owner}:{connection}".encode()
        return json.loads(self.cipher.decrypt(raw[:12], raw[12:], aad))
