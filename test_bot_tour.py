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
        self.effective_chat = types.SimpleNamespace(id=user_id)


class BotTourTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.pending_tours.clear()

    async def test_tour_starts_for_current_user(self):
        update = FakeUpdate("/tour", user_id=7)
        await bot.tour_command(update, None)
        self.assertIn(7, bot.pending_tours)
        self.assertIn("five things", update.message.replies[0])

    async def test_number_reply_is_user_scoped(self):
        bot.pending_tours.add(7)
        current_user = FakeUpdate("2", user_id=7)
        other_user = FakeUpdate("2", user_id=8)

        self.assertTrue(await bot.handle_tour_reply(current_user, "2"))
        self.assertFalse(await bot.handle_tour_reply(other_user, "2"))
        self.assertIn("Find and update clients", current_user.message.replies[0])

    async def test_invalid_reply_stays_in_tour_without_running_other_actions(self):
        bot.pending_tours.add(7)
        update = FakeUpdate("hello", user_id=7)
        with patch("bot.handle_memory_commands") as memory:
            await bot.handle_message(update, None)
        memory.assert_not_called()
        self.assertIn("number from 1 to 5", update.message.replies[0])

    async def test_cancel_only_clears_current_users_tour(self):
        bot.pending_tours.update({7, 8})
        update = FakeUpdate("/cancel_tour", user_id=7)
        await bot.cancel_tour_command(update, None)
        self.assertNotIn(7, bot.pending_tours)
        self.assertIn(8, bot.pending_tours)

    async def test_tour_commands_are_registered(self):
        app = MagicMock()
        builder = MagicMock()
        builder.token.return_value.build.return_value = app
        command_handler = MagicMock(side_effect=lambda name, handler: (name, handler))
        with (
            patch("bot.initialize_runtime"),
            patch("bot.TOKEN", "token"),
            patch("bot.ApplicationBuilder", return_value=builder),
            patch("bot.CommandHandler", command_handler),
            patch("bot.MessageHandler", MagicMock()),
            patch("bot.filters", MagicMock()),
        ):
            bot.main()
        commands = [call.args[0] for call in command_handler.call_args_list]
        self.assertIn("tour", commands)
        self.assertIn("cancel_tour", commands)


if __name__ == "__main__":
    unittest.main()
