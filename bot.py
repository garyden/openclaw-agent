from __future__ import annotations

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

import os
import re
import json
import tempfile
from crm_logging import (
    configure_logging, log_event, log_telegram_error, log_draft_diagnostic,
    log_lifecycle_failure,
)
from voice_draft_diagnostics import VoiceDraftDiagnostics, analyze_synthetic_transcript
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from openai import OpenAI

from app_config import load_settings, read_app_env, ConfigurationError
from authorization import owner_only, allowed_chat
from natural_crm import NaturalCRM, parse_request as parse_crm_request
from ai_parser import parse_user_intent
from utils import debug, parse_city_state
from town_analyzer import analyze_town, format_town_report
from report_builder import build_property_town_report
from pipeline import run_town_pipeline
from client_manager import ClientManager
from client_reference import resolve_client_reference
from client_importer import (
    build_import_preview,
    format_import_preview,
    parse_client_workbook,
)
from agent_profile import load_agent_profile
from daily_brief import build_daily_brief, application_today
from tour import format_tour_menu, format_tour_topic
from email_generator import generate_birthday_email
from email_sender import send_email

from memory_manager import (
    load_memory,
    append_fact,
    append_preference,
    append_property,
    delete_property,
    clear_all_properties,
    summarize_properties,
)

from property_analyzer import (
    auto_extract_house_info,
    normalize_to_analysis_text,
    analyze_house,
)

from scoring import (
    final_investment_decision,
    find_best_properties,
    find_deals_by_filters,
    compare_properties,
)

DEBUG = False
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
crm = None  # Initialized explicitly after validated startup.
agent_profile = load_agent_profile()
openai_client = None


def get_openai_client():
    global openai_client
    if openai_client is None and os.getenv("OPENAI_API_KEY"):
        openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return openai_client


def initialize_runtime():
    global TOKEN, crm
    settings = load_settings()
    crm = ClientManager(settings.crm_memory_path)
    TOKEN = settings.token
    return settings

pending_email_drafts = {}
pending_client_imports = {}
pending_client_actions = {}
pending_tours = set()
natural_crm = NaturalCRM(profile=agent_profile)
voice_draft_diagnostics = VoiceDraftDiagnostics()
_daily_brief_last_sent = {}
CLIENT_IMPORT_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets",
    "client_import_template.xlsx",
)
DEFAULT_DAILY_BRIEF_TIME = "08:00"
DEFAULT_DAILY_BRIEF_TIMEZONE = "America/New_York"
VOICE_CLIENT_UPDATE_FIELDS = {
    "status",
    "notes",
    "next_followup",
    "last_contact",
    "phone",
    "email",
    "budget",
    "areas",
    "requirements",
}
VOICE_ROUTER_INTENTS = {
    "list_clients",
    "get_client",
    "update_client",
    "delete_client",
    "generate_birthday_email",
    "unknown",
}


def store_pending_email_draft(user_id: int, client: dict, draft: dict) -> None:
    pending_email_drafts[user_id] = {
        "client_name": client.get("name", ""),
        "draft": draft,
    }


def get_pending_email_draft(record: dict | None) -> dict | None:
    if not isinstance(record, dict):
        return None

    draft = record.get("draft")
    if isinstance(draft, dict):
        return draft

    if "subject" in record or "body" in record:
        return record

    return None


def get_pending_email_client_name(record: dict | None) -> str:
    if not isinstance(record, dict):
        return ""

    return str(record.get("client_name") or "").strip()


def handle_analyze_town(user_text: str) -> str:
    parsed = parse_user_intent(user_text)

    city = parsed.get("city")
    state = parsed.get("state")

    if not city:
        return "请告诉我你要分析哪个 town，比如：Princeton NJ"

    if not state:
        state = "NJ"

    result = run_town_pipeline(city, state)

    if not result.get("success"):
        return result.get("message", f"{city}, {state} 的 town 分析失败")

    return result.get("report", f"{city}, {state} 分析完成，但没有生成报告")


def run_property_pipeline(info: dict, analysis_text: str, analysis_data: dict) -> tuple[str, bool]:
    city, state = parse_city_state(info.get("location", ""))

    town_result = analyze_town(city, state)
    final_result = final_investment_decision(analysis_data, town_result)

    saved = append_property(
        info["address"],
        info["price"],
        info["size"],
        info["rent"],
        info["location"],
        analysis_data["ratio_percent"],
        analysis_data["yield_percent"],
        analysis_data["health"],
        analysis_data["advice"],
        info["hoa"],
        info["tax"],
        info["insurance"],
        info["maintenance"],
        info["vacancy"],
        analysis_data["loan_amount"],
        analysis_data["monthly_mortgage"],
        analysis_data["cashflow_after_debt"],
        final_result["property_score"],
        final_result["town_score"],
        final_result["final_score"],
        final_result["grade"],
        final_result["decision"],
    )

    final_text = build_property_town_report(
        info,
        analysis_text,
        town_result,
        final_result
    )

    return final_text, saved


def parse_delete_address(user_text: str) -> str:
    parts = re.split(r"[:：]", user_text, maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi, I am your real estate copilot.\n\n"
        "I can help you manage clients, update follow-ups by voice, draft birthday emails, "
        "revise drafts, and send reviewed emails.\n\n"
        "Type /tour for a guided introduction or /help to see examples."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Here are the main things you can do:\n"
        "Use /tour for a short guided introduction.\n\n"
        "Add client:\n"
        "/add_client name=Mary Lee | phone=732-555-0100 | email=mary@example.com\n\n"
        "List clients:\n"
        "/list_clients\n"
        "Voice: list clients\n\n"
        "Import clients from Excel:\n"
        "/client_import_template\n"
        "/import_clients\n\n"
        "Daily brief:\n"
        "/daily_brief\n\n"
        "Get client:\n"
        "/get_client Mary Lee\n"
        "Voice: get client Mary Lee\n\n"
        "Update client:\n"
        "Voice: update client Mary Lee, status touring, next follow up 2026 July 10\n\n"
        "Remove client safely:\n"
        "/delete_client Mary Lee\n"
        "Voice: remove Mary Lee\n"
        "Then confirm or cancel the deletion preview.\n\n"
        "Generate birthday email:\n"
        "/generate_birthday_email Mary Lee\n"
        "Voice: generate birthday email for Mary Lee\n\n"
        "Revise email draft:\n"
        "Voice after a draft: make it warmer\n"
        "Voice after a draft: add a more personal closing\n\n"
        "Send reviewed draft:\n"
        "/send_last_email to review before sending\n"
        "/confirm_send_email to send\n"
        "/cancel_email to cancel"
    )


async def tour_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    if user_id is None:
        await update.message.reply_text("Could not identify the current Telegram user.")
        return

    pending_tours.add(user_id)
    profile_name = str(agent_profile.get("agent_name") or "").strip()
    await update.message.reply_text(format_tour_menu(profile_name))


async def cancel_tour_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    if user_id is None or user_id not in pending_tours:
        await update.message.reply_text("No guided tour is currently active.")
        return

    pending_tours.remove(user_id)
    await update.message.reply_text(
        "Tour finished. You can use /tour anytime, or /help for command examples."
    )


async def handle_tour_reply(update: Update, user_text: str) -> bool:
    user_id = update.effective_user.id if update.effective_user is not None else None
    if user_id is None or user_id not in pending_tours:
        return False

    # Read-only follow-up queries/drafts may interrupt guidance; numeric tour replies still work.
    request = parse_crm_request(user_text)
    if (request is not None and request['intent'] in {'followup_query', 'followup_email'}
            or user_text.strip() not in {'1', '2', '3', '4', '5'} and natural_crm.has_pending_draft(update)):
        return False

    topic = format_tour_topic(user_text)
    if topic is None:
        await update.message.reply_text(
            "Please reply with a number from 1 to 5, or use /cancel_tour."
        )
        return True

    await update.message.reply_text(topic)
    return True


async def add_client_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await update.message.reply_text(
            "Usage:\n/add_client name=John Smith | phone=123 | email=john@example.com"
        )
        return

    try:
        client = crm.add_client_from_text(parts[1])
        await update.message.reply_text(f"Client added: {client['name']}")
    except Exception as exc:
        log_event("request_failed")
        await update.message.reply_text(f"Could not add client: {exc}")


async def list_clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clients = crm.list_clients()
    await update.message.reply_text(format_clients_list(clients))


async def client_import_template_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(CLIENT_IMPORT_TEMPLATE_PATH):
        await update.message.reply_text("Client import template is unavailable.")
        return

    with open(CLIENT_IMPORT_TEMPLATE_PATH, "rb") as template_file:
        await update.message.reply_document(
            document=template_file,
            filename="client_import_template.xlsx",
            caption="Fill the Clients sheet, then use /import_clients and upload this file.",
        )


async def import_clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    if user_id is None:
        await update.message.reply_text("Could not identify the current Telegram user.")
        return

    pending_client_imports[user_id] = {"status": "awaiting_upload"}
    await update.message.reply_text(
        "Please upload the completed client_import_template.xlsx file.\n"
        "No clients will be imported until you use /confirm_import_clients."
    )


async def handle_client_import_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    document = update.message.document if update.message is not None else None
    if user_id is None or document is None:
        return
    if pending_client_imports.get(user_id, {}).get("status") != "awaiting_upload":
        await update.message.reply_text("Use /import_clients before uploading an Excel file.")
        return

    file_name = str(getattr(document, "file_name", "") or "")
    if not file_name.casefold().endswith(".xlsx"):
        await update.message.reply_text("Please upload an .xlsx file.")
        return

    temp_path = ""
    try:
        telegram_file = await context.bot.get_file(document.file_id)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp_file:
            temp_path = temp_file.name
        await telegram_file.download_to_drive(temp_path)

        rows = parse_client_workbook(temp_path)
        preview = build_import_preview(rows, crm.list_clients())
        pending_client_imports[user_id] = {
            "status": "ready_for_confirmation",
            "preview": preview,
        }
        await update.message.reply_text(format_import_preview(preview))
    except Exception as exc:
        pending_client_imports[user_id] = {"status": "awaiting_upload"}
        await update.message.reply_text(f"Could not read client workbook: {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


async def confirm_import_clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    record = pending_client_imports.get(user_id) if user_id is not None else None
    if not record or record.get("status") != "ready_for_confirmation":
        await update.message.reply_text("There is no client import waiting for confirmation.")
        return

    ready = record["preview"]["ready"]
    if not ready:
        await update.message.reply_text(
            "There are no valid new clients to import. Use /cancel_import_clients."
        )
        return

    try:
        imported = crm.add_clients_batch(ready)
    except Exception as exc:
        log_event("request_failed")
        await update.message.reply_text(
            f"Client import was not applied: {exc}\n"
            "No partial batch was written. Upload a new workbook to try again."
        )
        return

    del pending_client_imports[user_id]
    await update.message.reply_text(
        f"Client import complete: {len(imported)} clients added."
    )


async def cancel_import_clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    if user_id is None or user_id not in pending_client_imports:
        await update.message.reply_text("There is no pending client import.")
        return

    del pending_client_imports[user_id]
    await update.message.reply_text("Client import canceled. No clients were added.")


async def daily_brief_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    await update.message.reply_text(build_daily_brief_message(user_id))


def build_daily_brief_message(user_id: int | None, today: date | None = None) -> str:
    clients = crm.list_clients()
    pending_drafts = get_pending_draft_summaries(user_id)
    if today is None:
        brief = build_daily_brief(clients, pending_drafts)
    else:
        brief = build_daily_brief(clients, pending_drafts, today=today)
    return format_daily_brief(brief, agent_profile.get("agent_name", ""))


def load_daily_brief_schedule() -> dict | None:
    enabled = str(os.getenv("DAILY_BRIEF_ENABLED", "")).strip().casefold()
    if enabled not in {"1", "true", "yes", "on"}:
        return None

    raw_chat_id = str(os.getenv("DAILY_BRIEF_CHAT_ID", "")).strip()
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        debug("DAILY_BRIEF_CHAT_ID is missing or invalid; automatic Daily Brief disabled")
        return None

    raw_time = str(
        os.getenv("DAILY_BRIEF_TIME", DEFAULT_DAILY_BRIEF_TIME)
    ).strip()
    try:
        send_time = datetime.strptime(raw_time, "%H:%M").time()
    except ValueError:
        debug("DAILY_BRIEF_TIME must use HH:MM; automatic Daily Brief disabled")
        return None

    timezone_name = str(
        os.getenv("DAILY_BRIEF_TIMEZONE", DEFAULT_DAILY_BRIEF_TIMEZONE)
    ).strip()
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        debug("DAILY_BRIEF_TIMEZONE is invalid; automatic Daily Brief disabled")
        return None

    return {
        "chat_id": chat_id,
        "timezone_name": timezone_name,
        "send_time": time(
            send_time.hour,
            send_time.minute,
            tzinfo=timezone,
        ),
    }


async def automatic_daily_brief_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data if context.job is not None else {}
    chat_id = data.get("chat_id")
    timezone_name = data.get("timezone_name", DEFAULT_DAILY_BRIEF_TIMEZONE)
    if not isinstance(chat_id, int):
        debug("Automatic Daily Brief skipped because chat ID is invalid")
        return

    try:
        today = application_today(timezone_name=timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        debug("Automatic Daily Brief skipped because timezone is invalid")
        return

    if not allowed_chat(chat_id):
        return

    if _daily_brief_last_sent.get(chat_id) == today:
        debug("Automatic Daily Brief already sent today; skipping duplicate")
        return

    text = build_daily_brief_message(chat_id, today=today)
    await context.bot.send_message(chat_id=chat_id, text=text)
    _daily_brief_last_sent[chat_id] = today


def register_automatic_daily_brief(app) -> bool:
    schedule = load_daily_brief_schedule()
    if schedule is None or not allowed_chat(schedule["chat_id"]):
        return False

    job_queue = getattr(app, "job_queue", None)
    if job_queue is None:
        debug(
            "Telegram JobQueue is unavailable; install python-telegram-bot[job-queue] "
            "to enable automatic Daily Brief"
        )
        return False

    job_queue.run_daily(
        automatic_daily_brief_job,
        time=schedule["send_time"],
        data={
            "chat_id": schedule["chat_id"],
            "timezone_name": schedule["timezone_name"],
        },
        name=f"daily_brief_{schedule['chat_id']}",
    )
    return True


def get_pending_draft_summaries(user_id: int | None) -> list[dict]:
    if user_id is None:
        return []

    record = pending_email_drafts.get(user_id)
    draft = get_pending_email_draft(record)
    if draft is None:
        return []

    return [
        {
            "purpose": "birthday",
            "client_name": get_pending_email_client_name(record),
            "subject": str(draft.get("subject") or "").strip(),
        }
    ]


def format_daily_brief(brief: dict, agent_name: str = "") -> str:
    name = str(agent_name or "").strip()
    lines = [f"Good morning, {name}." if name else "Good morning."]

    if not any(
        brief.get(field)
        for field in (
            "overdue_followups",
            "followups_due_today",
            "birthdays_today",
            "pending_drafts",
        )
    ):
        return "\n\n".join(lines + ["You have no urgent CRM tasks today."])

    lines.extend(["", "Today's priorities"])

    overdue = brief.get("overdue_followups") or []
    if overdue:
        lines.extend(["", "Overdue follow-ups"])
        for item in overdue:
            days = item.get("days_overdue", 0)
            unit = "day" if days == 1 else "days"
            lines.append(f"- {item.get('client_name', '')} — overdue by {days} {unit}")

    due_today = brief.get("followups_due_today") or []
    if due_today:
        lines.extend(["", "Follow-ups due today"])
        lines.extend(f"- {item.get('client_name', '')}" for item in due_today)

    birthdays = brief.get("birthdays_today") or []
    if birthdays:
        lines.extend(["", "Birthdays"])
        lines.extend(f"- {item.get('client_name', '')}" for item in birthdays)

    drafts = brief.get("pending_drafts") or []
    if drafts:
        lines.extend(["", "Drafts waiting for review"])
        for item in drafts:
            purpose = str(item.get("purpose") or "email").strip().capitalize()
            client_name = str(item.get("client_name") or "").strip()
            label = f"{purpose} email"
            lines.append(f"- {label} for {client_name}" if client_name else f"- {label}")

    action = brief.get("suggested_action")
    if action:
        lines.extend(["", "Suggested first action", f"- {_format_suggested_action(action)}"])

    return "\n".join(lines)


def _format_suggested_action(action: dict) -> str:
    kind = action.get("kind")
    client_name = str(action.get("client_name") or "").strip()
    if kind in {"overdue_followup", "followup_due_today"}:
        return f"Follow up with {client_name}"
    if kind == "birthday":
        return f"Wish {client_name} a happy birthday"
    if kind == "pending_draft":
        purpose = str(action.get("purpose") or "email").strip()
        return f"Review the {purpose} email for {client_name}" if client_name else "Review the email draft"
    return "Review today's priorities"


async def get_client_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await update.message.reply_text("Usage:\n/get_client John Smith")
        return

    client_name = parts[1].strip()
    client = crm.get_client(client_name)
    if not client:
        await update.message.reply_text(format_client_not_found_reply(client_name))
        return

    await update.message.reply_text(crm.format_client_report(client))


async def generate_birthday_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await update.message.reply_text("Usage:\n/generate_birthday_email John Smith")
        return

    client_name = parts[1].strip()
    client = crm.get_client(client_name)
    if not client:
        await update.message.reply_text(format_client_not_found_reply(client_name))
        return

    draft = generate_birthday_email(client, agent_profile)
    if update.effective_user is not None:
        store_pending_email_draft(update.effective_user.id, client, draft)

    await update.message.reply_text(format_email_draft_reply(draft))


async def send_last_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    pending_record = pending_email_drafts.get(user_id) if user_id is not None else None
    draft = get_pending_email_draft(pending_record)

    if draft is None:
        await update.message.reply_text("No pending email draft.")
        return

    client_name = get_pending_email_client_name(pending_record)
    client = crm.get_client(client_name) if client_name else None
    email_address = (client or {}).get("email", "").strip()
    if not email_address:
        await update.message.reply_text("Client does not have an email address.")
        return

    await update.message.reply_text(format_email_send_preview(email_address, draft))


async def confirm_send_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    pending_record = pending_email_drafts.get(user_id) if user_id is not None else None
    draft = get_pending_email_draft(pending_record)

    if draft is None:
        await update.message.reply_text("No pending email draft.")
        return

    if read_app_env() != "production":
        await update.message.reply_text("Email sending is disabled outside production.")
        return

    client_name = get_pending_email_client_name(pending_record)
    client = crm.get_client(client_name) if client_name else None
    email_address = (client or {}).get("email", "").strip()
    if not email_address:
        await update.message.reply_text("Client does not have an email address.")
        return

    try:
        send_email(
            email_address,
            draft.get("subject", ""),
            draft.get("body", ""),
        )
    except Exception:
        log_event("request_failed")
        await update.message.reply_text("Could not send email. Please try again later.")
        return

    del pending_email_drafts[user_id]
    await update.message.reply_text("Email sent successfully.")


async def cancel_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    if user_id is None or user_id not in pending_email_drafts:
        await update.message.reply_text("No pending email draft.")
        return

    del pending_email_drafts[user_id]
    await update.message.reply_text("Email draft canceled.")


def format_clients_list(clients: list[dict]) -> str:
    if not clients:
        return "No clients found."

    lines = [
        f"- {client.get('name', '')} | {client.get('status', '')} | {client.get('phone', '') or '-'}"
        for client in clients
    ]
    return "Clients:\n" + "\n".join(lines)


def format_email_draft_reply(draft: dict, title: str = "Birthday email draft") -> str:
    return (
        f"{title}. Please review before sending.\n\n"
        f"Subject: {draft.get('subject', '')}\n\n"
        f"{draft.get('body', '')}"
    )


def format_email_send_preview(email_address: str, draft: dict) -> str:
    return (
        "Ready to send this email?\n\n"
        f"To: {email_address}\n"
        f"Subject: {draft.get('subject', '')}\n\n"
        f"{draft.get('body', '')}\n\n"
        "/confirm_send_email to send\n"
        "/cancel_email to cancel"
    )


def format_client_not_found_reply(client_name: str) -> str:
    reply = f"Client not found: {client_name}"
    suggestion = crm.suggest_client_name(client_name) if client_name.strip() else None
    if isinstance(suggestion, str) and suggestion.strip():
        reply += f"\nDid you mean: {suggestion}?"
    return reply


def resolve_spoken_client(
    client_name: str, *, assume_exact_if_clients_unavailable: bool = False
) -> dict:
    exact_client = crm.get_client(client_name)
    if isinstance(exact_client, dict) and exact_client:
        return {
            "status": "exact",
            "client": exact_client,
            "candidates": [exact_client],
            "score": 1.0,
        }
    clients = crm.list_clients()
    if not isinstance(clients, list) and assume_exact_if_clients_unavailable:
        # Production CRM always returns a list; this supports lightweight test doubles.
        client = {"name": client_name}
        return {
            "status": "exact",
            "client": client,
            "candidates": [client],
            "score": 1.0,
        }
    return resolve_client_reference(
        client_name,
        clients if isinstance(clients, list) else [],
    )


def format_ambiguous_client_reply(client_name: str, resolution: dict) -> str:
    names = [
        str(client.get("name") or "").strip()
        for client in resolution.get("candidates", [])
        if str(client.get("name") or "").strip()
    ]
    return (
        f"I found multiple possible matches for: {client_name}\n"
        + "\n".join(f"- {name}" for name in names)
        + "\nPlease say or type the full client name."
    )


def format_delete_client_preview(client: dict, heard_name: str = "") -> str:
    matched = ""
    actual_name = str(client.get("name") or "").strip()
    if heard_name and heard_name.casefold() != actual_name.casefold():
        matched = f'Closest match for "{heard_name}": {actual_name}\n\n'
    return (
        f"{matched}Delete this client?\n\n"
        f"Name: {actual_name}\n"
        f"Status: {client.get('status', '') or '-'}\n"
        f"Email: {client.get('email', '') or '-'}\n"
        f"Phone: {client.get('phone', '') or '-'}\n\n"
        "No client has been deleted yet.\n"
        "/confirm_delete_client to delete\n"
        "/cancel_delete_client to cancel"
    )


async def delete_client_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Usage:\n/delete_client John Smith")
        return
    await prepare_delete_client(update, parts[1].strip())


async def prepare_delete_client(update: Update, client_name: str) -> bool:
    user_id = update.effective_user.id if update.effective_user is not None else None
    if user_id is None:
        await update.message.reply_text("Could not identify the current Telegram user.")
        return True

    resolution = resolve_spoken_client(client_name)
    if resolution["status"] == "ambiguous":
        await update.message.reply_text(
            format_ambiguous_client_reply(client_name, resolution)
        )
        return True
    if resolution["status"] == "not_found":
        await update.message.reply_text(format_client_not_found_reply(client_name))
        return True

    client = resolution["client"]
    pending_client_actions[user_id] = {
        "kind": "delete_client",
        "client_name": client.get("name", ""),
    }
    await update.message.reply_text(format_delete_client_preview(client, client_name))
    return True


async def confirm_delete_client_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id if update.effective_user is not None else None
    action = pending_client_actions.get(user_id) if user_id is not None else None
    if not action or action.get("kind") != "delete_client":
        await update.message.reply_text("No client deletion is waiting for confirmation.")
        return

    client_name = str(action.get("client_name") or "")
    if not crm.get_client(client_name) or not crm.delete_client(client_name):
        del pending_client_actions[user_id]
        await update.message.reply_text("Client no longer exists. Nothing was deleted.")
        return

    del pending_client_actions[user_id]
    await update.message.reply_text(f"Client deleted: {client_name}")


async def cancel_delete_client_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else None
    action = pending_client_actions.get(user_id) if user_id is not None else None
    if not action or action.get("kind") != "delete_client":
        await update.message.reply_text("No client deletion is waiting for confirmation.")
        return
    del pending_client_actions[user_id]
    await update.message.reply_text("Client deletion canceled. No client was deleted.")


def transcribe_voice_file(file_path: str) -> str:
    if get_openai_client() is None:
        raise ValueError("OPENAI_API_KEY is not set")

    with open(file_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
        )

    return (transcript.text or "").strip()


def extract_voice_client_update_with_openai(text: str) -> tuple[str, str] | None:
    if get_openai_client() is None:
        return None

    response = openai_client.responses.create(
        model="gpt-5.4",
        instructions=(
            "You extract structured CRM update data from voice transcripts. "
            "Return only JSON, no markdown. Only support intent update_client. "
            "If the transcript is not a client update, return "
            '{"intent":"unknown","client_name":"","fields":{}}. '
            "Allowed fields: status, notes, next_followup, last_contact, phone, "
            "email, budget, areas, requirements. Normalize obvious dates to YYYY-MM-DD."
        ),
        input=(
            "Return JSON with this shape: "
            '{"intent":"update_client","client_name":"John Smith","fields":{}}.\n'
            f"Transcript: {text}"
        ),
    )

    try:
        data = json.loads(response.output_text.strip())
    except (AttributeError, json.JSONDecodeError):
        return None

    return voice_client_update_from_data(data)


def extract_voice_intent_with_openai(text: str) -> dict | None:
    if get_openai_client() is None:
        return None

    response = openai_client.responses.create(
        model="gpt-5.4",
        instructions=(
            "You extract intent from real estate assistant voice transcripts. "
            "Return only JSON, no markdown. Supported intents: list_clients, "
            "get_client, update_client, delete_client, generate_birthday_email, unknown. "
            "Map remove/delete client requests to delete_client. "
            "Use fields only for update_client. Allowed update fields: status, "
            "notes, next_followup, last_contact, phone, email, budget, areas, "
            "requirements. Normalize obvious dates to YYYY-MM-DD."
        ),
        input=(
            "Return JSON with this shape: "
            '{"intent":"get_client","client_name":"John Smith","fields":{}}.\n'
            f"Transcript: {text}"
        ),
    )

    try:
        data = json.loads(response.output_text.strip())
    except (AttributeError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    intent = str(data.get("intent") or "unknown").strip()
    if intent not in VOICE_ROUTER_INTENTS:
        intent = "unknown"

    client_name = str(data.get("client_name") or "").strip()
    fields = data.get("fields")
    if not isinstance(fields, dict):
        fields = {}

    return {
        "intent": intent,
        "client_name": client_name,
        "fields": fields,
    }


def revise_email_draft_with_openai(
    draft: dict,
    instruction: str,
    profile: dict | None = None,
) -> dict | None:
    if get_openai_client() is None:
        return None

    response = openai_client.responses.create(
        model="gpt-5.4",
        instructions=(
            "You revise email drafts for a real estate agent. Return only JSON, "
            "no markdown. The JSON must contain subject and body. Preserve the "
            "original intent unless the instruction explicitly changes it. Do not "
            "claim the email was sent. Agent DNA is the default style, but the "
            "user's explicit revision instruction takes priority for this draft. "
            "Agent DNA is not a source of client facts."
        ),
        input=(
            "Revise this email draft according to the spoken instruction.\n"
            f"Agent DNA JSON: {json.dumps(profile or agent_profile, ensure_ascii=False)}\n"
            f"Current draft JSON: {json.dumps(draft, ensure_ascii=False)}\n"
            f"Authoritative user revision instruction: {instruction}"
        ),
    )

    try:
        data = json.loads(response.output_text.strip())
    except (AttributeError, json.JSONDecodeError):
        return None

    subject = str(data.get("subject") or "").strip() if isinstance(data, dict) else ""
    body = str(data.get("body") or "").strip() if isinstance(data, dict) else ""
    if not subject or not body:
        return None

    return {"subject": subject, "body": body}


def format_voice_intent_debug_reply(
    heard_text: str,
    intent_data: dict,
    client_name: str = "",
) -> str:
    return (
        f"{format_client_not_found_reply(client_name)}\n"
        f"Heard: {heard_text}\n"
        f"Intent: {intent_data.get('intent', '')}\n"
        "Extracted data: "
        f"{json.dumps(intent_data, ensure_ascii=False, sort_keys=True)}"
    )


async def route_voice_intent(
    update: Update,
    intent_data: dict | None,
    heard_text: str = "",
) -> bool:
    if not isinstance(intent_data, dict):
        return False

    intent = intent_data.get("intent")

    if intent == "list_clients":
        await update.message.reply_text(format_clients_list(crm.list_clients()))
        return True

    if intent == "get_client":
        client_name = str(intent_data.get("client_name") or "").strip()
        if not client_name:
            if DEBUG and heard_text:
                await update.message.reply_text(
                    format_voice_intent_debug_reply(heard_text, intent_data, client_name)
                )
                return True
            return False

        resolution = resolve_spoken_client(client_name)
        if resolution["status"] == "ambiguous":
            await update.message.reply_text(
                format_ambiguous_client_reply(client_name, resolution)
            )
            return True
        client = resolution.get("client")
        if not client:
            if DEBUG and heard_text:
                await update.message.reply_text(
                    format_voice_intent_debug_reply(heard_text, intent_data, client_name)
                )
                return True

            await update.message.reply_text(format_client_not_found_reply(client_name))
            return True

        prefix = ""
        if resolution["status"] == "likely":
            prefix = (
                f'Showing closest match for "{client_name}": '
                f"{client.get('name', '')}\n\n"
            )
        await update.message.reply_text(prefix + crm.format_client_report(client))
        return True

    if intent == "update_client":
        client_update = voice_client_update_from_data(intent_data)
        if client_update is None:
            return False

        client_name, fields_text = client_update
        resolution = resolve_spoken_client(
            client_name,
            assume_exact_if_clients_unavailable=True,
        )
        if resolution["status"] == "ambiguous":
            await update.message.reply_text(
                format_ambiguous_client_reply(client_name, resolution)
            )
            return True
        if resolution["status"] == "not_found":
            await update.message.reply_text(format_client_not_found_reply(client_name))
            return True

        resolved_name = str(resolution["client"].get("name") or "")
        if resolution["status"] == "likely":
            user_id = update.effective_user.id if update.effective_user is not None else None
            if user_id is None:
                await update.message.reply_text(
                    "Could not identify the current Telegram user."
                )
                return True
            pending_client_actions[user_id] = {
                "kind": "update_client",
                "client_name": resolved_name,
                "fields_text": fields_text,
            }
            await update.message.reply_text(
                f'Closest match for "{client_name}": {resolved_name}\n\n'
                f"Proposed update: {fields_text}\n\n"
                "No client information has been changed yet.\n"
                "/confirm_client_action to update\n"
                "/cancel_client_action to cancel"
            )
            return True
        try:
            updated = crm.update_client_from_text(resolved_name, fields_text)
            await update.message.reply_text(
                "Client updated from voice:\n" + crm.format_client_report(updated)
            )
        except Exception as exc:
            log_event("request_failed")
            await update.message.reply_text(f"Could not update client from voice: {exc}")
        return True

    if intent == "delete_client":
        client_name = str(intent_data.get("client_name") or "").strip()
        if not client_name:
            return False
        return await prepare_delete_client(update, client_name)

    if intent == "generate_birthday_email":
        client_name = str(intent_data.get("client_name") or "").strip()
        if not client_name:
            if DEBUG and heard_text:
                await update.message.reply_text(
                    format_voice_intent_debug_reply(heard_text, intent_data, client_name)
                )
                return True
            return False

        resolution = resolve_spoken_client(client_name)
        if resolution["status"] == "ambiguous":
            await update.message.reply_text(
                format_ambiguous_client_reply(client_name, resolution)
            )
            return True
        client = resolution.get("client")
        if not client:
            if DEBUG and heard_text:
                await update.message.reply_text(
                    format_voice_intent_debug_reply(heard_text, intent_data, client_name)
                )
                return True

            await update.message.reply_text(format_client_not_found_reply(client_name))
            return True

        draft = generate_birthday_email(client, agent_profile)
        if update.effective_user is not None:
            store_pending_email_draft(update.effective_user.id, client, draft)

        await update.message.reply_text(format_email_draft_reply(draft))
        return True

    return False


async def confirm_client_action_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id if update.effective_user is not None else None
    action = pending_client_actions.get(user_id) if user_id is not None else None
    if not action or action.get("kind") != "update_client":
        await update.message.reply_text("No client update is waiting for confirmation.")
        return
    try:
        updated = crm.update_client_from_text(
            str(action.get("client_name") or ""),
            str(action.get("fields_text") or ""),
        )
    except Exception as exc:
        log_event("request_failed")
        await update.message.reply_text(f"Could not update client: {exc}")
        return
    del pending_client_actions[user_id]
    await update.message.reply_text(
        "Client updated from voice:\n" + crm.format_client_report(updated)
    )


async def cancel_client_action_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id if update.effective_user is not None else None
    action = pending_client_actions.get(user_id) if user_id is not None else None
    if not action or action.get("kind") != "update_client":
        await update.message.reply_text("No client update is waiting for confirmation.")
        return
    del pending_client_actions[user_id]
    await update.message.reply_text("Client update canceled. No information was changed.")


def voice_client_update_from_data(data: dict) -> tuple[str, str] | None:
    if not isinstance(data, dict):
        return None

    if data.get("intent") != "update_client":
        return None

    client_name = str(data.get("client_name") or "").strip()
    fields = data.get("fields")
    if not client_name or not isinstance(fields, dict):
        return None

    updates = []
    for key, value in fields.items():
        field_name = str(key).strip()
        if field_name not in VOICE_CLIENT_UPDATE_FIELDS:
            continue

        if value is None:
            continue

        field_value = str(value).strip()
        if not field_value:
            continue

        updates.append(f"{field_name}={field_value}")

    if not updates:
        return None

    return client_name, " | ".join(updates)


def parse_voice_client_update(text: str) -> tuple[str, str] | None:
    prefix = "update client"
    if not text.lower().startswith(prefix):
        return None

    body = text[len(prefix):].strip()
    field_aliases = [
        ("next_followup", ["next follow up", "next follow-up", "next_followup"]),
        ("last_contact", ["last contact", "last_contact"]),
        ("requirements", ["requirements", "requirement"]),
        ("status", ["status"]),
        ("notes", ["notes", "note"]),
        ("phone", ["phone"]),
        ("email", ["email"]),
        ("budget", ["budget"]),
        ("areas", ["areas", "area"]),
    ]

    parts = [part.strip() for part in body.split(",") if part.strip()]
    if len(parts) < 2:
        parts = split_voice_update_body(body, field_aliases)
    else:
        parts = merge_standalone_voice_fields(parts, field_aliases)

    if len(parts) < 2:
        raise ValueError(
            "Usage: Update client John Smith, status touring, next follow up 2026-05-28"
        )

    client_name = parts[0]
    if not client_name:
        raise ValueError("Client name is required.")

    updates = []
    for part in parts[1:]:
        field_name = ""
        value = ""

        for candidate_field, aliases in field_aliases:
            alias_pattern = "|".join(re.escape(alias) for alias in aliases)
            match = re.match(rf"^({alias_pattern})\s+(.+)$", part, flags=re.IGNORECASE)
            if match:
                field_name = candidate_field
                value = match.group(2).strip().rstrip(".")
                break

        if not field_name:
            raise ValueError(f"Unsupported update field: '{part}'")

        if not value:
            raise ValueError(f"Missing value for field '{field_name}'")

        if field_name in {"next_followup", "last_contact"}:
            value = normalize_voice_date(value)

        updates.append(f"{field_name}={value}")

    if not updates:
        raise ValueError("No update fields provided.")

    return client_name, " | ".join(updates)


def parse_voice_delete_intent(text: str) -> dict | None:
    cleaned = text.strip().rstrip(".")
    patterns = [
        r"^(?:please\s+)?(?:remove|delete)(?:\s+client)?\s+(.+)$",
        r"^(?:删除|刪除)(?:客户|客戶)?\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned, flags=re.IGNORECASE)
        if match and match.group(1).strip():
            return {
                "intent": "delete_client",
                "client_name": match.group(1).strip(),
                "fields": {},
            }
    return None


def split_voice_update_body(body: str, field_aliases: list[tuple[str, list[str]]]) -> list[str]:
    alias_to_field = {
        alias: field_name
        for field_name, aliases in field_aliases
        for alias in aliases
    }
    alias_pattern = "|".join(
        re.escape(alias) for alias in sorted(alias_to_field, key=len, reverse=True)
    )
    matches = list(
        re.finditer(rf"(?<!\w)({alias_pattern})(?!\w)\s+", body, flags=re.IGNORECASE)
    )
    if not matches:
        return [body.strip()] if body.strip() else []

    client_name = body[:matches[0].start()].strip(" ,")
    parts = [client_name]

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        field_text = body[match.start():end].strip(" ,")
        if field_text:
            parts.append(field_text)

    return parts


def merge_standalone_voice_fields(
    parts: list[str], field_aliases: list[tuple[str, list[str]]]
) -> list[str]:
    aliases = {
        alias.lower()
        for _, field_alias_list in field_aliases
        for alias in field_alias_list
    }
    merged = [parts[0]]
    index = 1

    while index < len(parts):
        current = parts[index].strip()
        if current.lower() in aliases and index + 1 < len(parts):
            merged.append(f"{current} {parts[index + 1].strip()}")
            index += 2
            continue

        if merged and not voice_part_starts_with_field(current, field_aliases):
            merged[-1] = f"{merged[-1]} {current}".strip()
            index += 1
            continue

        merged.append(current)
        index += 1

    return merged


def voice_part_starts_with_field(part: str, field_aliases: list[tuple[str, list[str]]]) -> bool:
    for _, aliases in field_aliases:
        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        if re.match(rf"^({alias_pattern})(\s+|$)", part, flags=re.IGNORECASE):
            return True

    return False


def normalize_voice_date(value: str) -> str:
    months = {
        "january": "01",
        "jan": "01",
        "february": "02",
        "feb": "02",
        "march": "03",
        "mar": "03",
        "april": "04",
        "apr": "04",
        "may": "05",
        "june": "06",
        "jun": "06",
        "july": "07",
        "jul": "07",
        "august": "08",
        "aug": "08",
        "september": "09",
        "sep": "09",
        "sept": "09",
        "october": "10",
        "oct": "10",
        "november": "11",
        "nov": "11",
        "december": "12",
        "dec": "12",
    }

    match = re.match(
        r"^(\d{4})\s+([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?$",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return value

    year, month_name, day = match.groups()
    month = months.get(month_name.lower())
    if not month:
        return value

    return f"{year}-{month}-{int(day):02d}"


async def diagnose_voice_draft_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if voice_draft_diagnostics.arm(update):
        await update.message.reply_text(
            'Synthetic voice diagnostic armed for 2 minutes and one voice message. '
            'The next voice uses an isolated test fixture: no CRM read, draft generation, or email delivery.')


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.voice is None:
        return

    diagnostic = voice_draft_diagnostics.consume(update)
    if diagnostic == 'expired':
        await update.message.reply_text('Synthetic voice diagnostic expired. Re-arm it before retrying.')
        return
    log_event("voice_received")
    stage = "download"
    try:
        voice = update.message.voice
        telegram_file = await context.bot.get_file(voice.file_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"{voice.file_unique_id}.ogg")
            await telegram_file.download_to_drive(file_path)
            log_event("voice_downloaded")
            stage = "transcription"
            text = (transcribe_voice_file(file_path) or "").strip()

        stage = "routing"
        if text:
            log_event("voice_transcribed")
            if diagnostic == 'active':
                log_draft_diagnostic(analyze_synthetic_transcript(text))
                await update.message.reply_text(
                    'Synthetic diagnostic complete. Only safe metadata was logged; '
                    'no CRM read, draft generation, or email delivery.')
                return
            request = parse_crm_request(text)
            if (request is not None and request['intent'] in {'followup_query', 'followup_email'}
                    or request is None and natural_crm.has_pending_draft(update)
                    and text not in {"1", "2", "3", "4", "5"}):
                log_event("voice_draft_routed" if request is None or request["intent"] == "followup_email"
                          else "voice_followup_routed")
                await natural_crm.handle(update, crm, text)
                log_event("voice_reply_sent")
                return
            if text in {"1", "2", "3", "4", "5"} and await handle_tour_reply(update, text):
                log_event("voice_tour_reply_sent")
                return

            log_event("voice_legacy_routed")
            user_id = update.effective_user.id if update.effective_user is not None else None
            pending_draft = pending_email_drafts.get(user_id) if user_id is not None else None

            intent_data = extract_voice_intent_with_openai(text)
            if not intent_data or intent_data.get("intent") == "unknown":
                intent_data = parse_voice_delete_intent(text) or intent_data
            if await route_voice_intent(update, intent_data, text):
                return

            if pending_draft is not None:
                draft = get_pending_email_draft(pending_draft)
                revised_draft = revise_email_draft_with_openai(draft, text, agent_profile)
                if revised_draft is None:
                    await update.message.reply_text(
                        "Could not revise the email draft from voice. Please try again later."
                    )
                    return

                if isinstance(pending_draft, dict) and "draft" in pending_draft:
                    pending_draft["draft"] = revised_draft
                else:
                    pending_email_drafts[user_id] = revised_draft
                await update.message.reply_text(
                    "Updated birthday email draft. Please review before sending.\n\n"
                    f"Subject: {revised_draft.get('subject', '')}\n\n"
                    f"{revised_draft.get('body', '')}"
                )
                return

            try:
                client_update = extract_voice_client_update_with_openai(text)
                if client_update is None:
                    client_update = parse_voice_client_update(text)
            except ValueError as exc:
                await update.message.reply_text(f"Could not update client from voice: {exc}")
                return

            if client_update is not None:
                client_name, fields_text = client_update
                try:
                    updated = crm.update_client_from_text(client_name, fields_text)
                    await update.message.reply_text(
                        "Client updated from voice:\n" + crm.format_client_report(updated)
                    )
                except Exception as exc:
                    log_event("request_failed")
                    await update.message.reply_text(f"Could not update client from voice: {exc}")
                return

            await update.message.reply_text(f"Transcription:\n{text}")
        else:
            log_event("voice_empty_transcript")
            await update.message.reply_text("I could not recognize any text in that voice message.")

    except Exception:
        events = {"download": "voice_download_failed", "transcription": "voice_transcription_failed",
                  "routing": "voice_routing_failed"}
        replies = {"download": "Could not download the voice message. Please try again.",
                   "transcription": "Voice transcription failed. Please try again later.",
                   "routing": "Could not process the voice message. Please try again."}
        log_event(events[stage])
        try:
            await update.message.reply_text(replies[stage])
        except Exception:
            log_event("voice_reply_failed")
            raise


async def handle_ai_debug(update: Update, user_text: str):
    parsed = parse_user_intent(user_text[3:].strip())
    debug("AI intent parsed")

    intent = parsed.get("intent", "unknown")

    await update.message.reply_text(
        "AI 解析结果：\n" + json.dumps(parsed, ensure_ascii=False, indent=2)
    )

    if intent == "compare_properties":
        await update.message.reply_text(compare_properties())
        return

    if intent == "find_best_properties":
        await update.message.reply_text(find_best_properties())
        return

    if intent == "show_memory":
        memory = load_memory()
        await update.message.reply_text(f"这是我目前的记忆：\n{memory}")
        return

    if intent == "delete_property":
        address = parsed.get("address", "").strip()
        success, msg = delete_property(address)
        await update.message.reply_text(msg)
        return

    if intent == "analyze_town":
        report = handle_analyze_town(user_text[3:].strip())
        await update.message.reply_text(report)
        return

    await update.message.reply_text("这个意图暂时还没接业务逻辑。")


async def handle_memory_commands(update: Update, user_text: str) -> bool:
    if user_text.startswith("记住") or user_text.startswith("記住"):
        fact = user_text[2:].strip()
        if fact:
            if "喜欢" in fact or "喜歡" in fact:
                append_preference(fact)
                await update.message.reply_text(f"好，我把这个记到 preferences 里了：{fact}")
            else:
                append_fact(fact)
                await update.message.reply_text(f"好，我把这个记到 facts 里了：{fact}")
        else:
            await update.message.reply_text("你可以这样说：记住我喜欢投资房产")
        return True

    if "你记得什么" in user_text or "你記得什麼" in user_text:
        memory = load_memory()
        await update.message.reply_text(f"这是我目前的记忆：\n{memory}")
        return True

    return False


async def handle_property_analysis(update: Update, user_text: str) -> bool:
    if user_text.startswith("幫我分析這段房屋信息：") or user_text.startswith("帮我分析这段房屋信息："):
        if "：" in user_text:
            raw_text = user_text.split("：", 1)[1].strip()
        elif ":" in user_text:
            raw_text = user_text.split(":", 1)[1].strip()
        else:
            raw_text = user_text

        info = auto_extract_house_info(raw_text)
        normalized_text = normalize_to_analysis_text(info)
        analysis_text, info, analysis_data = analyze_house(normalized_text)

        final_text, saved = run_property_pipeline(info, analysis_text, analysis_data)

        if saved:
            await update.message.reply_text(
                "我已自动提取房屋资料并完成综合分析。\n\n"
                + final_text
                + "\n这套房子已经记进 memory。"
            )
        else:
            await update.message.reply_text(
                "我已自动提取房屋资料并完成综合分析。\n\n"
                + final_text
                + "\n这套房子之前已经在 memory 里了，我这次没有重复记录。"
            )
        return True

    if (
        "分析这个房子" in user_text
        or "分析這個房子" in user_text
        or user_text.startswith("分析房子")
    ):
        analysis_text, info, analysis_data = analyze_house(user_text)
        final_text, saved = run_property_pipeline(info, analysis_text, analysis_data)

        if saved:
            await update.message.reply_text(
                final_text + "\n这套房子已经连同分析结果一起记进 memory 了。"
            )
        else:
            await update.message.reply_text(
                final_text + "\n这套房子之前已经在 memory 里了，我这次没有重复记录。"
            )
        return True

    return False


async def handle_property_queries(update: Update, user_text: str) -> bool:
    if "看过" in user_text and "房子" in user_text:
        summary = summarize_properties()
        await update.message.reply_text(summary)
        return True

    if "比较" in user_text and "房子" in user_text:
        result = compare_properties()
        await update.message.reply_text(result)
        return True

    if ("现金流最好" in user_text or "現金流最好" in user_text or "最值得研究" in user_text) and "房子" in user_text:
        result = find_best_properties()
        await update.message.reply_text(result)
        return True

    if (
        "帮我筛选最优房产" in user_text
        or "幫我篩選最優房產" in user_text
        or "哪套房子最值得投资" in user_text
        or "哪套房子最值得投資" in user_text
        or "最优房产" in user_text
    ):
        result = find_best_properties()
        await update.message.reply_text(result)
        return True

    if (
        "帮我找" in user_text
        or "幫我找" in user_text
        or "筛选" in user_text
        or "篩選" in user_text
    ):
        if "房子" in user_text or "房产" in user_text or "房產" in user_text:
            result = find_deals_by_filters(user_text)
            await update.message.reply_text(result)
            return True

    return False


async def handle_property_management(update: Update, user_text: str) -> bool:
    if user_text.startswith(("删除房产：", "刪除房產：", "删除房产:", "刪除房產:")):
        address = parse_delete_address(user_text)
        success, msg = delete_property(address)
        await update.message.reply_text(msg)
        return True

    if user_text in ["清空房产", "清空房產"]:
        msg = clear_all_properties()
        await update.message.reply_text(msg)
        return True

    return False


async def handle_town_commands(update: Update, user_text: str) -> bool:
    if user_text.startswith("分析town: ") or user_text.startswith("分析 town: "):
        raw = user_text.split(":", 1)[1].strip() if ":" in user_text else ""
        city, state = parse_city_state(raw)

        if not city:
            await update.message.reply_text("请输入正确格式，例如：分析town: Princeton, NJ")
            return True

        if not state:
            state = "NJ"

        result = run_town_pipeline(city, state)
        reply = result["report"] if result["success"] else result["message"]
        await update.message.reply_text(reply)
        return True

    if user_text.startswith("分析 town ") or user_text.startswith("分析town "):
        raw = user_text.replace("分析 town", "").replace("分析town", "").strip()
        city, state = parse_city_state(raw)

        if not city:
            await update.message.reply_text("请输入正确格式，例如：分析town Princeton, NJ")
            return True

        if not state:
            state = "NJ"

        # 👉 调用 pipeline
        result = run_town_pipeline(city, state)

        # 👉 安全处理返回结果（重点）
        if result.get("success"):
            reply = result.get("report", f"{city}, {state} 分析完成，但没有生成报告")
        else:
            reply = result.get("message", f"{city}, {state} 的 town 分析失败")

        await update.message.reply_text(reply)
        return True

    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        debug("收到消息了")
        debug("Update received")

        if update.message is None:
            debug("update.message is None")
            return

        user_text = (update.message.text or "").strip()



        if not user_text:
            await update.message.reply_text("我收到的是空消息。")
            return

        if await handle_tour_reply(update, user_text):
            return

        # Text CRM stays behind authorization and tour handling, ahead of legacy rules.
        if await natural_crm.handle(update, crm, user_text):
            return

        if user_text.startswith("AI:"):
            await handle_ai_debug(update, user_text)
            return

        if await handle_memory_commands(update, user_text):
            return

        if await handle_property_analysis(update, user_text):
            return

        if await handle_property_queries(update, user_text):
            return

        if await handle_property_management(update, user_text):
            return

        if await handle_town_commands(update, user_text):
            return

        debug("进入兜底分支")
        msg = await update.message.reply_text(f"我收到了：{user_text}")
        debug("reply_text 成功, message_id =", msg.message_id)

    except Exception as e:
        log_event("request_failed")
        await update.message.reply_text("Could not process this request. Please try again.")


async def handle_application_error(update, context):
    # Provider exceptions and Update reprs may contain tokens or customer data.
    log_telegram_error(context.error)


async def telegram_initialized(application):
    # PTB calls post_init only after successful Application.initialize().
    log_event("telegram_initialized")


def main():
    stage = "runtime_setup"

    async def after_initialize(application):
        nonlocal stage
        stage = "polling_after_init"
        await telegram_initialized(application)

    configure_logging()
    log_event("startup")
    try:
        initialize_runtime()

        if not TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")

        builder = ApplicationBuilder().token(TOKEN)
        builder.post_init(after_initialize)
        app = builder.build()
        app.add_error_handler(handle_application_error)

        app.add_handler(CommandHandler("diagnose_voice_draft", owner_only(diagnose_voice_draft_command, command_name="diagnose_voice_draft")))
        app.add_handler(CommandHandler("start", owner_only(start, command_name="start")))
        app.add_handler(CommandHandler("help", owner_only(help_command, command_name="help")))
        app.add_handler(CommandHandler("tour", owner_only(tour_command, command_name="tour")))
        app.add_handler(CommandHandler("cancel_tour", owner_only(cancel_tour_command, command_name="cancel_tour")))
        app.add_handler(CommandHandler("add_client", owner_only(add_client_command, command_name="add_client")))
        app.add_handler(CommandHandler("list_clients", owner_only(list_clients_command, command_name="list_clients")))
        app.add_handler(CommandHandler("client_import_template", owner_only(client_import_template_command, command_name="client_import_template")))
        app.add_handler(CommandHandler("import_clients", owner_only(import_clients_command, command_name="import_clients")))
        app.add_handler(CommandHandler("confirm_import_clients", owner_only(confirm_import_clients_command, command_name="confirm_import_clients")))
        app.add_handler(CommandHandler("cancel_import_clients", owner_only(cancel_import_clients_command, command_name="cancel_import_clients")))
        app.add_handler(CommandHandler("daily_brief", owner_only(daily_brief_command, command_name="daily_brief")))
        app.add_handler(CommandHandler("get_client", owner_only(get_client_command, command_name="get_client")))
        app.add_handler(CommandHandler("delete_client", owner_only(delete_client_command, command_name="delete_client")))
        app.add_handler(CommandHandler("confirm_delete_client", owner_only(confirm_delete_client_command, command_name="confirm_delete_client")))
        app.add_handler(CommandHandler("cancel_delete_client", owner_only(cancel_delete_client_command, command_name="cancel_delete_client")))
        app.add_handler(CommandHandler("confirm_client_action", owner_only(confirm_client_action_command, command_name="confirm_client_action")))
        app.add_handler(CommandHandler("cancel_client_action", owner_only(cancel_client_action_command, command_name="cancel_client_action")))
        app.add_handler(CommandHandler("generate_birthday_email", owner_only(generate_birthday_email_command, command_name="generate_birthday_email")))
        app.add_handler(CommandHandler("send_last_email", owner_only(send_last_email_command, command_name="send_last_email")))
        app.add_handler(CommandHandler("confirm_send_email", owner_only(confirm_send_email_command, command_name="confirm_send_email")))
        app.add_handler(CommandHandler("cancel_email", owner_only(cancel_email_command, command_name="cancel_email")))
        app.add_handler(MessageHandler(filters.VOICE, owner_only(handle_voice_message)))
        app.add_handler(MessageHandler(filters.Document.ALL, owner_only(handle_client_import_document)))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, owner_only(handle_message)))

        register_automatic_daily_brief(app)
        stage = "polling_before_init"
        log_event("polling_started")
        app.run_polling()
    except Exception as exc:
        log_telegram_error(exc, fallback="runtime_failed")
        log_lifecycle_failure(stage, exc)
        raise
    finally:
        log_event("shutdown")


if __name__ == "__main__":
    try:
        main()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from None
    except Exception:
        raise SystemExit("Startup failed. Check configuration and connectivity; details suppressed.") from None
