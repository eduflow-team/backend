"""비밀번호 해시 관련 유틸리티."""

import bcrypt

_ENCODING = "utf-8"


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode(_ENCODING), salt)
    return hashed.decode(_ENCODING)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(_ENCODING), password_hash.encode(_ENCODING))
