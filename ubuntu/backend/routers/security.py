import hashlib
import hmac
import os


def hash_password(password: str) -> str:
    """
    Genera un hash usando PBKDF2-HMAC-SHA256.

    Retorna un string con formato:
        pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    """
    salt = os.urandom(16)
    iterations = 100_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(plain_password: str, hashed: str) -> bool:
    """
    Verifica un password plano contra un hash generado con hash_password.
    """
    try:
        algo, it_str, salt_hex, dk_hex = hashed.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(it_str)
        salt = bytes.fromhex(salt_hex)
        dk_orig = bytes.fromhex(dk_hex)
    except Exception:
        return False

    dk_new = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(dk_new, dk_orig)

