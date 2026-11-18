import sys
import types
import unittest
from unittest.mock import MagicMock, patch


telegram = types.ModuleType("telegram")
telegram.Update = object
telegram_ext = types.ModuleType("telegram.ext")
for name in ["ApplicationBuilder", "CommandHandler", "MessageHandler", "ContextTypes", "filters"]:
    setattr(telegram_ext, name, object())
openai = types.ModuleType("openai")
openai.OpenAI = MagicMock
sys.modules.setdefault("telegram", telegram)
sys.modules.setdefault("telegram.ext", telegram_ext)
sys.modules.setdefault("openai", openai)

import bot


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, text="", user_id=123):
        self.message = FakeMessage(text)
        self.effective_user = types.SimpleNamespace(id=user_id)


class BotSafeClientActionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.pending_client_actions.clear()
        self.client = {
            "name": "Alex Chen",
            "status": "active",
            "email": "alex@example.com",
            "phone": "555-0100",
        }

    async def test_voice_delete_creates_preview_without_deleting(self):
        update = FakeUpdate(user_id=7)
        fake_crm = MagicMock()
        fake_crm.get_client.return_value = None
        fake_crm.list_clients.return_value = [self.client]
        with patch("bot.crm", fake_crm):
            handled = await bot.route_voice_intent(
                update,
                {"intent": "delete_client", "client_name": "Alex Chan", "fields": {}},
            )

        self.assertTrue(handled)
        fake_crm.delete_client.assert_not_called()
        self.assertEqual(
            bot.pending_client_actions[7]["client_name"],
            "Alex Chen",
        )
        self.assertIn("No client has been deleted yet", update.message.replies[0])

    async def test_confirm_deletes_only_pending_resolved_client(self):
        bot.pending_client_actions[7] = {
            "kind": "delete_client",
            "client_name": "Alex Chen",
        }
        update = FakeUpdate("/confirm_delete_client", user_id=7)
        fake_crm = MagicMock()
        fake_crm.get_client.return_value = self.client
        fake_crm.delete_client.return_value = True
        with patch("bot.crm", fake_crm):
            await bot.confirm_delete_client_command(update, None)

        fake_crm.delete_client.assert_called_once_with("Alex Chen")
        self.assertNotIn(7, bot.pending_client_actions)

    async def test_cancel_never_deletes(self):
        bot.pending_client_actions[7] = {
            "kind": "delete_client",
            "client_name": "Alex Chen",
        }
        update = FakeUpdate("/cancel_delete_client", user_id=7)
        fake_crm = MagicMock()
        with patch("bot.crm", fake_crm):
            await bot.cancel_delete_client_command(update, None)

        fake_crm.delete_client.assert_not_called()
        self.assertNotIn(7, bot.pending_client_actions)

    async def test_likely_voice_update_waits_for_confirmation(self):
        update = FakeUpdate(user_id=7)
        fake_crm = MagicMock()
        fake_crm.get_client.return_value = None
        fake_crm.list_clients.return_value = [self.client]
        with patch("bot.crm", fake_crm):
            await bot.route_voice_intent(
                update,
                {
                    "intent": "update_client",
                    "client_name": "Alex Chan",
                    "fields": {"status": "touring"},
                },
            )

        fake_crm.update_client_from_text.assert_not_called()
        self.assertEqual(bot.pending_client_actions[7]["kind"], "update_client")
        self.assertIn("No client information has been changed yet", update.message.replies[0])

    async def test_ambiguous_delete_does_not_create_pending_action(self):
        update = FakeUpdate(user_id=7)
        fake_crm = MagicMock()
        fake_crm.get_client.return_value = None
        fake_crm.list_clients.return_value = [
            self.client,
            {**self.client, "name": "Alex Chon"},
        ]
        with patch("bot.crm", fake_crm):
            await bot.prepare_delete_client(update, "Alex Chan")

        self.assertNotIn(7, bot.pending_client_actions)
        fake_crm.delete_client.assert_not_called()
        self.assertIn("multiple possible matches", update.message.replies[0])

    def test_deterministic_remove_parser(self):
        self.assertEqual(
            bot.parse_voice_delete_intent("remove Alex Chen")["client_name"],
            "Alex Chen",
        )
