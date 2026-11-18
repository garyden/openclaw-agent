"""One fail-closed boundary for every registered Telegram handler."""
from crm_logging import log_event
from functools import wraps
import os
from time import monotonic
from app_config import ConfigurationError, parse_ids


def allowed_chat(chat_id) -> bool:
    try:
        return type(chat_id) is int and chat_id in parse_ids(
            os.getenv('TELEGRAM_ALLOWED_CHAT_IDS', ''), 'TELEGRAM_ALLOWED_CHAT_IDS')
    except ConfigurationError:
        return False


def rejection_category(update):
    user = getattr(update, 'effective_user', None)
    chat = getattr(update, 'effective_chat', None)
    if (user is None or chat is None or type(getattr(user, 'id', None)) is not int
            or type(getattr(chat, 'id', None)) is not int):
        return 'missing_identity'
    try:
        owners = parse_ids(os.getenv('TELEGRAM_OWNER_IDS', ''),
                           'TELEGRAM_OWNER_IDS', positive=True)
    except ConfigurationError:
        return 'owner_not_allowed'
    if user.id not in owners or getattr(user, 'is_bot', False):
        return 'owner_not_allowed'
    if not allowed_chat(chat.id):
        return 'chat_not_allowed'
    return None


def authorized(update) -> bool:
    return rejection_category(update) is None


# Process-wide, bounded to three categories; never retain identities or request data.
_rejection_last_logged = {}
REJECTION_LOG_INTERVAL = 60.0


def log_rejection(category):
    if category not in ('owner_not_allowed', 'chat_not_allowed', 'missing_identity'):
        return
    now = monotonic()
    last = _rejection_last_logged.get(category)
    if last is None or now - last >= REJECTION_LOG_INTERVAL:
        _rejection_last_logged[category] = now
        log_event('authorization_' + category)


def owner_only(callback, *, command_name=None):
    @wraps(callback)
    async def guarded(update, context):
        category = rejection_category(update)
        if category is not None:
            log_rejection(category)
            # No Telegram reply or customer-data access on rejection.
            return None
        if command_name is not None:
            log_event('command_received', command_name)
        result = await callback(update, context)
        if command_name is not None:
            log_event('command_completed', command_name)
        return result
    return guarded
