"""JWT + password hashing helpers."""
import os
import secrets
import string
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET", "change-me-in-production-please")
if SECRET_KEY == "change-me-in-production-please":
    import logging as _logging
    _logging.getLogger(__name__).critical(
        "JWT_SECRET is using the default insecure value. "
        "Set a strong random secret in .env before deploying to production."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> str:
    """Returns user_id or raises JWTError."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return payload["sub"]


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def generate_temp_password() -> str:
    """Human-readable 10-char temp password: XXXXX-XXXXX (uppercase + digits)."""
    chars = string.ascii_uppercase + string.digits
    a = ''.join(secrets.choice(chars) for _ in range(5))
    b = ''.join(secrets.choice(chars) for _ in range(5))
    return f"{a}-{b}"
