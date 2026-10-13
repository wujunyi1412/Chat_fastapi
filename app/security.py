from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings


_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
SESSION_MAX_AGE = 60 * 60 * 24 * 14


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("密码至少需要 8 个字符")
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="chat-session-v1")


def create_session(user_id: int, room_id: int) -> str:
    return _serializer().dumps({"user_id": user_id, "room_id": room_id})


def read_session(token: str | None) -> dict[str, int] | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
        return {"user_id": int(data["user_id"]), "room_id": int(data["room_id"])}
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None

