"""Offline logging tests using synthetic payloads, temporary XML, and mocked polling."""
import asyncio
import io
import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.error import Conflict

from authorization import owner_only
from crm_logging import configure_logging, log_event, SafeEventFormatter, classify_telegram_error

ENV = {'TELEGRAM_OWNER_IDS': '7', 'TELEGRAM_ALLOWED_CHAT_IDS': '7'}
PRIVATE = (
    'Private Customer private@example.com +15551234567 transcript secret-token '
    'https://api.telegram.org/bot123456:fake-token/getUpdates -100987654321 '
    '<memory>synthetic CRM</memory> EMAIL_PASSWORD=fake-password'
)


class LoggingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        limiter = patch('authorization._rejection_last_logged', {})
        limiter.start()
        self.addCleanup(limiter.stop)
        self.stream = io.StringIO()
        self.logger = logging.getLogger('bot')
        saved = (self.logger.handlers[:], self.logger.level, self.logger.propagate)
        self.logger.handlers = []
        self.addCleanup(self.restore_logger, self.logger, saved)
        for name in ('httpx', 'httpcore', 'telegram', 'openai', 'apscheduler'):
            logger = logging.getLogger(name)
            self.addCleanup(self.restore_logger, logger,
                            (logger.handlers[:], logger.level, logger.propagate))
        with patch('sys.stderr', self.stream):
            configure_logging()

    @staticmethod
    def restore_logger(logger, saved):
        logger.handlers, logger.level, logger.propagate = saved

    def test_configuration_is_idempotent_and_transports_stay_silent(self):
        configure_logging()
        configure_logging()
        self.assertEqual(len(self.logger.handlers), 1)
        self.assertEqual(self.logger.level, logging.INFO)
        self.assertFalse(self.logger.propagate)
        for name in ('httpx', 'httpcore', 'telegram', 'openai', 'apscheduler'):
            logger = logging.getLogger(name)
            self.assertIsInstance(logger.handlers[0], logging.NullHandler)
            self.assertFalse(logger.propagate)
            logging.getLogger(name + '.transport').error(PRIVATE)
        log_event('startup')
        self.assertEqual(self.stream.getvalue(), 'INFO CRM bot starting\n')
        import bot, utils
        self.assertFalse(bot.DEBUG)
        self.assertFalse(utils.DEBUG)

    def test_formatter_discards_payloads_arguments_exception_and_stack(self):
        formatter = SafeEventFormatter()
        for msg in ('request_failed', PRIVATE, {'customer': PRIVATE}):
            record = logging.LogRecord('bot', logging.ERROR, PRIVATE, 1, msg,
                                       (PRIVATE,), (RuntimeError, RuntimeError(PRIVATE), None))
            record.stack_info = PRIVATE
            record.exc_text = PRIVATE
            record.command = PRIVATE
            rendered = formatter.format(record)
            self.assertNotIn(PRIVATE, rendered)
            self.assertNotIn('private@example.com', rendered)
        log_event('command_received', PRIVATE)
        log_event(PRIVATE, PRIVATE)
        self.assertEqual(self.stream.getvalue(), 'INFO Command received\n')

    async def test_commands_log_only_static_names_after_authorization(self):
        from client_manager import ClientManager
        with tempfile.TemporaryDirectory() as directory:
            crm = ClientManager(str(Path(directory) / 'memory.xml'))

            async def callback(update, context):
                crm.add_client(name=PRIVATE)
                return 'done'

            guarded = owner_only(callback, command_name='add_client')
            event = SimpleNamespace(effective_user=SimpleNamespace(id=7),
                                    effective_chat=SimpleNamespace(id=7),
                                    message=SimpleNamespace(text='/add_client ' + PRIVATE))
            with patch.dict(os.environ, ENV, clear=True):
                self.assertEqual(await guarded(event, None), 'done')
            self.assertEqual(self.stream.getvalue(),
                             'INFO Command received: /add_client\n'
                             'INFO Command completed: /add_client\n')
            self.stream.seek(0)
            self.stream.truncate()
            with patch.dict(os.environ, {}, clear=True):
                await guarded(event, None)
            self.assertEqual(self.stream.getvalue(), 'WARNING Authorization rejected: owner_not_allowed\n')
            self.assertEqual(len(crm.list_clients()), 1)

    async def test_failed_command_has_no_completion_or_exception_details(self):
        import bot

        async def callback(update, context):
            raise RuntimeError(PRIVATE)

        guarded = owner_only(callback, command_name='get_client')
        event = SimpleNamespace(effective_user=SimpleNamespace(id=7),
                                effective_chat=SimpleNamespace(id=7))
        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaises(RuntimeError):
                await guarded(event, None)
        await bot.handle_application_error(event, SimpleNamespace(error=RuntimeError(PRIVATE)))
        self.assertEqual(self.stream.getvalue(),
                         'INFO Command received: /get_client\n'
                         'ERROR Request failed; details suppressed\n')

    def test_mocked_lifecycle_logs_start_polling_shutdown_and_sanitized_failure(self):
        import bot
        app = MagicMock()
        builder = MagicMock()
        builder.token.return_value.build.return_value = app
        with (patch('bot.initialize_runtime'), patch('bot.TOKEN', 'synthetic'),
              patch('bot.ApplicationBuilder', return_value=builder),
              patch('bot.register_automatic_daily_brief')):
            bot.main()
            self.assertEqual(self.stream.getvalue(),
                             'INFO CRM bot starting\nINFO Polling starting\nINFO CRM bot stopped\n')
            self.stream.seek(0)
            self.stream.truncate()
            app.run_polling.side_effect = RuntimeError(PRIVATE)
            with self.assertRaises(RuntimeError):
                bot.main()
        self.assertEqual(self.stream.getvalue(),
                         'INFO CRM bot starting\nINFO Polling starting\n'
                         'ERROR Startup or polling failed; details suppressed\n'
                         'ERROR Lifecycle failure stage=polling_before_init exception=RuntimeError\n'
                         'INFO CRM bot stopped\n')

    def test_failure_after_initialization_logs_only_allowlisted_labels(self):
        import bot

        unknown_error = type('SensitiveSyntheticClassName', (Exception,), {})
        app = MagicMock()
        builder = MagicMock()
        builder.token.return_value.build.return_value = app

        def run_polling():
            callback = builder.token.return_value.post_init.call_args.args[0]
            asyncio.run(callback(app))
            try:
                raise Conflict(PRIVATE)
            except Conflict:
                raise unknown_error(PRIVATE)

        app.run_polling.side_effect = run_polling
        with (patch('bot.initialize_runtime'), patch('bot.TOKEN', 'synthetic'),
              patch('bot.ApplicationBuilder', return_value=builder),
              patch('bot.register_automatic_daily_brief')):
            with self.assertRaises(unknown_error):
                bot.main()
        self.assertEqual(
            self.stream.getvalue(),
            'INFO CRM bot starting\nINFO Polling starting\n'
            'INFO Telegram initialization succeeded\n'
            'ERROR Startup or polling failed; details suppressed\n'
            'ERROR Lifecycle failure stage=polling_after_init exception=Other context=Conflict\n'
            'INFO CRM bot stopped\n',
        )

    async def test_rejection_categories_are_safe_and_do_not_invoke_callback(self):
        callback = AsyncMock()
        guarded = owner_only(callback, command_name='tour')
        events = [
            (SimpleNamespace(effective_user=SimpleNamespace(id=8),
                             effective_chat=SimpleNamespace(id=7)), 'owner_not_allowed'),
            (SimpleNamespace(effective_user=SimpleNamespace(id=7),
                             effective_chat=SimpleNamespace(id=8)), 'chat_not_allowed'),
            (SimpleNamespace(effective_user=None, effective_chat=None), 'missing_identity'),
        ]
        with patch.dict(os.environ, ENV, clear=True):
            for event, category in events:
                self.stream.seek(0)
                self.stream.truncate()
                event.message = SimpleNamespace(text=PRIVATE, reply_text=AsyncMock())
                await guarded(event, None)
                self.assertEqual(self.stream.getvalue(),
                                 'WARNING Authorization rejected: ' + category + '\n')
                event.message.reply_text.assert_not_awaited()
        callback.assert_not_awaited()

    async def test_rejection_rate_limit_is_global_per_category_and_expires(self):
        import authorization
        callback = AsyncMock()
        guarded = owner_only(callback)
        with (patch.dict(os.environ, ENV, clear=True),
              patch('authorization.monotonic', side_effect=[0, 1, 59.9, 60])):
            for user in [8, 9, 10, 11]:
                event = SimpleNamespace(effective_user=SimpleNamespace(id=user),
                                        effective_chat=SimpleNamespace(id=7))
                await guarded(event, None)
        self.assertEqual(self.stream.getvalue(),
                         'WARNING Authorization rejected: owner_not_allowed\n' * 2)
        self.assertEqual(set(authorization._rejection_last_logged), {'owner_not_allowed'})
        callback.assert_not_awaited()

    async def test_malformed_allowlists_remain_denied_without_values_in_logs(self):
        callback = AsyncMock()
        guarded = owner_only(callback)
        event = SimpleNamespace(effective_user=SimpleNamespace(id=7),
                                effective_chat=SimpleNamespace(id=7))
        with patch.dict(os.environ, {**ENV, 'TELEGRAM_OWNER_IDS': PRIVATE}, clear=True):
            await guarded(event, None)
        with patch.dict(os.environ, {**ENV, 'TELEGRAM_ALLOWED_CHAT_IDS': PRIVATE}, clear=True):
            await guarded(event, None)
        self.assertEqual(self.stream.getvalue(),
                         'WARNING Authorization rejected: owner_not_allowed\n'
                         'WARNING Authorization rejected: chat_not_allowed\n')
        callback.assert_not_awaited()

    async def test_telegram_error_categories_never_format_exception_or_update(self):
        import bot
        from telegram.error import InvalidToken, Conflict, NetworkError, TimedOut, BadRequest, Forbidden

        class UnprintableNetworkError(NetworkError):
            def __str__(self):
                raise AssertionError('Exception text must not be accessed')

        class UnprintableUpdate:
            def __repr__(self):
                raise AssertionError('Update must not be formatted')

        for error, category in [(InvalidToken(PRIVATE), 'authentication'),
                                (Conflict(PRIVATE), 'polling_conflict'),
                                (NetworkError(PRIVATE), 'network'),
                                (TimedOut(PRIVATE), 'network'),
                                (UnprintableNetworkError(PRIVATE), 'network'),
                                (BadRequest(PRIVATE), 'other'),
                                (Forbidden(PRIVATE), 'other')]:
            with self.subTest(category=category):
                self.stream.seek(0)
                self.stream.truncate()
                self.assertEqual(classify_telegram_error(error), category)
                await bot.handle_application_error(UnprintableUpdate(), SimpleNamespace(error=error))
                self.assertEqual(self.stream.getvalue(), 'ERROR Telegram error: ' + category + '\n')

    async def test_initialization_event_is_registered_and_only_emitted_by_callback(self):
        import bot
        app = MagicMock()
        builder = MagicMock()
        builder.token.return_value.build.return_value = app
        with (patch('bot.initialize_runtime'), patch('bot.TOKEN', 'synthetic'),
              patch('bot.ApplicationBuilder', return_value=builder),
              patch('bot.register_automatic_daily_brief')):
            bot.main()
        builder.token.return_value.post_init.assert_called_once()
        self.assertNotIn('Telegram initialization succeeded', self.stream.getvalue())
        self.stream.seek(0)
        self.stream.truncate()
        # Simulate PTB's callback after successful initialize; no Telegram methods invoked.
        callback = builder.token.return_value.post_init.call_args.args[0]
        await callback(app)
        self.assertEqual(self.stream.getvalue(), 'INFO Telegram initialization succeeded\n')
        app.initialize.assert_not_called()
        app.bot.get_me.assert_not_called()

    def test_bootstrap_failures_are_classified_without_raw_details(self):
        import bot
        from telegram.error import InvalidToken, Conflict, NetworkError, BadRequest
        for error, category in [(InvalidToken(PRIVATE), 'authentication'),
                                (Conflict(PRIVATE), 'polling_conflict'),
                                (NetworkError(PRIVATE), 'network'),
                                (BadRequest(PRIVATE), 'other')]:
            self.stream.seek(0)
            self.stream.truncate()
            builder = MagicMock()
            builder.token.return_value.build.side_effect = error
            with (patch('bot.initialize_runtime'), patch('bot.TOKEN', 'synthetic'),
                  patch('bot.ApplicationBuilder', return_value=builder)):
                with self.assertRaises(type(error)):
                    bot.main()
            self.assertEqual(self.stream.getvalue(),
                             'INFO CRM bot starting\nERROR Telegram error: ' + category +
                             '\nERROR Lifecycle failure stage=runtime_setup exception=' +
                             type(error).__name__ + '\nINFO CRM bot stopped\n')
