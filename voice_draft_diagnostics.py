"""Opt-in, one-shot voice draft probe using an isolated synthetic fixture only.

Never opens configuration/data files, calls a model, or retains transcript text.
"""
import os
import re
import unicodedata
from time import monotonic

from authorization import authorized
from natural_crm import classify_client_match, parse_request


class VoiceDraftDiagnostics:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self._session = None
        self._expires = 0

    @staticmethod
    def permitted(update):
        if os.getenv('CRM_DRAFT_DIAGNOSTICS_ENABLED', '').strip().lower() != 'true':
            return False
        developer = os.getenv('CRM_DRAFT_DIAGNOSTICS_DEVELOPER_ID', '').strip()
        return (len(developer) <= 20 and developer.isascii() and developer.isdecimal() and authorized(update)
                and update.effective_user.id == int(developer))

    def arm(self, update):
        if not self.permitted(update):
            return False
        self._session = (update.effective_user.id, update.effective_chat.id)
        self._expires = self.clock() + 120
        return True

    def consume(self, update):
        if self._session is None or not self.permitted(update):
            return None
        if self._session != (update.effective_user.id, update.effective_chat.id):
            return None
        self._session = None  # One-shot even if download/transcription later fails.
        return 'active' if self.clock() < self._expires else 'expired'


def analyze_synthetic_transcript(text):
    """Same parser/resolver as production, against one fixed synthetic record."""
    request = parse_request(text)
    draft = request is not None and request['intent'] == 'followup_email'
    candidate = request['name'] if draft else ''
    extraction = ('complete' if request['purpose'] else 'missing_purpose') if draft else 'not_draft'
    route = ('natural_draft' if draft else 'natural_query' if request and request['intent'] == 'followup_query'
             else 'other_crm' if request else 'legacy_voice')
    match_kind = 'not_evaluated'
    reason = 'intent_not_draft'
    if draft:
        match_kind, _ = classify_client_match(candidate, [{'name': 'MVP Test Client'}], draft=True)
        reason = {'strict_exact': 'none', 'format_exact': 'none', 'partial': 'partial_name',
                  'fuzzy': 'fuzzy_name', 'fuzzy_ambiguous': 'ambiguous_name',
                  'duplicate_exact': 'duplicate_name', 'format_collision': 'formatting_collision',
                  'no_match': 'client_not_found'}[match_kind]
        if reason == 'none' and not request['purpose']:
            reason = 'missing_purpose'
    return {
        'route': route,
        'extraction': extraction,
        'candidate_tokens': min(20, len(re.findall(r'\w+', candidate))),
        'normalization': 'nfkc_changed' if unicodedata.normalize('NFKC', candidate) != candidate else 'unchanged',
        'matching': match_kind,
        'clarification': reason,
        'site': 'natural_resolve' if reason in {'partial_name', 'fuzzy_name', 'ambiguous_name',
                                             'duplicate_name', 'formatting_collision'} else 'none',
    }


def inspect_synthetic_transcript_locally(text, inspector):
    """Offline/test-only callback: inspect exact strings in local memory, no I/O.

    Not called by Telegram handlers. The caller must not log/persist the strings.
    """
    request = parse_request(text)
    candidate = request.get('name') if request and request['intent'] == 'followup_email' else None
    inspector(text, candidate)
    return analyze_synthetic_transcript(text)
