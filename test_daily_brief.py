import unittest
from datetime import date

from daily_brief import build_daily_brief


TODAY = date(2026, 7, 26)


class DailyBriefTest(unittest.TestCase):
    def test_matches_birthday_by_month_and_day_and_ignores_birth_year(self):
        brief = build_daily_brief(
            [
                {"name": "Lisa Chen", "birthday": "July 26"},
                {"name": "David Lee", "birthday": "1990-07-26"},
                {"name": "Future Date", "birthday": "July 27"},
            ],
            today=TODAY,
        )

        self.assertEqual(
            [item["client_name"] for item in brief["birthdays_today"]],
            ["David Lee", "Lisa Chen"],
        )

    def test_classifies_due_overdue_and_excludes_future_followups(self):
        brief = build_daily_brief(
            [
                {"name": "Due Today", "next_followup": "2026-07-26"},
                {"name": "Overdue", "next_followup": "2026-07-22"},
                {"name": "Future", "next_followup": "2026-07-27"},
            ],
            today=TODAY,
        )

        self.assertEqual(
            [item["client_name"] for item in brief["followups_due_today"]],
            ["Due Today"],
        )
        self.assertEqual(brief["overdue_followups"][0]["client_name"], "Overdue")
        self.assertEqual(brief["overdue_followups"][0]["days_overdue"], 4)

    def test_invalid_and_missing_dates_are_ignored(self):
        brief = build_daily_brief(
            [
                {"name": "Missing"},
                {
                    "name": "Invalid",
                    "birthday": "not a birthday",
                    "next_followup": "yesterday",
                },
                {"name": "Impossible", "birthday": "February 30", "next_followup": "2026-13-40"},
            ],
            today=TODAY,
        )

        self.assertEqual(brief["birthdays_today"], [])
        self.assertEqual(brief["followups_due_today"], [])
        self.assertEqual(brief["overdue_followups"], [])

    def test_most_overdue_is_sorted_first(self):
        brief = build_daily_brief(
            [
                {"name": "Two Days", "next_followup": "2026-07-24"},
                {"name": "Ten Days", "next_followup": "2026-07-16"},
                {"name": "Five Days", "next_followup": "2026-07-21"},
            ],
            today=TODAY,
        )

        self.assertEqual(
            [item["client_name"] for item in brief["overdue_followups"]],
            ["Ten Days", "Five Days", "Two Days"],
        )

    def test_same_client_can_appear_in_multiple_sections(self):
        brief = build_daily_brief(
            [
                {
                    "name": "Lisa Chen",
                    "birthday": "July 26",
                    "next_followup": "2026-07-20",
                }
            ],
            today=TODAY,
        )

        self.assertEqual(brief["birthdays_today"][0]["client_name"], "Lisa Chen")
        self.assertEqual(brief["overdue_followups"][0]["client_name"], "Lisa Chen")

    def test_suggested_action_uses_deterministic_priority(self):
        brief = build_daily_brief(
            [
                {"name": "Birthday", "birthday": "July 26"},
                {"name": "Due", "next_followup": "2026-07-26"},
                {"name": "Overdue", "next_followup": "2026-07-25"},
            ],
            [{"client_name": "Draft Client", "purpose": "birthday"}],
            today=TODAY,
        )

        self.assertEqual(brief["suggested_action"]["kind"], "overdue_followup")
        self.assertEqual(brief["suggested_action"]["client_name"], "Overdue")

    def test_suggested_action_falls_through_to_pending_draft(self):
        brief = build_daily_brief(
            [],
            [{"client_name": "Lisa Chen", "purpose": "birthday", "subject": "Birthday"}],
            today=TODAY,
        )

        self.assertEqual(
            brief["suggested_action"],
            {
                "kind": "pending_draft",
                "client_name": "Lisa Chen",
                "purpose": "birthday",
                "subject": "Birthday",
            },
        )

    def test_no_actionable_items_returns_empty_sections_and_no_suggestion(self):
        brief = build_daily_brief(
            [{"name": "Future", "next_followup": "2026-07-27"}],
            today=TODAY,
        )

        self.assertEqual(brief["birthdays_today"], [])
        self.assertEqual(brief["followups_due_today"], [])
        self.assertEqual(brief["overdue_followups"], [])
        self.assertEqual(brief["pending_drafts"], [])
        self.assertIsNone(brief["suggested_action"])


if __name__ == "__main__":
    unittest.main()
