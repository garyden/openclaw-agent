"""Explicit startup configuration. Importing this module does not load .env."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent


class ConfigurationError(ValueError):
    """Contains field names and safe diagnostics only, never configured values."""


def parse_ids(value: str, field: str, *, positive: bool = False) -> frozenset[int]:
    if not value.strip():
        return frozenset()
    parts = value.split(',')
    if any(not re.fullmatch(r'-?[0-9]+', part.strip()) for part in parts):
        raise ConfigurationError(f'{field} must contain comma-separated numeric IDs')
    ids = frozenset(int(part.strip()) for part in parts)
    if 0 in ids or (positive and any(number < 0 for number in ids)):
        raise ConfigurationError(f'{field} contains an invalid ID')
    return ids


@dataclass(frozen=True)
class Settings:
    # repr=False prevents accidental token disclosure in logs or exceptions.
    token: str = field(repr=False)
    owner_ids: frozenset[int]
    chat_ids: frozenset[int]


def read_settings(environ=None) -> Settings:
    env = os.environ if environ is None else environ
    token = env.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise ConfigurationError('TELEGRAM_BOT_TOKEN is required')
    owners = parse_ids(env.get('TELEGRAM_OWNER_IDS', ''), 'TELEGRAM_OWNER_IDS', positive=True)
    chats = parse_ids(env.get('TELEGRAM_ALLOWED_CHAT_IDS', ''), 'TELEGRAM_ALLOWED_CHAT_IDS')
    if not owners or not chats:
        raise ConfigurationError('TELEGRAM_OWNER_IDS and TELEGRAM_ALLOWED_CHAT_IDS are required')

    smtp_fields = ('EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_USER', 'EMAIL_PASSWORD')
    if any(env.get(key, '').strip() for key in smtp_fields):
        if not all(env.get(key, '').strip() for key in smtp_fields):
            raise ConfigurationError('SMTP requires EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD')
        try:
            port = int(env['EMAIL_PORT'])
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise ConfigurationError('EMAIL_PORT must be an integer from 1 to 65535') from None

    enabled = env.get('DAILY_BRIEF_ENABLED', '').strip().lower()
    if enabled not in ('', '0', 'false', 'no', 'off', '1', 'true', 'yes', 'on'):
        raise ConfigurationError('DAILY_BRIEF_ENABLED must be a boolean')
    if enabled in ('1', 'true', 'yes', 'on'):
        target = parse_ids(env.get('DAILY_BRIEF_CHAT_ID', ''), 'DAILY_BRIEF_CHAT_ID')
        if len(target) != 1 or not target.issubset(chats):
            raise ConfigurationError('DAILY_BRIEF_CHAT_ID must be one allowed chat ID')
        try:
            clock = env.get('DAILY_BRIEF_TIME', '08:00')
            if not re.fullmatch(r'[0-9]{2}:[0-9]{2}', clock):
                raise ValueError
            datetime.strptime(clock, '%H:%M')
        except ValueError:
            raise ConfigurationError('DAILY_BRIEF_TIME must use valid HH:MM') from None
        try:
            ZoneInfo(env.get('DAILY_BRIEF_TIMEZONE', 'America/New_York'))
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigurationError('DAILY_BRIEF_TIMEZONE must be a valid timezone') from None
    return Settings(token, owners, chats)


def load_settings(env_path: Path | str | None = None) -> Settings:
    from dotenv import load_dotenv
    # Existing shell variables win; no interpolation of secret values.
    load_dotenv(BASE_DIR / '.env' if env_path is None else env_path,
                override=False, interpolate=False)
    return read_settings()
