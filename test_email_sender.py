import os
import unittest
from unittest.mock import patch

from email_sender import send_email


EMAIL_ENV = {
    "EMAIL_HOST": "smtp.example.com",
    "EMAIL_PORT": "587",
    "EMAIL_USER": "agent@example.com",
    "EMAIL_PASSWORD": "test-password",
}


class EmailSenderTest(unittest.TestCase):
    @patch("email_sender.smtplib.SMTP")
    def test_send_email_uses_smtp_config_and_message(self, smtp_class):
        smtp = smtp_class.return_value.__enter__.return_value

        with patch.dict(os.environ, EMAIL_ENV, clear=True):
            send_email(
                "client@example.com",
                "Showing schedule",
                "The showing is scheduled for this weekend.",
            )

        smtp_class.assert_called_once_with("smtp.example.com", 587)
        smtp.starttls.assert_called_once_with()
        smtp.login.assert_called_once_with("agent@example.com", "test-password")

        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["From"], "agent@example.com")
        self.assertEqual(message["To"], "client@example.com")
        self.assertEqual(message["Subject"], "Showing schedule")
        self.assertEqual(message.get_content(), "The showing is scheduled for this weekend.\n")

    def test_send_email_requires_config(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "EMAIL_HOST is not set"):
                send_email("client@example.com", "Subject", "Body")

    def test_send_email_requires_integer_port(self):
        env = {**EMAIL_ENV, "EMAIL_PORT": "invalid"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "EMAIL_PORT must be an integer"):
                send_email("client@example.com", "Subject", "Body")


if __name__ == "__main__":
    unittest.main()
