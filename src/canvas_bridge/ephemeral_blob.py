"""Authenticated chunked staging. Keys never enter a database, URL or file."""

import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BLOCK = 64 * 1024


def storage_size(size):
    return size + ((size + BLOCK - 1) // BLOCK + 1) * 32


class Writer:
    def __init__(self, stream, key, binding):
        self.stream, self.cipher, self.binding = stream, AESGCM(key), binding
        self.buffer, self.index = bytearray(), 0

    def frame(self, value):
        nonce = os.urandom(12)
        encrypted = self.cipher.encrypt(nonce, value, self.binding + self.index.to_bytes(8, "big"))
        self.stream.write(struct.pack(">I", len(encrypted)) + nonce + encrypted)
        self.index += 1

    def write(self, value):
        self.buffer.extend(value)
        while len(self.buffer) >= BLOCK:
            self.frame(bytes(self.buffer[:BLOCK]))
            del self.buffer[:BLOCK]
        return len(value)

    def flush(self):
        self.stream.flush()

    def finish(self):
        if self.buffer:
            self.frame(bytes(self.buffer))
            self.buffer.clear()
        self.frame(b"")  # Authenticated end marker detects truncation, even empty files.
        self.flush()


def chunks(path, key, binding):
    if key is None:
        raise OSError("Staged object key was destroyed.")
    cipher, index = AESGCM(key), 0
    try:
        with path.open("rb") as stream:
            while True:
                header = stream.read(4)
                if len(header) != 4:
                    raise OSError("Truncated staged object.")
                size = struct.unpack(">I", header)[0]
                if not 16 <= size <= BLOCK + 16:
                    raise OSError("Invalid staged object.")
                nonce, encrypted = stream.read(12), stream.read(size)
                if len(nonce) != 12 or len(encrypted) != size:
                    raise OSError("Truncated staged object.")
                value = cipher.decrypt(nonce, encrypted, binding + index.to_bytes(8, "big"))
                index += 1
                if not value:
                    if stream.read(1):
                        raise OSError("Invalid staged object suffix.")
                    return
                yield value
    except InvalidTag as exc:
        raise OSError("Staged object authentication failed.") from exc
