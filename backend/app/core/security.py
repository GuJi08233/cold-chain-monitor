import re

import bcrypt


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(
        password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("密码长度至少 8 位")

    types = 0
    types += 1 if re.search(r"[A-Z]", password) else 0
    types += 1 if re.search(r"[a-z]", password) else 0
    types += 1 if re.search(r"\d", password) else 0

    if types < 2:
        raise ValueError("密码至少包含大写字母、小写字母、数字中的两种")
