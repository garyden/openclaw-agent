import unittest

from tour import format_tour_menu, format_tour_topic


class TourTest(unittest.TestCase):
    def test_menu_is_short_and_lists_five_topics(self):
        menu = format_tour_menu("Test Agent")
        self.assertIn("Hi Test Agent!", menu)
        for number in range(1, 6):
            self.assertIn(f"{number}.", menu)
        self.assertIn("/cancel_tour", menu)

    def test_each_topic_has_safe_action_guidance(self):
        for number in range(1, 6):
            topic = format_tour_topic(str(number))
            self.assertIsNotNone(topic)
            self.assertIn("another number", topic)

        self.assertIn("informational only", format_tour_topic("1"))
        self.assertIn("requires confirmation", format_tour_topic("2"))
        self.assertIn("Nothing is imported until", format_tour_topic("3"))
        self.assertIn("does not send", format_tour_topic("4"))
        self.assertIn("Only /confirm_send_email", format_tour_topic("5"))

    def test_invalid_topic_is_rejected(self):
        self.assertIsNone(format_tour_topic("unknown"))
