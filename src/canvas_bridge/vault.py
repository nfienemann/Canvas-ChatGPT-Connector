import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DPAPI_PREFIX = b"bridge-dpapi-v1:"


def _dpapi(value: bytes, *, decrypt=False) -> bytes:
    """Windows user-bound secret protection; never fall back after a DPAPI failure."""
    if os.name != "nt":
        raise ValueError("This vault key requires its Windows account's secret store.")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(value)
    incoming = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ValueError("OS secret protection failed.")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


class Vault:
    """AES-GCM with principal/connection binding; key supplied separately from DB."""

    def __init__(self, key_file: Path):
        key = key_file.read_bytes()
        if key.startswith(DPAPI_PREFIX):
            key = _dpapi(key[len(DPAPI_PREFIX) :], decrypt=True)
        if len(key) != 32:
            raise ValueError("Vault key must contain exactly 32 random bytes.")
        self.cipher = AESGCM(key)
        self.key = key

    @staticmethod
    def create(key_file: Path):
        key = os.urandom(32)
        protected = DPAPI_PREFIX + _dpapi(key) if os.name == "nt" else key
        with key_file.open("xb") as stream:
            stream.write(protected)
        key_file.chmod(0o600)

    def seal(self, payload: dict, owner: str, connection: str) -> str:
        nonce = os.urandom(12)
        aad = f"{owner}:{connection}".encode()
        encrypted = self.cipher.encrypt(nonce, json.dumps(payload).encode(), aad)
        return base64.urlsafe_b64encode(nonce + encrypted).decode()

    def open(self, value: str, owner: str, connection: str) -> dict:
        raw = base64.urlsafe_b64decode(value)
        aad = f"{owner}:{connection}".encode()
        return json.loads(self.cipher.decrypt(raw[:12], raw[12:], aad))
