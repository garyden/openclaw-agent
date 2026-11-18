import unittest

from client_reference import resolve_client_reference


class ClientReferenceTest(unittest.TestCase):
    def setUp(self):
        self.clients = [
            {"name": "Alex Chen"},
            {"name": "Mary Lee"},
        ]

    def test_exact_match(self):
        result = resolve_client_reference("alex chen", self.clients)
        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["client"]["name"], "Alex Chen")

    def test_unique_close_match(self):
        result = resolve_client_reference("Alex Chan", self.clients)
        self.assertEqual(result["status"], "likely")
        self.assertEqual(result["client"]["name"], "Alex Chen")

    def test_ambiguous_match_is_not_guessed(self):
        clients = [{"name": "Alex Chen"}, {"name": "Alex Chon"}]
        result = resolve_client_reference("Alex Chan", clients)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["client"])
        self.assertEqual(len(result["candidates"]), 2)

    def test_distant_name_is_not_found(self):
        result = resolve_client_reference("Completely Different", self.clients)
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["client"])
