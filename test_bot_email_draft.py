import sys
import types
import unittest
from unittest.mock import patch


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

from bot import (
    agent_profile,
    cancel_email_command,
    confirm_send_email_command,
    extract_voice_intent_with_openai,
    generate_birthday_email_command,
    get_client_command,
    handle_voice_message,
    help_command,
    pending_email_drafts,
    revise_email_draft_with_openai,
    route_voice_intent,
    send_last_email_command,
    start,
)


class FakeMessage:
    def __init__(self, text="", voice=None):
        self.text = text
        self.voice = voice
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, text="", user_id=123, voice=None):
        self.message = FakeMessage(text, voice)
        self.effective_user = types.SimpleNamespace(id=user_id)


class FakeTelegramFile:
    async def download_to_drive(self, file_path):
        self.file_path = file_path


class FakeBot:
    def __init__(self):
        self.telegram_file = FakeTelegramFile()

    async def get_file(self, file_id):
        self.file_id = file_id
        return self.telegram_file


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()


class BotEmailDraftTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pending_email_drafts.clear()

    async def test_start_explains_agent_capabilities(self):
        update = FakeUpdate("/start")

        await start(update, None)

        self.assertEqual(len(update.message.replies), 1)
        self.assertIn("real estate copilot", update.message.replies[0])
        self.assertIn("manage clients", update.message.replies[0])
        self.assertIn("draft birthday emails", update.message.replies[0])
        self.assertIn("/help", update.message.replies[0])

    async def test_help_lists_commands_and_voice_examples(self):
        update = FakeUpdate("/help")

        await help_command(update, None)

        self.assertEqual(len(update.message.replies), 1)
        reply = update.message.replies[0]
        self.assertIn("/add_client name=Mary Lee", reply)
        self.assertIn("/list_clients", reply)
        self.assertIn("/daily_brief", reply)
        self.assertIn("/get_client Mary Lee", reply)
        self.assertIn("Voice: update client Mary Lee", reply)
        self.assertIn("/generate_birthday_email Mary Lee", reply)
        self.assertIn("Voice after a draft: make it warmer", reply)
        self.assertIn("/send_last_email", reply)
        self.assertIn("/confirm_send_email", reply)
        self.assertIn("/cancel_email", reply)

    async def test_generate_birthday_email_command_generates_reviewable_draft(self):
        update = FakeUpdate("/generate_birthday_email Grace Hopper", user_id=456)
        client = {"name": "Grace Hopper", "birthday": "December 9"}
        draft = {
            "subject": "Happy Birthday, Grace",
            "body": "Hi Grace,\n\nWishing you a wonderful birthday.",
        }

        with patch("bot.crm") as crm, patch("bot.generate_birthday_email") as generator:
            crm.get_client.return_value = client
            generator.return_value = draft

            await generate_birthday_email_command(update, None)

        crm.get_client.assert_called_once_with("Grace Hopper")
        generator.assert_called_once_with(client, agent_profile)
        self.assertEqual(
            pending_email_drafts[456],
            {"client_name": "Grace Hopper", "draft": draft},
        )
        self.assertEqual(len(update.message.replies), 1)
        self.assertIn("Please review before sending", update.message.replies[0])
        self.assertIn("Subject: Happy Birthday, Grace", update.message.replies[0])
        self.assertIn("Hi Grace", update.message.replies[0])

    async def test_send_last_email_requires_pending_draft(self):
        update = FakeUpdate("/send_last_email", user_id=456)

        await send_last_email_command(update, None)

        self.assertEqual(update.message.replies, ["No pending email draft."])

    async def test_confirm_send_email_is_disabled_in_testing(self):
        update = FakeUpdate("/confirm_send_email", user_id=456)
        pending_email_drafts[456] = {
            "client_name": "Synthetic Client",
            "draft": {"subject": "Synthetic subject", "body": "Synthetic body"},
        }
        with (
            patch("bot.read_app_env", return_value="testing"),
            patch("bot.crm") as crm,
            patch("bot.send_email") as sender,
        ):
            await confirm_send_email_command(update, None)
        crm.get_client.assert_not_called()
        sender.assert_not_called()
        self.assertIn(456, pending_email_drafts)
        self.assertEqual(update.message.replies, ["Email sending is disabled outside production."])

    @patch("bot.read_app_env", return_value="production")
    async def test_send_last_email_requires_client_email(self, app_env):
        update = FakeUpdate("/send_last_email", user_id=456)
        pending_email_drafts[456] = {
            "client_name": "Grace Hopper",
            "draft": {"subject": "Happy Birthday", "body": "Hi Grace."},
        }

        with patch("bot.crm") as crm, patch("bot.send_email") as sender:
            crm.get_client.return_value = {"name": "Grace Hopper", "email": ""}

            await confirm_send_email_command(update, None)

        crm.get_client.assert_called_once_with("Grace Hopper")
        sender.assert_not_called()
        self.assertEqual(update.message.replies, ["Client does not have an email address."])
        self.assertIn(456, pending_email_drafts)

    async def test_send_last_email_shows_confirmation_preview_without_sending(self):
        update = FakeUpdate("/send_last_email", user_id=456)
        pending_email_drafts[456] = {
            "client_name": "Grace Hopper",
            "draft": {"subject": "Happy Birthday", "body": "Hi Grace."},
        }

        with (
            patch("bot.crm") as crm,
            patch("bot.send_email") as sender,
            patch("bot.generate_birthday_email") as generator,
            patch("bot.openai_client") as openai_client,
        ):
            crm.get_client.return_value = {
                "name": "Grace Hopper",
                "email": "grace@example.com",
            }

            await send_last_email_command(update, None)

        crm.get_client.assert_called_once_with("Grace Hopper")
        sender.assert_not_called()
        generator.assert_not_called()
        openai_client.responses.create.assert_not_called()
        self.assertIn(456, pending_email_drafts)
        self.assertEqual(len(update.message.replies), 1)
        self.assertIn("To: grace@example.com", update.message.replies[0])
        self.assertIn("Subject: Happy Birthday", update.message.replies[0])
        self.assertIn("Hi Grace.", update.message.replies[0])
        self.assertIn("/confirm_send_email to send", update.message.replies[0])
        self.assertIn("/cancel_email to cancel", update.message.replies[0])

    async def test_confirm_send_email_requires_pending_draft(self):
        update = FakeUpdate("/confirm_send_email", user_id=456)

        await confirm_send_email_command(update, None)

        self.assertEqual(update.message.replies, ["No pending email draft."])

    @patch("bot.read_app_env", return_value="production")
    async def test_confirm_send_email_sends_and_clears_pending_draft(self, app_env):
        update = FakeUpdate("/confirm_send_email", user_id=456)
        pending_email_drafts[456] = {
            "client_name": "Grace Hopper",
            "draft": {"subject": "Happy Birthday", "body": "Hi Grace."},
        }

        with (
            patch("bot.crm") as crm,
            patch("bot.send_email") as sender,
            patch("bot.generate_birthday_email") as generator,
            patch("bot.openai_client") as openai_client,
        ):
            crm.get_client.return_value = {
                "name": "Grace Hopper",
                "email": "grace@example.com",
            }

            await confirm_send_email_command(update, None)

        crm.get_client.assert_called_once_with("Grace Hopper")
        sender.assert_called_once_with("grace@example.com", "Happy Birthday", "Hi Grace.")
        generator.assert_not_called()
        openai_client.responses.create.assert_not_called()
        self.assertNotIn(456, pending_email_drafts)
        self.assertEqual(update.message.replies, ["Email sent successfully."])

    @patch("bot.read_app_env", return_value="production")
    async def test_confirm_send_email_keeps_pending_draft_when_send_fails(self, app_env):
        update = FakeUpdate("/confirm_send_email", user_id=456)
        pending_email_drafts[456] = {
            "client_name": "Grace Hopper",
            "draft": {"subject": "Happy Birthday", "body": "Hi Grace."},
        }

        with patch("bot.crm") as crm, patch("bot.send_email", side_effect=ValueError("SMTP failed")):
            crm.get_client.return_value = {
                "name": "Grace Hopper",
                "email": "grace@example.com",
            }

            await confirm_send_email_command(update, None)

        self.assertIn(456, pending_email_drafts)
        self.assertEqual(
            update.message.replies,
            ["Could not send email. Please try again later."],
        )

    async def test_cancel_email_clears_pending_draft(self):
        update = FakeUpdate("/cancel_email", user_id=456)
        pending_email_drafts[456] = {
            "client_name": "Grace Hopper",
            "draft": {"subject": "Happy Birthday", "body": "Hi Grace."},
        }

        await cancel_email_command(update, None)

        self.assertNotIn(456, pending_email_drafts)
        self.assertEqual(update.message.replies, ["Email draft canceled."])

    async def test_cancel_email_requires_pending_draft(self):
        update = FakeUpdate("/cancel_email", user_id=456)

        await cancel_email_command(update, None)

        self.assertEqual(update.message.replies, ["No pending email draft."])

    async def test_generate_birthday_email_command_requires_client_name(self):
        update = FakeUpdate("/generate_birthday_email")

        await generate_birthday_email_command(update, None)

        self.assertEqual(
            update.message.replies,
            ["Usage:\n/generate_birthday_email John Smith"],
        )

    async def test_generate_birthday_email_command_handles_missing_client(self):
        update = FakeUpdate("/generate_birthday_email Missing Client")

        with patch("bot.crm") as crm, patch("bot.generate_birthday_email") as generator:
            crm.get_client.return_value = None

            await generate_birthday_email_command(update, None)

        crm.get_client.assert_called_once_with("Missing Client")
        generator.assert_not_called()
        self.assertEqual(update.message.replies, ["Client not found: Missing Client"])

    async def test_generate_birthday_email_command_suggests_close_client_match(self):
        update = FakeUpdate("/generate_birthday_email Alex Chan")

        with patch("bot.crm") as crm, patch("bot.generate_birthday_email") as generator:
            crm.get_client.return_value = None
            crm.suggest_client_name.return_value = "Alex Chen"

            await generate_birthday_email_command(update, None)

        crm.get_client.assert_called_once_with("Alex Chan")
        crm.suggest_client_name.assert_called_once_with("Alex Chan")
        generator.assert_not_called()
        self.assertEqual(
            update.message.replies,
            ["Client not found: Alex Chan\nDid you mean: Alex Chen?"],
        )

    async def test_get_client_command_suggests_close_client_match(self):
        update = FakeUpdate("/get_client Alex Chan")

        with patch("bot.crm") as crm:
            crm.get_client.return_value = None
            crm.suggest_client_name.return_value = "Alex Chen"

            await get_client_command(update, None)

        crm.get_client.assert_called_once_with("Alex Chan")
        crm.suggest_client_name.assert_called_once_with("Alex Chan")
        crm.format_client_report.assert_not_called()
        self.assertEqual(
            update.message.replies,
            ["Client not found: Alex Chan\nDid you mean: Alex Chen?"],
        )

    async def test_voice_with_pending_draft_revises_and_updates_cached_draft(self):
        pending_email_drafts[123] = {
            "subject": "Happy Birthday, Grace",
            "body": "Hi Grace,\n\nHappy birthday.",
        }
        revised = {
            "subject": "A Warm Birthday Wish",
            "body": "Hi Grace,\n\nWishing you a warm and wonderful birthday.",
        }
        voice = types.SimpleNamespace(file_id="file-1", file_unique_id="voice-1")
        update = FakeUpdate(user_id=123, voice=voice)

        with (
            patch("bot.transcribe_voice_file", return_value="Make it warmer.") as transcribe,
            patch("bot.extract_voice_intent_with_openai", return_value=None),
            patch("bot.revise_email_draft_with_openai", return_value=revised) as revise,
        ):
            await handle_voice_message(update, FakeContext())

        transcribe.assert_called_once()
        revise.assert_called_once_with(
            {"subject": "Happy Birthday, Grace", "body": "Hi Grace,\n\nHappy birthday."},
            "Make it warmer.",
            agent_profile,
        )
        self.assertEqual(pending_email_drafts[123], revised)
        self.assertEqual(len(update.message.replies), 1)
        self.assertIn("Updated birthday email draft", update.message.replies[0])
        self.assertIn("Subject: A Warm Birthday Wish", update.message.replies[0])

    async def test_voice_with_pending_draft_routes_explicit_list_command_first(self):
        pending_email_drafts[123] = {
            "subject": "Happy Birthday, Grace",
            "body": "Hi Grace,\n\nHappy birthday.",
        }
        voice = types.SimpleNamespace(file_id="file-1", file_unique_id="voice-1")
        update = FakeUpdate(user_id=123, voice=voice)
        intent_data = {"intent": "list_clients", "client_name": "", "fields": {}}

        with (
            patch("bot.transcribe_voice_file", return_value="List clients"),
            patch("bot.extract_voice_intent_with_openai", return_value=intent_data) as extract_intent,
            patch("bot.revise_email_draft_with_openai") as revise,
            patch("bot.extract_voice_client_update_with_openai") as extract_update,
            patch("bot.crm") as crm,
        ):
            crm.list_clients.return_value = [
                {"name": "Grace Hopper", "status": "active", "phone": "5550100"}
            ]

            await handle_voice_message(update, FakeContext())

        extract_intent.assert_called_once_with("List clients")
        revise.assert_not_called()
        extract_update.assert_not_called()
        crm.list_clients.assert_called_once_with()
        self.assertEqual(
            update.message.replies,
            ["Clients:\n- Grace Hopper | active | 5550100"],
        )
        self.assertEqual(
            pending_email_drafts[123],
            {
                "subject": "Happy Birthday, Grace",
                "body": "Hi Grace,\n\nHappy birthday.",
            },
        )

    async def test_voice_router_runs_before_existing_crm_update_fallback(self):
        voice = types.SimpleNamespace(file_id="file-1", file_unique_id="voice-1")
        update = FakeUpdate(user_id=123, voice=voice)
        intent_data = {"intent": "list_clients", "client_name": "", "fields": {}}

        with (
            patch("bot.transcribe_voice_file", return_value="List clients"),
            patch("bot.extract_voice_intent_with_openai", return_value=intent_data) as extract_intent,
            patch("bot.route_voice_intent", return_value=True) as route,
            patch("bot.extract_voice_client_update_with_openai") as extract_update,
            patch("bot.parse_voice_client_update") as parse_update,
        ):
            await handle_voice_message(update, FakeContext())

        extract_intent.assert_called_once_with("List clients")
        route.assert_called_once_with(update, intent_data, "List clients")
        extract_update.assert_not_called()
        parse_update.assert_not_called()

    async def test_voice_get_client_missing_name_returns_debug_context(self):
        voice = types.SimpleNamespace(file_id="file-1", file_unique_id="voice-1")
        update = FakeUpdate(user_id=123, voice=voice)
        intent_data = {"intent": "get_client", "client_name": "", "fields": {}}

        with (
            patch("bot.DEBUG", True),
            patch("bot.transcribe_voice_file", return_value="Get client Alex Chen"),
            patch("bot.extract_voice_intent_with_openai", return_value=intent_data),
            patch("bot.extract_voice_client_update_with_openai") as extract_update,
            patch("bot.parse_voice_client_update") as parse_update,
        ):
            await handle_voice_message(update, FakeContext())

        extract_update.assert_not_called()
        parse_update.assert_not_called()
        self.assertEqual(len(update.message.replies), 1)
        self.assertIn("Client not found: ", update.message.replies[0])
        self.assertIn("Heard: Get client Alex Chen", update.message.replies[0])
        self.assertIn("Intent: get_client", update.message.replies[0])
        self.assertIn('"client_name": ""', update.message.replies[0])

    async def test_voice_without_pending_draft_uses_existing_crm_voice_flow(self):
        voice = types.SimpleNamespace(file_id="file-1", file_unique_id="voice-1")
        update = FakeUpdate(user_id=123, voice=voice)

        with (
            patch("bot.transcribe_voice_file", return_value="Update client Grace Hopper, status active"),
            patch("bot.extract_voice_intent_with_openai", return_value=None),
            patch("bot.extract_voice_client_update_with_openai", return_value=("Grace Hopper", "status=active")),
            patch("bot.revise_email_draft_with_openai") as revise,
            patch("bot.crm") as crm,
        ):
            crm.update_client_from_text.return_value = {
                "name": "Grace Hopper",
                "status": "active",
            }
            crm.format_client_report.return_value = "Client: Grace Hopper\nStatus: active"

            await handle_voice_message(update, FakeContext())

        revise.assert_not_called()
        crm.update_client_from_text.assert_called_once_with("Grace Hopper", "status=active")
        self.assertIn("Client updated from voice", update.message.replies[0])

    async def test_voice_falls_back_to_raw_transcription_when_no_command_matches(self):
        voice = types.SimpleNamespace(file_id="file-1", file_unique_id="voice-1")
        update = FakeUpdate(user_id=123, voice=voice)

        with (
            patch("bot.transcribe_voice_file", return_value="This is just a note."),
            patch("bot.extract_voice_intent_with_openai", return_value=None),
            patch("bot.extract_voice_client_update_with_openai", return_value=None),
        ):
            await handle_voice_message(update, FakeContext())

        self.assertEqual(update.message.replies, ["Transcription:\nThis is just a note."])

    async def test_voice_router_lists_clients(self):
        update = FakeUpdate()

        with patch("bot.crm") as crm:
            crm.list_clients.return_value = [
                {"name": "Grace Hopper", "status": "active", "phone": "5550100"}
            ]

            handled = await route_voice_intent(update, {"intent": "list_clients"})

        self.assertTrue(handled)
        crm.list_clients.assert_called_once_with()
        self.assertEqual(
            update.message.replies,
            ["Clients:\n- Grace Hopper | active | 5550100"],
        )

    async def test_voice_router_gets_client(self):
        update = FakeUpdate()
        client = {"name": "Grace Hopper", "status": "active"}

        with patch("bot.crm") as crm:
            crm.get_client.return_value = client
            crm.format_client_report.return_value = "Client: Grace Hopper"

            handled = await route_voice_intent(
                update,
                {"intent": "get_client", "client_name": "Grace Hopper", "fields": {}},
            )

        self.assertTrue(handled)
        crm.get_client.assert_called_once_with("Grace Hopper")
        crm.format_client_report.assert_called_once_with(client)
        self.assertEqual(update.message.replies, ["Client: Grace Hopper"])

    async def test_voice_router_get_client_not_found_returns_debug_context(self):
        update = FakeUpdate()
        intent_data = {"intent": "get_client", "client_name": "Alex Chen", "fields": {}}

        with patch("bot.DEBUG", True), patch("bot.crm") as crm:
            crm.get_client.return_value = None

            handled = await route_voice_intent(update, intent_data, "Get client Alex Chen")

        self.assertTrue(handled)
        crm.get_client.assert_called_once_with("Alex Chen")
        self.assertEqual(len(update.message.replies), 1)
        self.assertIn("Client not found: Alex Chen", update.message.replies[0])
        self.assertIn("Heard: Get client Alex Chen", update.message.replies[0])
        self.assertIn("Intent: get_client", update.message.replies[0])
        self.assertIn('"client_name": "Alex Chen"', update.message.replies[0])

    async def test_voice_router_get_client_not_found_suggests_close_match(self):
        update = FakeUpdate()
        intent_data = {"intent": "get_client", "client_name": "Alex Chan", "fields": {}}

        with patch("bot.DEBUG", True), patch("bot.crm") as crm:
            crm.get_client.return_value = None
            crm.suggest_client_name.return_value = "Alex Chen"

            handled = await route_voice_intent(update, intent_data, "Get client Alex Chan")

        self.assertTrue(handled)
        crm.get_client.assert_called_once_with("Alex Chan")
        crm.suggest_client_name.assert_called_once_with("Alex Chan")
        self.assertIn("Client not found: Alex Chan", update.message.replies[0])
        self.assertIn("Did you mean: Alex Chen?", update.message.replies[0])
        self.assertIn("Heard: Get client Alex Chan", update.message.replies[0])

    async def test_voice_router_get_client_not_found_suggests_close_match_without_debug(self):
        update = FakeUpdate()
        intent_data = {"intent": "get_client", "client_name": "Alex Chan", "fields": {}}

        with patch("bot.DEBUG", False), patch("bot.crm") as crm:
            crm.get_client.return_value = None
            crm.suggest_client_name.return_value = "Alex Chen"

            handled = await route_voice_intent(update, intent_data, "Get client Alex Chan")

        self.assertTrue(handled)
        crm.get_client.assert_called_once_with("Alex Chan")
        crm.suggest_client_name.assert_called_once_with("Alex Chan")
        self.assertEqual(
            update.message.replies,
            ["Client not found: Alex Chan\nDid you mean: Alex Chen?"],
        )

    async def test_voice_router_generate_birthday_email_suggests_close_match(self):
        update = FakeUpdate()
        intent_data = {
            "intent": "generate_birthday_email",
            "client_name": "Alex Chan",
            "fields": {},
        }

        with patch("bot.crm") as crm, patch("bot.generate_birthday_email") as generator:
            crm.get_client.return_value = None
            crm.suggest_client_name.return_value = "Alex Chen"

            handled = await route_voice_intent(update, intent_data)

        self.assertTrue(handled)
        crm.get_client.assert_called_once_with("Alex Chan")
        crm.suggest_client_name.assert_called_once_with("Alex Chan")
        generator.assert_not_called()
        self.assertEqual(
            update.message.replies,
            ["Client not found: Alex Chan\nDid you mean: Alex Chen?"],
        )

    async def test_voice_router_generates_birthday_email_and_caches_draft(self):
        update = FakeUpdate(user_id=789)
        client = {"name": "Grace Hopper", "birthday": "December 9"}
        draft = {"subject": "Happy Birthday", "body": "Hi Grace."}

        with patch("bot.crm") as crm, patch("bot.generate_birthday_email") as generator:
            crm.get_client.return_value = client
            generator.return_value = draft

            handled = await route_voice_intent(
                update,
                {
                    "intent": "generate_birthday_email",
                    "client_name": "Grace Hopper",
                    "fields": {},
                },
            )

        self.assertTrue(handled)
        crm.get_client.assert_called_once_with("Grace Hopper")
        generator.assert_called_once_with(client, agent_profile)
        self.assertEqual(
            pending_email_drafts[789],
            {"client_name": "Grace Hopper", "draft": draft},
        )
        self.assertIn("Subject: Happy Birthday", update.message.replies[0])

    async def test_voice_router_updates_client(self):
        update = FakeUpdate()

        with patch("bot.crm") as crm:
            crm.update_client_from_text.return_value = {
                "name": "Grace Hopper",
                "status": "active",
            }
            crm.format_client_report.return_value = "Client: Grace Hopper\nStatus: active"

            handled = await route_voice_intent(
                update,
                {
                    "intent": "update_client",
                    "client_name": "Grace Hopper",
                    "fields": {"status": "active"},
                },
            )

        self.assertTrue(handled)
        crm.update_client_from_text.assert_called_once_with(
            "Grace Hopper",
            "status=active",
        )
        self.assertIn("Client updated from voice", update.message.replies[0])

    def test_revise_email_draft_with_openai_validates_json_response(self):
        response = types.SimpleNamespace(
            output_text='{"subject":"New subject","body":"New body"}'
        )

        with patch("bot.openai_client") as openai_client:
            openai_client.responses.create.return_value = response

            draft = revise_email_draft_with_openai(
                {"subject": "Old subject", "body": "Old body"},
                "Make it shorter.",
            )

        self.assertEqual(draft, {"subject": "New subject", "body": "New body"})

    def test_revision_prompt_uses_agent_dna_but_prioritizes_user_instruction(self):
        response = types.SimpleNamespace(
            output_text='{"subject":"Short","body":"Hi Grace."}'
        )
        profile = {
            "agent_name": "Test Agent",
            "writing_tone": ["warm"],
        }

        with patch("bot.openai_client") as openai_client:
            openai_client.responses.create.return_value = response
            revise_email_draft_with_openai(
                {"subject": "Old", "body": "Old body"},
                "Make it very direct.",
                profile,
            )

        call = openai_client.responses.create.call_args
        self.assertIn('"agent_name": "Test Agent"', call.kwargs["input"])
        self.assertIn(
            "Authoritative user revision instruction: Make it very direct.",
            call.kwargs["input"],
        )
        self.assertIn(
            "user's explicit revision instruction takes priority",
            call.kwargs["instructions"],
        )

    def test_extract_voice_intent_with_openai_validates_json_response(self):
        response = types.SimpleNamespace(
            output_text=(
                '{"intent":"get_client","client_name":"Grace Hopper","fields":{}}'
            )
        )

        with patch("bot.openai_client") as openai_client:
            openai_client.responses.create.return_value = response

            intent = extract_voice_intent_with_openai("Show me Grace Hopper")

        self.assertEqual(
            intent,
            {"intent": "get_client", "client_name": "Grace Hopper", "fields": {}},
        )


if __name__ == "__main__":
    unittest.main()
