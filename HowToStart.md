# Local setup

See README.md for Python setup, configuration, offline tests, and data-isolation limits.
Use a dedicated virtual environment and copy .env.example to a local .env only
when deliberately configuring this independent source snapshot. Never copy an
existing production .env or XML store into it for development or tests.

## Batch import

Use /client_import_template for the blank workbook, /import_clients to upload,
review the preview, then /confirm_import_clients or /cancel_import_clients.
No client is imported before explicit confirmation.
