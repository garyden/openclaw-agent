import os
import tempfile
import unittest
from datetime import date

from openpyxl import load_workbook

from client_importer import build_import_preview, parse_client_workbook


TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "assets", "client_import_template.xlsx"
)


class ClientImporterTest(unittest.TestCase):
    def make_workbook(self, rows):
        workbook = load_workbook(TEMPLATE_PATH)
        sheet = workbook["Clients"]
        for row_index, row in enumerate(rows, start=2):
            for column_index, value in enumerate(row, start=1):
                sheet.cell(row=row_index, column=column_index, value=value)
        temp_file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        temp_file.close()
        workbook.save(temp_file.name)
        workbook.close()
        self.addCleanup(lambda: os.path.exists(temp_file.name) and os.unlink(temp_file.name))
        return temp_file.name

    def test_parses_and_normalizes_template_rows(self):
        path = self.make_workbook(
            [[
                "Lisa Chen", "lisa@example.com", "(732) 555-0101", "", "800000",
                "Princeton", "3 bedrooms", "active", "Referral", date(1990, 7, 28),
                "07/20/2026", "2026-08-01",
            ]]
        )
        rows = parse_client_workbook(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client"]["name"], "Lisa Chen")
        self.assertEqual(rows[0]["client"]["birthday"], "1990-07-28")
        self.assertEqual(rows[0]["client"]["last_contact"], "2026-07-20")
        self.assertEqual(rows[0]["row_errors"], [])

    def test_invalid_rows_and_duplicates_are_not_ready(self):
        path = self.make_workbook(
            [
                ["Existing Client", "new@example.com", "", "", "", "", "", "active"],
                ["New Client", "existing@example.com", "", "", "", "", "", "active"],
                ["Bad Status", "", "", "", "", "", "", "not-valid"],
                ["", "", "", "", "", "", "", "active"],
            ]
        )
        preview = build_import_preview(
            parse_client_workbook(path),
            [{"name": "Existing Client", "email": "existing@example.com", "phone": ""}],
        )
        self.assertEqual(len(preview["ready"]), 0)
        self.assertEqual(len(preview["duplicates"]), 2)
        self.assertEqual(len(preview["errors"]), 2)


if __name__ == "__main__":
    unittest.main()
