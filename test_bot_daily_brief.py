import sys
import types
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


telegram = types.ModuleType("telegram")
telegram.Update = object

telegram_ext = types.ModuleType("telegram.ext")
for name in ["ApplicationBuilder", "CommandHandler", "MessageHandler", "ContextTypes", "filters"]:
    setattr(telegram_ext, name, object())

openai = types.ModuleType("openai")


class OpenAI:
    def __init__(self, *args, **kwargs):
        pass


openai.OpenAI = OpenAI

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
    def __init__(self, user_id=123):
        self.message = FakeMessage("/daily_brief")
        self.effective_user = types.SimpleNamespace(id=user_id)


class BotDailyBriefTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        allowlist = patch.dict("os.environ", {"TELEGRAM_ALLOWED_CHAT_IDS": "123"})
        allowlist.start()
        self.addCleanup(allowlist.stop)
        bot.pending_email_drafts.clear()
        bot._daily_brief_last_sent.clear()

    async def test_command_reads_crm_and_current_users_draft_without_actions(self):
        update = FakeUpdate(user_id=123)
        client = {"name": "Amy Wang", "next_followup": "2026-07-20"}
        bot.pending_email_drafts[123] = {
            "client_name": "Lisa Chen",
            "draft": {"subject": "Happy Birthday", "body": "Private body"},
        }
        bot.pending_email_drafts[999] = {
            "client_name": "Other User Client",
            "draft": {"subject": "Other", "body": "Other private body"},
        }
        brief = {
            "birthdays_today": [],
            "followups_due_today": [],
            "overdue_followups": [],
            "pending_drafts": [
                {"client_name": "Lisa Chen", "purpose": "birthday", "subject": "Happy Birthday"}
            ],
            "suggested_action": {
                "kind": "pending_draft",
                "client_name": "Lisa Chen",
                "purpose": "birthday",
            },
        }

        with (
            patch("bot.crm") as crm,
            patch("bot.build_daily_brief", return_value=brief) as build,
            patch("bot.generate_birthday_email") as generate,
            patch("bot.send_email") as send,
        ):
            crm.list_clients.return_value = [client]
            await bot.daily_brief_command(update, None)

        crm.list_clients.assert_called_once_with()
        crm.update_client.assert_not_called()
        crm.delete_client.assert_not_called()
        generate.assert_not_called()
        send.assert_not_called()
        build.assert_called_once_with(
            [client],
            [
                {
                    "purpose": "birthday",
                    "client_name": "Lisa Chen",
                    "subject": "Happy Birthday",
                }
            ],
        )
        self.assertNotIn("Other User Client", update.message.replies[0])
        self.assertEqual(len(bot.pending_email_drafts), 2)

    async def test_agent_name_is_used_and_missing_name_has_safe_greeting(self):
        brief = {
            "birthdays_today": [],
            "followups_due_today": [],
            "overdue_followups": [],
            "pending_drafts": [],
            "suggested_action": None,
        }

        self.assertEqual(
            bot.format_daily_brief(brief, "Test Agent"),
            "Good morning, Test Agent.\n\nYou have no urgent CRM tasks today.",
        )
        self.assertEqual(
            bot.format_daily_brief(brief, None),
            "Good morning.\n\nYou have no urgent CRM tasks today.",
        )

    async def test_help_includes_daily_brief(self):
        update = FakeUpdate()
        await bot.help_command(update, None)
        self.assertIn("/daily_brief", update.message.replies[0])

    async def test_daily_brief_command_is_registered(self):
        app = MagicMock()
        builder = MagicMock()
        builder.token.return_value.build.return_value = app
        command_handler = MagicMock(side_effect=lambda name, handler: ("command", name, handler))
        message_handler = MagicMock(side_effect=lambda *args: ("message", args))
        fake_filters = MagicMock()

        with (
            patch("bot.initialize_runtime"),
            patch("bot.TOKEN", "test-token"),
            patch("bot.ApplicationBuilder", return_value=builder),
            patch("bot.CommandHandler", command_handler),
            patch("bot.MessageHandler", message_handler),
            patch("bot.filters", fake_filters),
        ):
            bot.main()

        registered_commands = [call.args[0] for call in command_handler.call_args_list]
        self.assertIn("daily_brief", registered_commands)

    async def test_valid_schedule_is_registered_for_configured_chat(self):
        app = MagicMock()
        env = {
            "DAILY_BRIEF_ENABLED": "true",
            "TELEGRAM_ALLOWED_CHAT_IDS": "123",
            "DAILY_BRIEF_CHAT_ID": "123",
            "DAILY_BRIEF_TIME": "08:00",
            "DAILY_BRIEF_TIMEZONE": "America/New_York",
        }

        with patch.dict("os.environ", env, clear=True):
            registered = bot.register_automatic_daily_brief(app)

        self.assertTrue(registered)
        kwargs = app.job_queue.run_daily.call_args.kwargs
        self.assertIs(app.job_queue.run_daily.call_args.args[0], bot.automatic_daily_brief_job)
        self.assertEqual(kwargs["data"]["chat_id"], 123)
        self.assertEqual(kwargs["data"]["timezone_name"], "America/New_York")
        self.assertEqual(kwargs["time"].hour, 8)
        self.assertEqual(kwargs["time"].minute, 0)

    async def test_invalid_or_disabled_schedule_does_not_register(self):
        app = MagicMock()

        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(bot.register_automatic_daily_brief(app))

        with patch.dict(
            "os.environ",
            {
                "DAILY_BRIEF_ENABLED": "true",
                "DAILY_BRIEF_CHAT_ID": "not-a-number",
            },
            clear=True,
        ):
            self.assertFalse(bot.register_automatic_daily_brief(app))

        app.job_queue.run_daily.assert_not_called()

    async def test_automatic_job_sends_once_per_local_day(self):
        context = types.SimpleNamespace(
            job=types.SimpleNamespace(
                data={
                    "chat_id": 123,
                    "timezone_name": "America/New_York",
                }
            ),
            bot=types.SimpleNamespace(send_message=AsyncMock()),
        )

        with (
            patch("bot.application_today", return_value=date(2026, 11, 14)),
            patch("bot.build_daily_brief_message", return_value="Good morning, Test Agent.") as build,
        ):
            await bot.automatic_daily_brief_job(context)
            await bot.automatic_daily_brief_job(context)

        context.bot.send_message.assert_awaited_once_with(
            chat_id=123,
            text="Good morning, Test Agent.",
        )
        build.assert_called_once()
        self.assertEqual(bot._daily_brief_last_sent[123], date(2026, 11, 14))

    async def test_failed_automatic_send_is_not_marked_sent(self):
        context = types.SimpleNamespace(
            job=types.SimpleNamespace(
                data={
                    "chat_id": 123,
                    "timezone_name": "America/New_York",
                }
            ),
            bot=types.SimpleNamespace(
                send_message=AsyncMock(side_effect=RuntimeError("network failure"))
            ),
        )

        with (
            patch("bot.application_today", return_value=date(2026, 11, 14)),
            patch("bot.build_daily_brief_message", return_value="Brief"),
            self.assertRaises(RuntimeError),
        ):
            await bot.automatic_daily_brief_job(context)

        self.assertNotIn(123, bot._daily_brief_last_sent)


if __name__ == "__main__":
    unittest.main()
