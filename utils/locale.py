"""Validated locale identifiers shared by configuration and presentation layers."""

from __future__ import annotations

DEFAULT_LOCALE = "zh_CN"
SUPPORTED_LOCALES = ("zh_CN", "en_US")


def normalize_locale(value: object) -> str:
    """Return a supported persisted locale without accepting arbitrary values."""
    return value if isinstance(value, str) and value in SUPPORTED_LOCALES else DEFAULT_LOCALE
