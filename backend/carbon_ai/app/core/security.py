from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
import hashlib
import secrets
import os
from app.core.config import settings  # Load local environment before reading JWT secret.

SECRET_KEY = os.environ["JWT_SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

def _hash_password_with_salt(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    ).hex()


def get_password_hash(password: str) -> str:
    salt = secrets.token_hex(32)
    return salt + ":" + _hash_password_with_salt(password, salt)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        salt, hashed = hashed_password.split(":", 1)
        expected_hash = _hash_password_with_salt(plain_password, salt)
        return hashed == expected_hash
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
