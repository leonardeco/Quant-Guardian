"""Password hashing (stdlib scrypt, no bcrypt/passlib version issues) and JWT auth."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .config import settings
from .db import get_db

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT).hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest = stored.split("$")
    except ValueError:
        return False
    calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT).hex()
    return hmac.compare_digest(calc, digest)


def create_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": user_id, "exp": exp}, settings.jwt_secret, algorithm="HS256")


async def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
                           db: AsyncSession = Depends(get_db)) -> models.User:
    if not cred:
        raise HTTPException(401, "missing token")
    try:
        user_id = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token")
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(401, "invalid token")
    return user
