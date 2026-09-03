import hashlib
import hmac
import os
import logging

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """
    Genera un hash usando Bcrypt ($2y$) totalmente compatible tanto con PHP como con Python.
    """
    if not password:
        return ""
    try:
        import bcrypt
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(10)).decode("utf-8")
        if hashed.startswith("$2b$"):
            hashed = "$2y$" + hashed[4:]
        return hashed
    except Exception:
        salt = os.urandom(16)
        iterations = 100_000
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(plain_password: str, hashed: str) -> bool:
    """
    Verifica un password plano contra cualquier formato de hash:
    Bcrypt ($2y$, $2b$, $2a$), Argon2 ($argon2id$, $argon2i$), PBKDF2, o texto plano.
    Compatible al 100% entre PHP (password_hash / password_verify) y Python (bcrypt / passlib / argon2).
    """
    if not hashed or not plain_password:
        return False

    hashed_clean = str(hashed).strip()
    plain_clean = str(plain_password)

    # 1. Soporte para Bcrypt de PHP y Python ($2y$, $2b$, $2a$)
    if hashed_clean.startswith(("$2y$", "$2b$", "$2a$")):
        try:
            import bcrypt
            formatted_hash = hashed_clean.replace("$2y$", "$2b$").encode("utf-8")
            if bcrypt.checkpw(plain_clean.encode("utf-8"), formatted_hash):
                return True
        except Exception as e:
            logger.debug(f"Native bcrypt verification failed, trying passlib: {e}")

        try:
            from passlib.hash import bcrypt as passlib_bcrypt
            if passlib_bcrypt.verify(plain_clean, hashed_clean):
                return True
        except Exception as e:
            logger.debug(f"Passlib bcrypt verification failed: {e}")

    # 2. Soporte para Argon2 de PHP ($argon2id$, $argon2i$)
    if hashed_clean.startswith(("$argon2id$", "$argon2i$")):
        try:
            import argon2
            ph = argon2.PasswordHasher()
            ph.verify(hashed_clean, plain_clean)
            return True
        except Exception:
            pass

        try:
            from passlib.hash import argon2 as passlib_argon2
            if passlib_argon2.verify(plain_clean, hashed_clean):
                return True
        except Exception:
            pass

    # 3. Soporte para PBKDF2-HMAC-SHA256
    if hashed_clean.startswith("pbkdf2_sha256$"):
        try:
            parts = hashed_clean.split("$", 3)
            if len(parts) == 4:
                _, it_str, salt_hex, dk_hex = parts
                iterations = int(it_str)
                salt = bytes.fromhex(salt_hex)
                dk_orig = bytes.fromhex(dk_hex)
                dk_new = hashlib.pbkdf2_hmac(
                    "sha256",
                    plain_clean.encode("utf-8"),
                    salt,
                    iterations,
                )
                if hmac.compare_digest(dk_new, dk_orig):
                    return True
        except Exception:
            pass

        try:
            from passlib.hash import pbkdf2_sha256
            if pbkdf2_sha256.verify(plain_clean, hashed_clean):
                return True
        except Exception:
            pass

    # 4. Verificación genérica mediante passlib (soporte universal)
    try:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt", "argon2", "pbkdf2_sha256", "md5_crypt"], deprecated="auto")
        if pwd_context.verify(plain_clean, hashed_clean):
            return True
    except Exception:
        pass

    # 5. Comparación de respaldo para texto plano
    try:
        return hmac.compare_digest(plain_clean.encode("utf-8"), hashed_clean.encode("utf-8"))
    except Exception:
        return False
