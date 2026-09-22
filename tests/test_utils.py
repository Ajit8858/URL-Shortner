from app.utils import base62_decode, base62_encode


def test_base62_roundtrip():
    for n in [0, 1, 61, 62, 12345, 999_999_999, 10**12]:
        encoded = base62_encode(n)
        assert base62_decode(encoded) == n


def test_base62_is_url_safe():
    encoded = base62_encode(123456789)
    assert encoded.isalnum()


def test_base62_monotonic_length_growth():
    # Sanity check: larger numbers never produce shorter codes.
    prev_len = 0
    for exp in range(0, 15):
        n = 62**exp
        length = len(base62_encode(n))
        assert length >= prev_len
        prev_len = length
