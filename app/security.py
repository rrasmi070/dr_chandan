from __future__ import annotations

import hashlib
import hmac
import os


def hash_password(password: str) -> str:
    iterations = 600_000
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{iterations}${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        iteration_text, salt_hex, hash_hex = encoded_hash.split("$", 2)
        iterations = int(iteration_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)
