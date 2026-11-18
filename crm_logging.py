"""Console events with a closed vocabulary: never format request/provider data."""
import logging
from telegram.error import TelegramError, InvalidToken, Conflict, NetworkError, BadRequest

COMMANDS = frozenset({
    'diagnose_voice_draft', 'start', 'help', 'tour', 'cancel_tour', 'add_client', 'list_clients',
    'client_import_template', 'import_clients', 'confirm_import_clients',
    'cancel_import_clients', 'daily_brief', 'get_client', 'delete_client',
    'confirm_delete_client', 'cancel_delete_client', 'confirm_client_action',
    'cancel_client_action', 'generate_birthday_email', 'send_last_email',
    'confirm_send_email', 'cancel_email',
})
EVENTS = {
    'draft_diagnostic': (logging.INFO, 'Synthetic draft diagnostic v1'),
    'voice_received': (logging.INFO, 'Voice stage: received'),
    'voice_downloaded': (logging.INFO, 'Voice stage: downloaded'),
    'voice_transcribed': (logging.INFO, 'Voice stage: transcribed'),
    'voice_draft_routed': (logging.INFO, 'Voice stage: draft_routed'),
    'voice_followup_routed': (logging.INFO, 'Voice stage: followup_routed'),
    'voice_reply_sent': (logging.INFO, 'Voice stage: reply_sent'),
    'voice_tour_reply_sent': (logging.INFO, 'Voice stage: tour_reply_sent'),
    'voice_legacy_routed': (logging.INFO, 'Voice stage: legacy_routed'),
    'voice_empty_transcript': (logging.WARNING, 'Voice failure: empty_transcript'),
    'voice_download_failed': (logging.ERROR, 'Voice failure: download'),
    'voice_transcription_failed': (logging.ERROR, 'Voice failure: transcription'),
    'voice_routing_failed': (logging.ERROR, 'Voice failure: routing'),
    'voice_reply_failed': (logging.ERROR, 'Voice failure: reply'),
    'telegram_initialized': (logging.INFO, 'Telegram initialization succeeded'),
    'authorization_owner_not_allowed': (logging.WARNING, 'Authorization rejected: owner_not_allowed'),
    'authorization_chat_not_allowed': (logging.WARNING, 'Authorization rejected: chat_not_allowed'),
    'authorization_missing_identity': (logging.WARNING, 'Authorization rejected: missing_identity'),
    'telegram_error_authentication': (logging.ERROR, 'Telegram error: authentication'),
    'telegram_error_polling_conflict': (logging.ERROR, 'Telegram error: polling_conflict'),
    'telegram_error_network': (logging.ERROR, 'Telegram error: network'),
    'telegram_error_other': (logging.ERROR, 'Telegram error: other'),
    'startup': (logging.INFO, 'CRM bot starting'),
    'polling_started': (logging.INFO, 'Polling starting'),
    'shutdown': (logging.INFO, 'CRM bot stopped'),
    'command_received': (logging.INFO, 'Command received'),
    'command_completed': (logging.INFO, 'Command completed'),
    'request_failed': (logging.ERROR, 'Request failed; details suppressed'),
    'runtime_failed': (logging.ERROR, 'Startup or polling failed; details suppressed'),
}


DIAGNOSTIC_VALUES = {
    'route': {'natural_draft', 'natural_query', 'other_crm', 'legacy_voice'},
    'extraction': {'complete', 'missing_purpose', 'not_draft'},
    'normalization': {'nfkc_changed', 'unchanged'},
    'matching': {'strict_exact', 'format_exact', 'partial', 'fuzzy', 'fuzzy_ambiguous',
                 'duplicate_exact', 'format_collision', 'no_match', 'not_evaluated'},
    'clarification': {'none', 'partial_name', 'fuzzy_name', 'ambiguous_name', 'duplicate_name',
                      'formatting_collision', 'client_not_found', 'missing_purpose', 'intent_not_draft'},
    'site': {'natural_resolve', 'none'},
}


def safe_draft_diagnostic(metadata):
    if type(metadata) is not dict:
        return {}
    safe = {key: metadata[key] for key, allowed in DIAGNOSTIC_VALUES.items()
            if type(metadata.get(key)) is str and metadata[key] in allowed}
    count = metadata.get('candidate_tokens')
    if type(count) is int and 0 <= count <= 20:
        safe['candidate_tokens'] = count
    return safe


def log_draft_diagnostic(metadata):
    logging.getLogger('bot').info('draft_diagnostic', extra={'diagnostic': safe_draft_diagnostic(metadata)})


class SafeEventFormatter(logging.Formatter):
    def format(self, record):
        # Do not use getMessage(), exception formatting, or arbitrary extra fields.
        event = EVENTS.get(record.msg) if type(record.msg) is str else None
        level, message = event or (logging.ERROR, 'Event details suppressed')
        command = getattr(record, 'command', None)
        if (event and record.msg in ('command_received', 'command_completed')
                and type(command) is str and command in COMMANDS):
            message += f': /{command}'
        if event and record.msg == 'draft_diagnostic':
            safe = safe_draft_diagnostic(getattr(record, 'diagnostic', None))
            message += ' ' + ' '.join(f'{key}={value}' for key, value in safe.items())
        return f'{logging.getLevelName(level)} {message}'


def configure_logging():
    logger = logging.getLogger('bot')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, '_crm_console', False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler._crm_console = True
        handler.setLevel(logging.INFO)
        handler.setFormatter(SafeEventFormatter())
        logger.addHandler(handler)
    for name in ('httpx', 'httpcore', 'telegram', 'openai', 'apscheduler'):
        transport = logging.getLogger(name)
        if not (len(transport.handlers) == 1
                and isinstance(transport.handlers[0], logging.NullHandler)):
            transport.handlers = [logging.NullHandler()]
        transport.propagate = False


def log_event(event, command=None):
    if type(event) is not str or event not in EVENTS:
        return
    safe_command = command if type(command) is str and command in COMMANDS else None
    logging.getLogger('bot').log(EVENTS[event][0], event,
                               extra={'command': safe_command})


def classify_telegram_error(error):
    """Inspect types only; exception text may contain credentials or API URLs."""
    if isinstance(error, InvalidToken):
        return 'authentication'
    if isinstance(error, Conflict):
        return 'polling_conflict'
    # BadRequest inherits NetworkError in PTB but is an API rejection, not transport failure.
    if isinstance(error, NetworkError) and not isinstance(error, BadRequest):
        return 'network'
    return 'other'


def log_telegram_error(error, fallback='request_failed'):
    if isinstance(error, TelegramError):
        log_event('telegram_error_' + classify_telegram_error(error))
    else:
        log_event(fallback)
