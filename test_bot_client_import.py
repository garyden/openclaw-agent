import sys
import types
import unittest
from unittest.mock import AsyncMock, patch


telegram = types.ModuleType("telegram")
telegram.Update = object
telegram_ext = types.ModuleType("telegram.ext")
for name in ["ApplicationBuilder", "CommandHandler", "MessageHandler", "ContextTypes", "filters"]:
    setattr(telegram_ext, name, object())
openai = types.ModuleType("openai")
openai.OpenAI = lambda *args, **kwargs: None
sys.modules.setdefault("telegram", telegram)
sys.modules.setdefault("telegram.ext", telegram_ext)
sys.modules.setdefault("openai", openai)

import bot


class FakeMessage:
    def __init__(self, text="", document=None):
        self.text = text
        self.document = document
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, text="", user_id=123, document=None):
        self.message = FakeMessage(text, document)
        self.effective_user = types.SimpleNamespace(id=user_id)


class FakeTelegramFile:
    async def download_to_drive(self, path):
        with open(path, "wb") as output:
            output.write(b"test")


class BotClientImportTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.pending_client_imports.clear()

    async def test_upload_previews_without_writing_then_confirm_imports(self):
        await bot.import_clients_command(FakeUpdate("/import_clients"), None)
        document = types.SimpleNamespace(file_name="clients.xlsx", file_id="file-1")
        upload_update = FakeUpdate(user_id=123, document=document)
        context = types.SimpleNamespace(
            bot=types.SimpleNamespace(get_file=AsyncMock(return_value=FakeTelegramFile()))
        )
        rows = [{"row_number": 2, "client": {"name": "Lisa Chen"}, "row_errors": []}]
        preview = {
            "total_rows": 1,
            "ready": [{"name": "Lisa Chen", "status": "new_lead"}],
            "duplicates": [],
            "errors": [],
        }
        with (
            patch("bot.parse_client_workbook", return_value=rows),
            patch("bot.build_import_preview", return_value=preview),
            patch("bot.crm") as crm,
        ):
            crm.list_clients.return_value = []
            await bot.handle_client_import_document(upload_update, context)
            crm.add_clients_batch.assert_not_called()
            confirm_update = FakeUpdate("/confirm_import_clients")
            crm.add_clients_batch.return_value = preview["ready"]
            await bot.confirm_import_clients_command(confirm_update, None)

        crm.add_clients_batch.assert_called_once_with(preview["ready"])
        self.assertNotIn(123, bot.pending_client_imports)
        self.assertIn("1 clients added", confirm_update.message.replies[0])

    async def test_cancel_removes_pending_import_without_writing(self):
        bot.pending_client_imports[123] = {"status": "awaiting_upload"}
        update = FakeUpdate("/cancel_import_clients")
        with patch("bot.crm") as crm:
            await bot.cancel_import_clients_command(update, None)
        crm.add_clients_batch.assert_not_called()
        self.assertNotIn(123, bot.pending_client_imports)


if __name__ == "__main__":
    unittest.main()
