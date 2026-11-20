# Local setup

See README.md for Python setup, configuration, offline tests, and data-isolation limits.
Use a dedicated virtual environment and copy `.env.example` to `.env.development`
when deliberately configuring a development bot. Use development credentials
and synthetic CRM data. Configure the Mac mini production service separately
as described in README.md.

## Batch import

Use /client_import_template for the blank workbook, /import_clients to upload,
review the preview, then /confirm_import_clients or /cancel_import_clients.
No client is imported before explicit confirmation.
