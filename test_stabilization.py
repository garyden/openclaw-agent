"""No production CRM access or network; only synthetic data and temporary XML."""
import asyncio
import contextlib
import importlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app_config import ConfigurationError, load_settings, read_settings
from authorization import authorized, owner_only

ENV = {'TELEGRAM_BOT_TOKEN': '123456:synthetic-token',
       'TELEGRAM_OWNER_IDS': '7', 'TELEGRAM_ALLOWED_CHAT_IDS': '7,-100'}


def update(user=7, chat=7):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user, is_bot=False),
                           effective_chat=SimpleNamespace(id=chat))


class ConfigurationTest(unittest.TestCase):
    def test_deny_missing_or_malformed_allowlists_without_values(self):
        for change in ({'TELEGRAM_OWNER_IDS': ''}, {'TELEGRAM_ALLOWED_CHAT_IDS': ''},
                       {'TELEGRAM_OWNER_IDS': 'private-value'},
                       {'TELEGRAM_OWNER_IDS': '-7'}, {'TELEGRAM_ALLOWED_CHAT_IDS': '0'},
                       {'TELEGRAM_BOT_TOKEN': ''}):
            with self.assertRaises(ConfigurationError) as caught:
                read_settings({**ENV, **change})
            self.assertNotIn('private-value', str(caught.exception))

    def test_optional_services_and_secret_repr(self):
        settings = read_settings(ENV)
        self.assertNotIn(ENV['TELEGRAM_BOT_TOKEN'], repr(settings))
        for extra in ({'EMAIL_HOST': 'secret-host'},
                      {'EMAIL_HOST': 'h', 'EMAIL_PORT': '99999',
                       'EMAIL_USER': 'u', 'EMAIL_PASSWORD': 'secret-password'}):
            with self.assertRaises(ConfigurationError) as caught:
                read_settings({**ENV, **extra})
            self.assertNotIn('secret', str(caught.exception))

    def test_daily_brief_must_target_allowed_chat_and_valid_schedule(self):
        brief = {'DAILY_BRIEF_ENABLED': 'true', 'DAILY_BRIEF_CHAT_ID': '-100'}
        read_settings({**ENV, **brief})
        for extra in ({'DAILY_BRIEF_CHAT_ID': '8'}, {'DAILY_BRIEF_TIME': '25:00'},
                      {'DAILY_BRIEF_TIMEZONE': 'invalid'}, {'DAILY_BRIEF_ENABLED': 'typo'}):
            with self.assertRaises(ConfigurationError):
                read_settings({**ENV, **brief, **extra})

    def test_dotenv_is_explicit_and_preserves_process_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('\n'.join(f'{k}={v}' for k, v in ENV.items()) +
                            '\nOPENAI_API_KEY=${DO_NOT_EXPAND}\n')
            with patch.dict(os.environ, {'TELEGRAM_OWNER_IDS': '9'}, clear=True):
                settings = load_settings(path)
                self.assertEqual(settings.owner_ids, frozenset({9}))
                self.assertEqual(os.environ['OPENAI_API_KEY'], '${DO_NOT_EXPAND}')


class AuthorizationTest(unittest.IsolatedAsyncioTestCase):
    async def test_both_allowlists_required_and_silent_denial(self):
        callback = AsyncMock()
        guarded = owner_only(callback)
        with patch.dict(os.environ, ENV, clear=True):
            for event in (update(8, 7), update(7, 8), update(None, 7),
                          SimpleNamespace(), update('7', 7)):
                await guarded(event, None)
            callback.assert_not_awaited()
            await guarded(update(), None)
            callback.assert_awaited_once()
        for env in ({}, {**ENV, 'TELEGRAM_OWNER_IDS': 'bad'},
                    {**ENV, 'TELEGRAM_ALLOWED_CHAT_IDS': ''}):
            with patch.dict(os.environ, env, clear=True):
                self.assertFalse(authorized(update()))

    async def test_every_registered_handler_is_guarded(self):
        import bot
        app = MagicMock()
        builder = MagicMock()
        builder.token.return_value.build.return_value = app
        with (patch('bot.initialize_runtime'), patch('bot.TOKEN', 'synthetic'),
              patch('bot.ApplicationBuilder', return_value=builder),
              patch('bot.register_automatic_daily_brief'),
              patch.dict(os.environ, {}, clear=True)):
            bot.main()
            handlers = [call.args[0] for call in app.add_handler.call_args_list]
            self.assertGreater(len(handlers), 20)
            for handler in handlers:
                self.assertTrue(hasattr(handler.callback, '__wrapped__'))
                await handler.callback(update(99, 99), None)
            app.run_polling.assert_called_once()  # Mock only.

    async def test_scheduler_rechecks_authorization_before_reading_crm(self):
        import bot
        context = SimpleNamespace(job=SimpleNamespace(data={
            'chat_id': 99, 'timezone_name': 'America/New_York'}),
            bot=SimpleNamespace(send_message=AsyncMock()))
        with (patch.dict(os.environ, ENV, clear=True),
              patch('bot.build_daily_brief_message') as build):
            await bot.automatic_daily_brief_job(context)
            build.assert_not_called()
            context.bot.send_message.assert_not_awaited()


class StartupTest(unittest.TestCase):
    def test_import_has_no_crm_or_provider_initialization(self):
        # A fresh interpreter uses real installed libraries, not legacy test stubs.
        script = '''
import socket
from unittest.mock import patch
import client_manager, openai, smtplib, dotenv
with patch.object(dotenv, "load_dotenv", side_effect=AssertionError("dotenv loaded during import")), \
     patch.object(client_manager.ClientManager, '__init__', side_effect=AssertionError('CRM initialized')), \\
     patch.object(openai, 'OpenAI', side_effect=AssertionError('OpenAI initialized')), \\
     patch.object(smtplib, 'SMTP', side_effect=AssertionError('SMTP initialized')), \\
     patch.object(socket.socket, 'connect', side_effect=AssertionError('network')):
 import bot, ai_parser, email_generator, email_sender
 assert bot.crm is None and bot.openai_client is None and ai_parser.client is None
'''
        env = {k: v for k, v in os.environ.items() if k not in {
            'OPENAI_API_KEY', 'TELEGRAM_BOT_TOKEN'}}
        result = subprocess.run([sys.executable, '-B', '-c', script],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_only_uses_injected_temporary_crm(self):
        import bot
        from client_manager import ClientManager
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'memory.xml'
            with (patch('bot.load_settings', return_value=read_settings(ENV)),
                  patch('bot.ClientManager', side_effect=lambda: ClientManager(str(path))),
                  patch.object(bot, 'crm'), patch.object(bot, 'TOKEN')):
                bot.initialize_runtime()
                self.assertEqual(bot.crm.xml_path, str(path))
                self.assertEqual(bot.crm.list_clients(), [])

    def test_invalid_startup_does_not_initialize_crm_or_telegram(self):
        import bot
        with (patch('bot.load_settings', side_effect=ConfigurationError('missing config')),
              patch('bot.ClientManager') as crm,
              patch('bot.ApplicationBuilder') as builder):
            with self.assertRaises(ConfigurationError):
                bot.main()
            crm.assert_not_called()
            builder.assert_not_called()

    def test_clients_initialize_lazily(self):
        import bot, ai_parser
        with (patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic'}, clear=True),
              patch.object(bot, 'openai_client', None),
              patch.object(ai_parser, 'client', None),
              patch('bot.OpenAI') as bot_client, patch('ai_parser.OpenAI') as parser_client):
            bot.get_openai_client()
            bot.get_openai_client()
            ai_parser.get_client()
            ai_parser.get_client()
            bot_client.assert_called_once()
            parser_client.assert_called_once()

    def test_debug_logs_drop_payloads_and_error_logs_drop_exceptions(self):
        import bot, utils
        output = io.StringIO()
        with patch.object(utils, 'DEBUG', True), contextlib.redirect_stdout(output):
            utils.debug('Event received', 'private-customer', 'secret-token')
        self.assertNotIn('private-customer', output.getvalue())
        self.assertNotIn('secret-token', output.getvalue())
        with self.assertLogs('bot', level='ERROR') as logs:
            asyncio.run(bot.handle_application_error(None,
                SimpleNamespace(error=RuntimeError('secret-token'))))
        self.assertNotIn('secret-token', '\n'.join(logs.output))
