from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from client_manager import CLIENT_FIELDS, DEFAULT_CLIENT, VALID_STATUSES

MAX_IMPORT_ROWS = 500
REQUIRED_HEADERS = tuple(CLIENT_FIELDS)
DATE_FIELDS = {"birthday", "last_contact", "next_followup"}
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%B %d %Y",
    "%b %d, %Y",
    "%b %d %Y",
)


def parse_client_workbook(path: str | Path) -> list[dict]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("Excel import requires openpyxl.") from exc

    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        if "Clients" not in workbook.sheetnames:
            raise ValueError("Workbook must contain a sheet named 'Clients'.")

        sheet = workbook["Clients"]
        rows = sheet.iter_rows(values_only=True)
        headers = next(rows, None)
        normalized_headers = tuple(_clean(value).casefold() for value in (headers or ()))
        if normalized_headers[: len(REQUIRED_HEADERS)] != REQUIRED_HEADERS:
            raise ValueError(
                "Clients sheet headers do not match the official import template."
            )

        parsed = []
        for row_number, values in enumerate(rows, start=2):
            if not any(_clean(value) for value in values):
                continue
            if len(parsed) >= MAX_IMPORT_ROWS:
                raise ValueError(f"Import is limited to {MAX_IMPORT_ROWS} client rows.")

            raw = dict(zip(REQUIRED_HEADERS, values[: len(REQUIRED_HEADERS)]))
            parsed.append(
                {
                    "row_number": row_number,
                    "client": _normalize_client_row(raw),
                    "row_errors": _validate_client_row(raw),
                }
            )
        return parsed
    finally:
        workbook.close()


def build_import_preview(rows: list[dict], existing_clients: list[dict]) -> dict:
    existing_names = {_key(client.get("name")) for client in existing_clients}
    existing_emails = {_key(client.get("email")) for client in existing_clients if _clean(client.get("email"))}
    existing_phones = {_phone_key(client.get("phone")) for client in existing_clients if _clean(client.get("phone"))}
    seen_names: set[str] = set()
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()
    ready = []
    duplicates = []
    errors = []

    for row in rows:
        client = row["client"]
        row_number = row["row_number"]
        if row["row_errors"]:
            errors.append({"row_number": row_number, "errors": row["row_errors"]})
            continue

        duplicate_reasons = []
        name_key = _key(client["name"])
        email_key = _key(client["email"]) if client["email"] else ""
        phone_key = _phone_key(client["phone"]) if client["phone"] else ""

        if name_key in existing_names or name_key in seen_names:
            duplicate_reasons.append("duplicate name")
        if email_key and (email_key in existing_emails or email_key in seen_emails):
            duplicate_reasons.append("duplicate email")
        if phone_key and (phone_key in existing_phones or phone_key in seen_phones):
            duplicate_reasons.append("duplicate phone")

        if duplicate_reasons:
            duplicates.append(
                {
                    "row_number": row_number,
                    "client_name": client["name"],
                    "reasons": duplicate_reasons,
                }
            )
            continue

        ready.append(client)
        seen_names.add(name_key)
        if email_key:
            seen_emails.add(email_key)
        if phone_key:
            seen_phones.add(phone_key)

    return {
        "total_rows": len(rows),
        "ready": ready,
        "duplicates": duplicates,
        "errors": errors,
    }


def format_import_preview(preview: dict) -> str:
    lines = [
        "Client import preview",
        "",
        f"Total rows: {preview['total_rows']}",
        f"Ready to import: {len(preview['ready'])}",
        f"Duplicates skipped: {len(preview['duplicates'])}",
        f"Invalid rows: {len(preview['errors'])}",
    ]
    if preview["duplicates"]:
        lines.extend(["", "Duplicates"])
        for item in preview["duplicates"][:10]:
            lines.append(
                f"- Row {item['row_number']}: {item['client_name']} "
                f"({', '.join(item['reasons'])})"
            )
    if preview["errors"]:
        lines.extend(["", "Invalid rows"])
        for item in preview["errors"][:10]:
            lines.append(f"- Row {item['row_number']}: {'; '.join(item['errors'])}")
    if len(preview["duplicates"]) > 10 or len(preview["errors"]) > 10:
        lines.extend(["", "Only the first 10 duplicate/error rows are shown."])

    lines.extend(["", "No clients have been imported yet."])
    if preview["ready"]:
        lines.append("Use /confirm_import_clients to import the ready rows.")
    lines.append("Use /cancel_import_clients to cancel.")
    return "\n".join(lines)


def _normalize_client_row(raw: dict[str, Any]) -> dict:
    client = DEFAULT_CLIENT.copy()
    for field in REQUIRED_HEADERS:
        value = raw.get(field)
        if field in DATE_FIELDS:
            client[field] = _normalize_date(value)
        else:
            client[field] = _clean(value)
    client["status"] = client["status"].casefold() or "new_lead"
    return client


def _validate_client_row(raw: dict[str, Any]) -> list[str]:
    errors = []
    if not _clean(raw.get("name")):
        errors.append("missing client name")

    status = _clean(raw.get("status")).casefold() or "new_lead"
    if status not in VALID_STATUSES:
        errors.append(f"invalid status '{status}'")

    for field in DATE_FIELDS:
        value = raw.get(field)
        if _clean(value) and not _normalize_date(value):
            errors.append(f"invalid {field} date")
    return errors


def _normalize_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = _clean(value)
    if not text:
        return ""
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            continue
    return ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _key(value: Any) -> str:
    return " ".join(_clean(value).casefold().split())


def _phone_key(value: Any) -> str:
    return "".join(character for character in _clean(value) if character.isdigit())
