"""Explicit startup configuration. Importing this module does not load .env."""
from __future__ import annotations

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DEV_MEMORY_PATH = BASE_DIR / 'memory' / 'development.xml'


class ConfigurationError(ValueError):
    """Contains field names and safe diagnostics only, never configured values."""


def read_app_env(environ=None) -> str:
    env = os.environ if environ is None else environ
    value = env.get('APP_ENV', 'development')
    if value not in ('development', 'testing', 'production'):
        raise ConfigurationError('APP_ENV must be development, testing, or production')
    return value


@lru_cache(maxsize=1)
def _test_memory_directory():
    return tempfile.TemporaryDirectory(prefix='openclaw-crm-')


def _inside_git_checkout(path: Path) -> bool:
    return any(os.path.lexists(parent / '.git') for parent in path.parents)


def validate_production_memory(path: Path) -> None:
    if not path.is_absolute():
        raise ConfigurationError('Production CRM_MEMORY_PATH must be absolute')
    if '\x00' in str(path):
        raise ConfigurationError('Production CRM_MEMORY_PATH is invalid')
    try:
        resolved = path.resolve(strict=True)
        if (_inside_git_checkout(path) or _inside_git_checkout(resolved)
                or resolved.is_relative_to(BASE_DIR)):
            raise ConfigurationError('Production CRM_MEMORY_PATH must be outside Git checkouts')
        if (not resolved.is_file() or resolved.stat().st_nlink != 1
                or not os.access(resolved, os.R_OK | os.W_OK)
                or not os.access(resolved.parent, os.W_OK | os.X_OK)):
            raise ConfigurationError('Production CRM_MEMORY_PATH must be a readable and writable regular file in a writable directory')
        with resolved.open('r+b') as source:
            if ET.parse(source).getroot().tag != 'memory':
                raise ConfigurationError('Production CRM_MEMORY_PATH must have a <memory> XML root')
    except (OSError, RuntimeError, ET.ParseError, UnicodeError, LookupError):
        raise ConfigurationError('Production CRM_MEMORY_PATH must point to existing accessible CRM XML') from None


def resolve_memory_path(environ=None, *, explicit_path=None) -> Path:
    env = os.environ if environ is None else environ
    app_env = read_app_env(env)
    configured = env.get('CRM_MEMORY_PATH', '').strip()
    if app_env == 'production':
        if not configured:
            raise ConfigurationError('CRM_MEMORY_PATH is required in production')
        path = Path(configured)
        validate_production_memory(path)
        resolved = path.resolve()
        if explicit_path is not None and Path(explicit_path).resolve() != resolved:
            raise ConfigurationError('Production CRM must use CRM_MEMORY_PATH')
        return resolved

    raw_path = explicit_path if explicit_path is not None else configured
    if not raw_path:
        if app_env == 'testing':
            return Path(_test_memory_directory().name).resolve() / 'memory.xml'
        if DEV_MEMORY_PATH.resolve() != DEV_MEMORY_PATH:
            raise ConfigurationError('Default development CRM path must not use symlinks')
        if DEV_MEMORY_PATH.is_file() and DEV_MEMORY_PATH.stat().st_nlink != 1:
            raise ConfigurationError('Default development CRM file must not use hard links')
        return DEV_MEMORY_PATH

    path = Path(raw_path).expanduser()
    if explicit_path is None:
        path = BASE_DIR / path
    resolved = path.resolve()
    if app_env == 'testing' and (
        not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())
        or _inside_git_checkout(resolved) or resolved.is_relative_to(BASE_DIR)
    ):
        raise ConfigurationError('Testing CRM_MEMORY_PATH must be in a temporary directory outside Git checkouts')
    return resolved


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
    app_env: str
    crm_memory_path: Path = field(repr=False)


def read_settings(environ=None) -> Settings:
    env = os.environ if environ is None else environ
    app_env = read_app_env(env)
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
    return Settings(token, owners, chats, app_env, resolve_memory_path(env))


def load_settings(env_path: Path | str | None = None) -> Settings:
    app_env = read_app_env()
    if app_env == 'development' or (app_env == 'testing' and env_path is not None):
        from dotenv import dotenv_values

        path = BASE_DIR / '.env.development' if env_path is None else env_path
        values = dotenv_values(path, interpolate=False)
        # Select the environment before loading credentials from a file.
        if 'APP_ENV' in values and values['APP_ENV'] != app_env:
            raise ConfigurationError('Select APP_ENV in the process environment before loading settings')
        for key, value in values.items():
            if value is not None:
                os.environ.setdefault(key, value)
    return read_settings()
