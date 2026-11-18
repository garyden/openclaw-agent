import os
import tempfile
import unittest

from client_manager import ClientManager, VALID_STATUSES, STATUS_ALIASES, normalize_client_status


class ClientManagerTest(unittest.TestCase):
    def make_manager(self):
        temp_dir = tempfile.TemporaryDirectory()
        xml_path = os.path.join(temp_dir.name, "memory.xml")
        manager = ClientManager(xml_path)
        return temp_dir, manager

    def test_status_normalizer_accepts_exact_bilingual_aliases_only(self):
        for alias, expected in STATUS_ALIASES.items():
            with self.subTest(alias=alias):
                self.assertEqual(normalize_client_status(alias), expected)
                self.assertEqual(normalize_client_status('  ' + alias.upper() + '  '), expected)
        for canonical in VALID_STATUSES:
            self.assertEqual(normalize_client_status(canonical), canonical)
            self.assertEqual(normalize_client_status(canonical.replace('_', ' ').upper()), canonical)
            self.assertEqual(normalize_client_status(canonical.replace('_', '-')), canonical)
        for unknown in [None, 1, '', '未知', 'active or paused', 'not touring',
                        '看房中或暂停', '不看房中', 'offer', 'done', 'inactive']:
            self.assertIsNone(normalize_client_status(unknown))

    def test_storage_normalizes_bilingual_statuses_before_validation(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)
        manager.add_client(name='Synthetic Test', status='新线索')
        for canonical, aliases in [
            ('new_lead', ['新客户', 'New Lead']),
            ('active', ['跟进中', 'active']),
            ('touring', ['看房中', 'viewing']),
            ('offer_submitted', ['已提交报价', 'Offer Submitted']),
            ('closed', ['已成交', 'deal closed']),
            ('paused', ['暂缓', 'on hold']),
        ]:
            for alias in aliases:
                with self.subTest(alias=alias):
                    # This is the raw field-pair path used by legacy voice updates.
                    manager.update_client_from_text('Synthetic Test', f'status={alias}')
                    self.assertEqual(manager.get_client('Synthetic Test')['status'], canonical)
        with open(manager.xml_path, 'rb') as file:
            before = file.read()
        for alias in ['未知', 'unknown', '看房中或暂停', 'active or paused']:
            with self.assertRaises(ValueError):
                manager.update_client('Synthetic Test', status=alias)
            with open(manager.xml_path, 'rb') as file:
                self.assertEqual(file.read(), before)

    def test_add_get_update_delete_client(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        client = manager.add_client(
            name="John Smith",
            email="john@example.com",
            phone="1234567890",
            budget="800000",
            areas="Princeton, Edison",
            status="active",
        )

        self.assertEqual(client["name"], "John Smith")
        self.assertEqual(manager.get_client("john smith")["email"], "john@example.com")

        updated = manager.update_client(
            "John Smith",
            status="touring",
            notes="Scheduled showing",
        )
        self.assertEqual(updated["status"], "touring")
        self.assertEqual(updated["notes"], "Scheduled showing")

        self.assertTrue(manager.delete_client("John Smith"))
        self.assertIsNone(manager.get_client("John Smith"))

    def test_xml_persists_and_reloads(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        manager.add_client(name="Mary Lee", phone="5552221111")
        reloaded = ClientManager(manager.xml_path)

        self.assertEqual(len(reloaded.list_clients()), 1)
        self.assertEqual(reloaded.get_client("Mary Lee")["phone"], "5552221111")

    def test_add_clients_batch_is_atomic(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        imported = manager.add_clients_batch(
            [
                {"name": "Amy Wang", "status": "active"},
                {"name": "Lisa Chen", "status": "new_lead"},
            ]
        )
        self.assertEqual(len(imported), 2)

        with self.assertRaises(ValueError):
            manager.add_clients_batch(
                [
                    {"name": "David Lee", "status": "active"},
                    {"name": "Amy Wang", "status": "active"},
                ]
            )

        self.assertIsNone(manager.get_client("David Lee"))

    def test_duplicate_detection_normalizes_name_spacing(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        manager.add_client(name="John Smith")

        with self.assertRaises(ValueError):
            manager.add_client(name=" john   smith ")

    def test_get_client_accepts_unique_first_name_match(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        manager.add_client(name="Alex Chen", email="alex@example.com")

        self.assertEqual(manager.get_client("Alex")["name"], "Alex Chen")
        self.assertEqual(manager.get_client("alex")["email"], "alex@example.com")

    def test_get_client_does_not_guess_ambiguous_first_name_match(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        manager.add_client(name="John Smith")
        manager.add_client(name="John Lee")

        self.assertIsNone(manager.get_client("John"))

    def test_suggest_client_name_returns_close_match(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        manager.add_client(name="Alex Chen")

        self.assertEqual(manager.suggest_client_name("Alex Chan"), "Alex Chen")
        self.assertIsNone(manager.get_client("Alex Chan"))

    def test_suggest_client_name_ignores_distant_match(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        manager.add_client(name="Alex Chen")

        self.assertIsNone(manager.suggest_client_name("Alice Johnson"))

    def test_add_client_from_easy_text(self):
        temp_dir, manager = self.make_manager()
        self.addCleanup(temp_dir.cleanup)

        client = manager.add_client_from_text(
            "name=Grace Hopper | email=grace@example.com | "
            "phone=5550100 | areas=Princeton, Edison | status=active"
        )

        self.assertEqual(client["name"], "Grace Hopper")
        self.assertEqual(client["email"], "grace@example.com")
        self.assertEqual(client["areas"], "Princeton, Edison")
        self.assertEqual(client["status"], "active")

    def test_existing_memory_file_gets_clients_section(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = os.path.join(temp_dir, "memory.xml")
            with open(xml_path, "w", encoding="utf-8") as file:
                file.write("<memory><properties /></memory>")

            manager = ClientManager(xml_path)
            manager.add_client(name="Ada Lovelace")

            with open(xml_path, "r", encoding="utf-8") as file:
                content = file.read()

            self.assertIn("<clients>", content)
            self.assertIn("<name>Ada Lovelace</name>", content)

    def test_new_memory_file_only_ensures_required_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = os.path.join(temp_dir, "memory.xml")
            ClientManager(xml_path)

            with open(xml_path, "r", encoding="utf-8") as file:
                content = file.read()

            self.assertIn("<properties", content)
            self.assertIn("<towns", content)
            self.assertIn("<clients", content)
            self.assertNotIn("<user", content)
            self.assertNotIn("<facts", content)
            self.assertNotIn("<preferences", content)
            self.assertNotIn("<history", content)


if __name__ == "__main__":
    unittest.main()
