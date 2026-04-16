from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

_ENV_KEY = "LLMOPS_ENCRYPTION_KEY"


class CryptoError(RuntimeError):
    pass


def _get_cipher() -> Fernet:
    raw = os.environ.get(_ENV_KEY)
    if not raw:
        raise CryptoError(
            f"{_ENV_KEY} is not set. Generate one with "
            "`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` "
            "and export it before starting the backend."
        )
    try:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except (ValueError, TypeError) as exc:
        raise CryptoError(f"{_ENV_KEY} is not a valid Fernet key: {exc}") from exc


def encrypt(plaintext: str) -> bytes:
    return _get_cipher().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    try:
        return _get_cipher().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoError(
            "Failed to decrypt stored credentials — the encryption key has changed "
            "or the payload is corrupt."
        ) from exc


__all__ = ["encrypt", "decrypt", "CryptoError"]
