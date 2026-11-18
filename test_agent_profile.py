import json
import tempfile
import unittest
from pathlib import Path

from agent_profile import DEFAULT_AGENT_PROFILE, load_agent_profile


class AgentProfileTest(unittest.TestCase):
    def _write_profile(self, directory: str, value) -> Path:
        path = Path(directory) / "agent_profile.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_loads_complete_valid_profile_including_empty_company(self):
        configured = {
            "agent_name": "Test Agent",
            "company_name": "",
            "preferred_language": "English",
            "email_signature": "Best,\nTest Agent",
            "writing_tone": ["warm", "concise"],
            "preferred_email_length": "short",
            "greeting_style": "Use Hi {client_first_name},",
            "closing_style": "Use a warm closing.",
            "communication_principles": ["Be sincere."],
            "avoid": ["pushy sales language"],
        }
        with tempfile.TemporaryDirectory() as directory:
            profile = load_agent_profile(self._write_profile(directory, configured))

        self.assertEqual(profile, configured)
        self.assertEqual(profile["company_name"], "")

    def test_partial_profile_is_merged_with_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_profile(directory, {"agent_name": "Test Agent"})
            profile = load_agent_profile(path)

        self.assertEqual(profile["agent_name"], "Test Agent")
        self.assertEqual(
            profile["email_signature"],
            DEFAULT_AGENT_PROFILE["email_signature"],
        )

    def test_missing_profile_file_returns_defaults(self):
        profile = load_agent_profile("/path/that/does/not/exist/agent_profile.json")
        self.assertEqual(profile, DEFAULT_AGENT_PROFILE)

    def test_invalid_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent_profile.json"
            path.write_text("{invalid", encoding="utf-8")
            profile = load_agent_profile(path)

        self.assertEqual(profile, DEFAULT_AGENT_PROFILE)

    def test_invalid_field_types_are_defaulted_and_lists_are_cleaned(self):
        configured = {
            "agent_name": 123,
            "company_name": None,
            "writing_tone": [" warm ", 42, ""],
            "communication_principles": "Be sincere.",
            "avoid": [None, " pushy language "],
        }
        with tempfile.TemporaryDirectory() as directory:
            profile = load_agent_profile(self._write_profile(directory, configured))

        self.assertEqual(profile["agent_name"], DEFAULT_AGENT_PROFILE["agent_name"])
        self.assertEqual(profile["company_name"], DEFAULT_AGENT_PROFILE["company_name"])
        self.assertEqual(profile["writing_tone"], ["warm"])
        self.assertEqual(
            profile["communication_principles"],
            DEFAULT_AGENT_PROFILE["communication_principles"],
        )
        self.assertEqual(profile["avoid"], ["pushy language"])


if __name__ == "__main__":
    unittest.main()
