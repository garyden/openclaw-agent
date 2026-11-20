"""Offline environment isolation checks using synthetic XML and mocked SMTP."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_config import (
    ConfigurationError,
    DEV_MEMORY_PATH,
    load_settings,
    resolve_memory_path,
)
from client_manager import ClientManager
from email_sender import send_email
from memory_manager import append_fact, load_memory


class EnvironmentIsolationTest(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.directory).resolve()

    def test_default_paths(self):
        self.assertEqual(resolve_memory_path({}), DEV_MEMORY_PATH)
        self.assertEqual(resolve_memory_path({'APP_ENV': 'development'}), DEV_MEMORY_PATH)
        testing = {'APP_ENV': 'testing'}
        path = resolve_memory_path(testing)
        self.assertTrue(path.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertEqual(path, resolve_memory_path(testing))
        self.assertNotEqual(path, DEV_MEMORY_PATH)

    def test_development_default_rejects_aliases_to_other_stores(self):
        target = self.root / 'external.xml'
        target.write_text('<memory/>')
        alias = self.root / 'development.xml'
        with patch('app_config.DEV_MEMORY_PATH', alias):
            alias.symlink_to(target)
            with self.assertRaisesRegex(ConfigurationError, 'symlinks'):
                resolve_memory_path({})
            alias.unlink()
            os.link(target, alias)
            with self.assertRaisesRegex(ConfigurationError, 'hard links'):
                resolve_memory_path({})

    def test_invalid_environment(self):
        for value in ('', 'staging', 'Production'):
            with self.subTest(value=value), self.assertRaisesRegex(ConfigurationError, 'APP_ENV'):
                resolve_memory_path({'APP_ENV': value})

    def test_production_rejects_missing_relative_and_invalid_xml(self):
        missing = self.root / 'missing.xml'
        malformed = self.root / 'malformed.xml'
        malformed.write_text('<memory>')
        wrong_root = self.root / 'wrong.xml'
        wrong_root.write_text('<other/>')
        for path in ('', 'relative.xml', missing, malformed, wrong_root, self.root):
            with self.subTest(path=path), self.assertRaises(ConfigurationError):
                resolve_memory_path({'APP_ENV': 'production', 'CRM_MEMORY_PATH': str(path)})
        self.assertFalse(missing.exists())
        self.assertEqual(malformed.read_text(), '<memory>')
        self.assertEqual(wrong_root.read_text(), '<other/>')

    def test_production_rejects_git_checkout_worktree_and_symlink_alias(self):
        for marker_is_file in (False, True):
            checkout = self.root / str(marker_is_file)
            checkout.mkdir()
            marker = checkout / '.git'
            if marker_is_file:
                marker.write_text('gitdir: synthetic\n')
            else:
                marker.mkdir()
            path = checkout / 'memory.xml'
            path.write_text('<memory/>')
            alias = self.root / f'alias-{marker_is_file}.xml'
            alias.symlink_to(path)
            for candidate in (path, alias):
                with self.subTest(candidate=candidate), self.assertRaisesRegex(
                    ConfigurationError, 'outside Git checkouts'
                ):
                    resolve_memory_path({'APP_ENV': 'production', 'CRM_MEMORY_PATH': str(candidate)})

    def test_production_rejects_inaccessible_file_or_directory(self):
        path = self.root / 'memory.xml'
        path.write_text('<memory/>')
        env = {'APP_ENV': 'production', 'CRM_MEMORY_PATH': str(path)}
        for denied in (path, self.root):
            with patch('app_config.os.access', side_effect=lambda target, mode: target != denied):
                with self.assertRaisesRegex(ConfigurationError, 'readable and writable'):
                    resolve_memory_path(env)

    def test_production_startup_and_reads_do_not_modify_existing_xml(self):
        path = self.root / 'memory.xml'
        path.write_text('<memory/>')
        env = {'APP_ENV': 'production', 'CRM_MEMORY_PATH': str(path)}
        with patch.dict(os.environ, env, clear=True):
            crm = ClientManager()
            self.assertEqual(crm.list_clients(), [])
            self.assertIn('<facts>', load_memory())
            self.assertEqual(path.read_text(), '<memory/>')
            crm.add_client('Synthetic Client')
            append_fact('Synthetic & escaped')
            self.assertIn('Synthetic &amp; escaped', load_memory())
            self.assertEqual(crm.list_clients()[0]['name'], 'Synthetic Client')
            path.unlink()
            with self.assertRaises(ConfigurationError):
                crm.add_client('Other Client')
            with self.assertRaises(ConfigurationError):
                append_fact('Other fact')
            self.assertFalse(path.exists())

    def test_production_cannot_override_the_configured_path(self):
        path = self.root / 'memory.xml'
        path.write_text('<memory/>')
        other = self.root / 'other.xml'
        with patch.dict(os.environ, {'APP_ENV': 'production', 'CRM_MEMORY_PATH': str(path)}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, 'must use CRM_MEMORY_PATH'):
                ClientManager(other)
        self.assertFalse(other.exists())

    def test_missing_production_store_blocks_telegram_startup(self):
        import bot

        missing = self.root / 'missing.xml'
        env = {
            'APP_ENV': 'production',
            'CRM_MEMORY_PATH': str(missing),
            'TELEGRAM_BOT_TOKEN': 'synthetic',
            'TELEGRAM_OWNER_IDS': '7',
            'TELEGRAM_ALLOWED_CHAT_IDS': '7',
        }
        with patch.dict(os.environ, env, clear=True), patch('bot.ApplicationBuilder') as builder:
            with self.assertRaisesRegex(ConfigurationError, 'existing accessible CRM XML'):
                bot.main()
            builder.assert_not_called()
        self.assertFalse(missing.exists())

    def test_both_components_share_only_the_selected_environment_store(self):
        prod = self.root / 'prod.xml'
        prod.write_text('<memory/>')
        paths = {'development': self.root / 'dev.xml', 'testing': self.root / 'test.xml', 'production': prod}
        for mode, path in paths.items():
            with patch.dict(os.environ, {'APP_ENV': mode, 'CRM_MEMORY_PATH': str(path)}, clear=True):
                manager = ClientManager()
                self.assertEqual(Path(manager.xml_path), path)
                self.assertEqual(manager.list_clients(), [])
                manager.add_client(mode)
                append_fact(f'{mode} fact')
                self.assertIn(f'{mode} fact', load_memory())
                self.assertEqual([client['name'] for client in manager.list_clients()], [mode])
        for mode, path in paths.items():
            content = path.read_text()
            for other in paths.keys() - {mode}:
                self.assertNotIn(f'{other} fact', content)
        for mode in ('development', 'testing'):
            self.assertNotEqual(resolve_memory_path({'APP_ENV': mode}), prod)

    def test_testing_rejects_checkout_paths(self):
        with self.assertRaisesRegex(ConfigurationError, 'temporary directory'):
            resolve_memory_path({'APP_ENV': 'testing', 'CRM_MEMORY_PATH': str(DEV_MEMORY_PATH)})

    def test_production_ignores_dotenv_and_requires_service_credentials(self):
        with patch.dict(os.environ, {'APP_ENV': 'production'}, clear=True):
            with patch('dotenv.dotenv_values') as dotenv:
                with self.assertRaisesRegex(ConfigurationError, 'TELEGRAM_BOT_TOKEN'):
                    load_settings()
                dotenv.assert_not_called()

    def test_dotenv_cannot_select_production(self):
        path = self.root / '.env.development'
        path.write_text('APP_ENV=production\nTELEGRAM_BOT_TOKEN=synthetic\n')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, 'Select APP_ENV'):
                load_settings(path)
            self.assertNotIn('TELEGRAM_BOT_TOKEN', os.environ)

    def test_nonproduction_email_never_opens_smtp(self):
        for mode in ('development', 'testing'):
            with patch.dict(os.environ, {'APP_ENV': mode}, clear=True):
                with patch('email_sender.smtplib.SMTP') as smtp:
                    with self.assertRaisesRegex(ValueError, 'disabled'):
                        send_email('client@example.com', 'Synthetic subject', 'Synthetic body')
                    smtp.assert_not_called()
