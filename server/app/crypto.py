"""Envelope encryption.

    KEK (32 bytes, on disk, never in the database)
      └─ wraps ─> DEK (32 bytes, one per user, stored wrapped in the database)
                    └─ encrypts ─> message content, conversation titles, email

A stolen database dump therefore contains only ciphertext and wrapped keys.
Reading one sentence requires a second, independent compromise: the key file.

AAD (additional authenticated data) binds each ciphertext to the row it belongs
to, so an attacker with write access cannot graft one user's ciphertext onto
another user's conversation.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_LEN = 12  # 96-bit nonce — the GCM standard


@dataclass(frozen=True)
class Sealed:
    """Ciphertext plus its nonce. The 16-byte GCM tag is appended to `ct`."""

    ct: bytes
    nonce: bytes


def seal(key: bytes, plaintext: str, aad: str | None = None) -> Sealed:
    nonce = os.urandom(NONCE_LEN)
    aead = AESGCM(key)
    ct = aead.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8") if aad else None)
    return Sealed(ct=ct, nonce=nonce)


def open_sealed(key: bytes, sealed: Sealed, aad: str | None = None) -> str:
    """Raises cryptography.exceptions.InvalidTag on tamper or wrong AAD. Let it raise."""
    aead = AESGCM(key)
    pt = aead.decrypt(sealed.nonce, sealed.ct, aad.encode("utf-8") if aad else None)
    return pt.decode("utf-8")


# ── Per-user data keys ───────────────────────────────────────────────────

def new_dek() -> bytes:
    return os.urandom(32)


def wrap_dek(kek: bytes, dek: bytes, user_id: str) -> Sealed:
    """Wrap a user's data key with the master key, bound to that user's id."""
    return seal(kek, dek.hex(), aad=f"dek:{user_id}")


def unwrap_dek(kek: bytes, sealed: Sealed, user_id: str) -> bytes:
    return bytes.fromhex(open_sealed(kek, sealed, aad=f"dek:{user_id}"))


# ── Deterministic lookup hashing ─────────────────────────────────────────

def lookup_hash(pepper: bytes, value: str) -> bytes:
    """HMAC for indexed lookup of values we store encrypted (e.g. email).

    HMAC rather than a bare hash: the pepper lives on disk with the KEK, so a
    database dump cannot be brute-forced against a list of known addresses.
    """
    return hmac.new(pepper, value.strip().lower().encode("utf-8"), hashlib.sha256).digest()


def constant_time_eq(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)
