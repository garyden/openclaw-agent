from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_AGENT_PROFILE_PATH = Path(__file__).resolve().parent / "config" / "agent_profile.json"

DEFAULT_AGENT_PROFILE = {
    "agent_name": "",
    "company_name": "",
    "preferred_language": "English",
    "email_signature": "Best,\nYour real estate agent",
    "writing_tone": ["warm", "professional", "natural"],
    "preferred_email_length": "short",
    "greeting_style": "Use a simple greeting such as Hi {client_first_name},",
    "closing_style": "Use a warm, simple closing.",
    "communication_principles": [
        "Be helpful and sincere.",
        "Do not invent client facts.",
    ],
    "avoid": [
        "pushy sales language",
        "claims or details not supported by client data",
    ],
}

_STRING_FIELDS = {
    "agent_name",
    "company_name",
    "preferred_language",
    "email_signature",
    "preferred_email_length",
    "greeting_style",
    "closing_style",
}
_LIST_FIELDS = {"writing_tone", "communication_principles", "avoid"}


def load_agent_profile(path: str | Path | None = None) -> dict:
    """Load Agent DNA from a predictable path and always return a safe profile."""
    profile_path = Path(path) if path is not None else DEFAULT_AGENT_PROFILE_PATH

    try:
        with profile_path.open("r", encoding="utf-8") as profile_file:
            configured = json.load(profile_file)
    except (OSError, UnicodeError, json.JSONDecodeError):
        configured = {}

    return normalize_agent_profile(configured)


def normalize_agent_profile(profile: Any) -> dict:
    """Merge valid configured values onto defaults without retaining unknown keys."""
    normalized = deepcopy(DEFAULT_AGENT_PROFILE)
    if not isinstance(profile, dict):
        return normalized

    for field in _STRING_FIELDS:
        value = profile.get(field)
        if isinstance(value, str):
            normalized[field] = value.strip()

    for field in _LIST_FIELDS:
        value = profile.get(field)
        if isinstance(value, list):
            cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
            normalized[field] = cleaned

    return normalized
