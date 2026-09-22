import secrets
import string
import uuid

_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase  # 62 chars
_BASE = len(_ALPHABET)


def base62_encode(num: int) -> str:
    if num == 0:
        return _ALPHABET[0]
    chars = []
    while num > 0:
        num, rem = divmod(num, _BASE)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def base62_decode(s: str) -> int:
    num = 0
    for char in s:
        num = num * _BASE + _ALPHABET.index(char)
    return num


def random_fallback_code(length: int = 8) -> str:
    """Used only if Redis-backed ID generation is unavailable."""
    raw = uuid.uuid4().int
    return base62_encode(raw)[:length] or secrets.token_urlsafe(length)[:length]


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)
