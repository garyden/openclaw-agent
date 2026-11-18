"""No data files or APIs: synthetic metadata, authorization gates, and privacy tests."""
import io
import contextlib
import logging
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from crm_logging import SafeEventFormatter, log_draft_diagnostic
from voice_draft_diagnostics import (VoiceDraftDiagnostics, analyze_synthetic_transcript,
                                     inspect_synthetic_transcript_locally)

ENV = {'TELEGRAM_OWNER_IDS': '7,8', 'TELEGRAM_ALLOWED_CHAT_IDS': '70,80',
       'CRM_DRAFT_DIAGNOSTICS_ENABLED': 'true', 'CRM_DRAFT_DIAGNOSTICS_DEVELOPER_ID': '7'}


def event(user=7, chat=70):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user, is_bot=False),
                           effective_chat=SimpleNamespace(id=chat))


class VoiceDraftDiagnosticsTest(unittest.TestCase):
    def test_mode_requires_flag_authorized_developer_and_chat(self):
        probe = VoiceDraftDiagnostics(clock=lambda: 100)
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(probe.arm(event()))
        for change in [{'CRM_DRAFT_DIAGNOSTICS_ENABLED': 'false'},
                       {'CRM_DRAFT_DIAGNOSTICS_DEVELOPER_ID': 'invalid'},
                       {'TELEGRAM_OWNER_IDS': '8'}, {'TELEGRAM_ALLOWED_CHAT_IDS': '80'}]:
            with patch.dict('os.environ', {**ENV, **change}, clear=True):
                self.assertFalse(probe.arm(event()))
        with patch.dict('os.environ', ENV, clear=True):
            self.assertFalse(probe.arm(event(8)))
            self.assertFalse(probe.arm(event(7, 90)))
            self.assertTrue(probe.arm(event()))
            self.assertIsNone(probe.consume(event(8)))
            self.assertIsNone(probe.consume(event(7, 80)))
            self.assertEqual(probe.consume(event()), 'active')
            self.assertIsNone(probe.consume(event()))

    def test_expiry_and_disabled_mode(self):
        now = [0]
        probe = VoiceDraftDiagnostics(clock=lambda: now[0])
        with patch.dict('os.environ', ENV, clear=True):
            self.assertTrue(probe.arm(event()))
            now[0] = 120
            self.assertEqual(probe.consume(event()), 'expired')
            self.assertIsNone(probe.consume(event()))
            probe.arm(event())
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(probe.consume(event()))

    def test_metadata_distinguishes_extraction_matching_and_typography(self):
        for text, expected in [
            ('Draft an email to MVP Test Client about availability', ('complete', 'strict_exact', 3)),
            ('Draft an email to M.V.P. Test Client about availability', ('complete', 'format_exact', 5)),
            ('Draft an email to ＭＶＰ Test Client about availability', ('complete', 'format_exact', 3)),
            ('Draft an email to MVP Test Client', ('missing_purpose', 'strict_exact', 3)),
            ('Who should I follow up with today?', ('not_draft', 'not_evaluated', 0)),
        ]:
            metadata = analyze_synthetic_transcript(text)
            self.assertEqual((metadata['extraction'], metadata['matching'], metadata['candidate_tokens']), expected)
            self.assertNotIn(text, str(metadata))
            self.assertNotIn('MVP Test Client', str(metadata))
        self.assertEqual(analyze_synthetic_transcript('Draft an email to ＭＶＰ Test Client about availability')['normalization'], 'nfkc_changed')

    def test_logger_and_formatter_drop_non_allowlisted_values_and_raw_objects(self):
        private = 'synthetic-private-name synthetic@example.com credential https://example.com/token'
        metadata = {'route': private, 'candidate_tokens': 123456789,
                    'extraction': 'complete', 'matching': 'fuzzy', 'clarification': 'fuzzy_name',
                    'transcript': private, 'name': private, 'email': private}
        with self.assertLogs('bot', level='INFO') as logs:
            log_draft_diagnostic(metadata)
        record = logs.records[0]
        self.assertNotIn(private, str(record.diagnostic))
        record.diagnostic['raw'] = private
        record.diagnostic['route'] = private
        record.args = (private,)
        record.exc_info = (RuntimeError, RuntimeError(private), None)
        record.stack_info = private
        rendered = SafeEventFormatter().format(record)
        self.assertIn('matching=fuzzy', rendered)
        self.assertNotIn(private, rendered)
        self.assertNotIn('123456789', rendered)
        self.assertNotIn('candidate_tokens=', rendered)

    def test_local_inspector_has_no_automatic_io_or_retained_raw_data(self):
        text = 'Draft an email to MVP Task Client about a synthetic showing'
        captured = []
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            metadata = inspect_synthetic_transcript_locally(text, lambda transcript, name: captured.append((transcript, name)))
        self.assertEqual(captured, [(text, 'MVP Task Client')])
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn(text, str(metadata))
