from __future__ import annotations

from datetime import date, datetime, timedelta
import os
from zoneinfo import ZoneInfo
from typing import Any


_FOLLOWUP_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%B %d, %Y",
    "%B %d %Y",
    "%b %d, %Y",
    "%b %d %Y",
)
_BIRTHDAY_FORMATS = (
    "%B %d",
    "%b %d",
    "%B %d, %Y",
    "%B %d %Y",
    "%b %d, %Y",
    "%b %d %Y",
    "%Y-%m-%d",
    "%m-%d",
    "%m/%d",
)


def application_today(now: datetime | None = None, timezone_name: str | None = None) -> date:
    """Use the Daily Brief timezone for both manual and conversational queries."""
    zone = ZoneInfo(timezone_name or os.getenv("DAILY_BRIEF_TIMEZONE", "America/New_York").strip())
    current = now if now is not None else datetime.now(zone)
    if current.tzinfo is None:
        raise ValueError("Application clock must be timezone-aware")
    return current.astimezone(zone).date()


def build_daily_brief(
    clients: list[dict],
    pending_drafts: list[dict] | None = None,
    today: date | None = None,
) -> dict:
    """Classify existing CRM work without changing clients or draft state."""
    current_date = today if isinstance(today, date) else application_today()
    birthdays_today = []
    followups_due_today = []
    overdue_followups = []

    for client in clients if isinstance(clients, list) else []:
        if not isinstance(client, dict):
            continue

        client_name = _clean(client.get("name"))
        if not client_name:
            continue

        birthday = _parse_birthday_month_day(client.get("birthday"))
        if birthday == (current_date.month, current_date.day):
            birthdays_today.append({"client_name": client_name})

        followup_date = _parse_followup_date(client.get("next_followup"))
        if followup_date == current_date:
            followups_due_today.append(
                {"client_name": client_name, "followup_date": followup_date}
            )
        elif followup_date is not None and followup_date < current_date:
            overdue_followups.append(
                {
                    "client_name": client_name,
                    "followup_date": followup_date,
                    "days_overdue": (current_date - followup_date).days,
                }
            )

    safe_drafts = _normalize_pending_drafts(pending_drafts)
    birthdays_today.sort(key=lambda item: item["client_name"].casefold())
    followups_due_today.sort(key=lambda item: item["client_name"].casefold())
    overdue_followups.sort(
        key=lambda item: (item["followup_date"], item["client_name"].casefold())
    )
    safe_drafts.sort(
        key=lambda item: (
            not bool(item["client_name"]),
            item["client_name"].casefold(),
            item["purpose"].casefold(),
        )
    )

    result = {
        "birthdays_today": birthdays_today,
        "followups_due_today": followups_due_today,
        "overdue_followups": overdue_followups,
        "pending_drafts": safe_drafts,
        "suggested_action": None,
    }
    result["suggested_action"] = _suggested_action(result)
    return result


def build_followup_query(clients: list[dict], scope: str, today: date | None = None) -> dict:
    """Reuse Daily Brief classification without changing records or scheduling work."""
    if scope not in {"today", "tomorrow", "overdue"}:
        raise ValueError("Unsupported follow-up query")
    local_today = today if today is not None else application_today()
    target = local_today + timedelta(days=1) if scope == "tomorrow" else local_today
    category = "overdue_followups" if scope == "overdue" else "followups_due_today"
    items = []
    # Classify individual records to retain their own status, even for duplicate names.
    for client in clients if isinstance(clients, list) else []:
        brief = build_daily_brief([client], today=target)
        for item in brief[category]:
            items.append({**item, "status": _clean(client.get("status")) or "unknown"})
    items.sort(key=lambda item: (item["followup_date"], item["client_name"].casefold()))
    return {"scope": scope, "date": target, "items": items}


def _parse_followup_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = _clean(value)
    for date_format in _FOLLOWUP_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def _parse_birthday_month_day(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (date, datetime)):
        return value.month, value.day

    text = _clean(value)
    for date_format in _BIRTHDAY_FORMATS:
        try:
            if "%Y" in date_format:
                parsed = datetime.strptime(text, date_format)
            else:
                parsed = datetime.strptime(f"{text} 2000", f"{date_format} %Y")
            return parsed.month, parsed.day
        except ValueError:
            continue
    return None


def _normalize_pending_drafts(pending_drafts: Any) -> list[dict]:
    normalized = []
    for draft in pending_drafts if isinstance(pending_drafts, list) else []:
        if not isinstance(draft, dict):
            continue
        normalized.append(
            {
                "client_name": _clean(draft.get("client_name")),
                "purpose": _clean(draft.get("purpose")) or "email",
                "subject": _clean(draft.get("subject")),
            }
        )
    return normalized


def _suggested_action(brief: dict) -> dict | None:
    categories = (
        ("overdue_followup", "overdue_followups"),
        ("followup_due_today", "followups_due_today"),
        ("birthday", "birthdays_today"),
        ("pending_draft", "pending_drafts"),
    )
    for kind, field in categories:
        items = brief[field]
        if items:
            return {"kind": kind, **items[0]}
    return None


def _clean(value: Any) -> str:
    return str(value or "").strip()
