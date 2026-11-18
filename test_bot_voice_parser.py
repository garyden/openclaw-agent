import sys
import types
import unittest


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

from bot import parse_voice_client_update, voice_client_update_from_data


class BotVoiceParserTest(unittest.TestCase):
    def test_voice_client_update_from_data_converts_allowed_fields(self):
        result = voice_client_update_from_data(
            {
                "intent": "update_client",
                "client_name": "John Smith",
                "fields": {
                    "status": "touring",
                    "next_followup": "2026-05-28",
                    "notes": "scheduled showing this weekend",
                },
            }
        )

        self.assertEqual(
            result,
            (
                "John Smith",
                "status=touring | next_followup=2026-05-28 | "
                "notes=scheduled showing this weekend",
            ),
        )

    def test_voice_client_update_from_data_ignores_unknown_intent(self):
        result = voice_client_update_from_data(
            {"intent": "unknown", "client_name": "", "fields": {}}
        )

        self.assertIsNone(result)

    def test_update_client_supports_hyphenated_followup_date(self):
        result = parse_voice_client_update(
            "Update client John Smith, status touring, "
            "next follow-up 2026 May 28th, notes scheduled showing this weekend."
        )

        self.assertEqual(
            result,
            (
                "John Smith",
                "status=touring | next_followup=2026-05-28 | "
                "notes=scheduled showing this weekend",
            ),
        )

    def test_update_client_supports_missing_commas(self):
        result = parse_voice_client_update(
            "Update client John Smith status touring "
            "next follow up 2026 May 28th notes scheduled showing this weekend."
        )

        self.assertEqual(
            result,
            (
                "John Smith",
                "status=touring | next_followup=2026-05-28 | "
                "notes=scheduled showing this weekend",
            ),
        )

    def test_update_client_supports_field_label_split_by_comma(self):
        result = parse_voice_client_update(
            "Update client John Smith, status touring, "
            "Next Follow-up, 2026 May 28th, notes scheduled showing this weekend."
        )

        self.assertEqual(
            result,
            (
                "John Smith",
                "status=touring | next_followup=2026-05-28 | "
                "notes=scheduled showing this weekend",
            ),
        )

    def test_update_client_supports_date_split_by_comma(self):
        result = parse_voice_client_update(
            "Update client John Smith, status touring, "
            "Next Follow-up 2026, May 28th, notes scheduled showing this weekend."
        )

        self.assertEqual(
            result,
            (
                "John Smith",
                "status=touring | next_followup=2026-05-28 | "
                "notes=scheduled showing this weekend",
            ),
        )


if __name__ == "__main__":
    unittest.main()
