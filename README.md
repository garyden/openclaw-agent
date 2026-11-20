# Real Estate Telegram CRM - clean source snapshot

This independent source snapshot includes the current bilingual CRM, Daily Brief,
MVP 3.1 draft-only follow-up emails, and one-shot synthetic voice diagnostics.
It has no Git metadata, credentials, real CRM records, private agent profile,
market caches, virtual environment, private notes, or local archives.

## Setup (operator instructions only)

Use native Python 3.13 on Apple Silicon. In this directory:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B run_safe_tests.py
```

## Run development and production separately

| Environment | CRM XML | Configuration |
| --- | --- | --- |
| `development` (default) | Ignored `memory/development.xml` in each checkout. Set `CRM_MEMORY_PATH` to override it with a development-only store. | Copy `.env.example` to ignored `.env.development` in each checkout. Existing process variables take precedence. |
| `testing` | A per-process temporary directory by default. Explicit test paths must resolve under the system temporary directory and outside Git checkouts. | The safe runner clears inherited credentials, sets `APP_ENV=testing`, and uses synthetic fixtures and mocked services. |
| `production` | Explicit absolute `CRM_MEMORY_PATH` to an existing, readable and writable regular XML file with a `<memory>` root, outside every Git checkout. The containing directory must support atomic writes. | Set `APP_ENV=production` and supply credentials in the Mac mini service environment. Production does not load dotenv files. |

Keep development credentials on the MacBook and Mac mini separate from the Mac
mini production service credentials. Give the production service a dedicated
account and keep its data and secrets in private locations accessible to that
account. Each Telegram bot instance needs its own token if it runs at the same
time. Configure both owner and chat allowlists for each instance. Run
`.venv/bin/python -B bot.py` from the intended checkout once its environment is
configured. Keep the process environment fixed for the lifetime of the bot.

All CRM commands and legacy property and memory commands share the selected
store. Relative `CRM_MEMORY_PATH` overrides in development and testing resolve
from the checkout. Production rejects missing, malformed, inaccessible, and
checkout-local files before Telegram initialization. It validates symlink
targets and rejects hard-linked production files. Startup leaves existing
production XML untouched. Authorized edits use atomic replacement.

Development and testing can generate drafts, while SMTP delivery is available
only in production. Production still requires an authorized owner to issue
`/confirm_send_email` for a pending sendable draft.

## Migrate an existing production store

1. Schedule downtime and stop the existing production bot and any other writer.
2. As the operator, make a private backup outside Git, then copy the existing XML
   to a dedicated private directory outside all checkouts on the Mac mini. Use a
   regular file, set the production service as owner, and restrict directory and
   file permissions (for example, `0700` and `0600`).
3. As the production service account, verify the source and destination checksums
   match and validate the destination with `app_config.read_settings()` in the
   service environment before starting the bot. Keep credential values and XML
   contents out of terminal output, logs, and Git.
4. Start only the production instance and verify an authorized read-only CRM
   command. Keep the backup private. If rollback is needed, stop the service
   first and preserve the current store before restoring. Account for any CRM
   changes made after cutover.

## Operational limits

Use one bot process per XML store. Atomic writes prevent partial files, while
multiple writers can still overwrite one another’s changes. Explicit path
overrides rely on operator configuration and filesystem permissions, so keep
production files inaccessible to development accounts. Legacy `.env` and
`memory/memory.xml` are no longer automatic defaults. The optional private
`config/agent_profile.json` is ignored and can be based on the generic example.

The safe suite intentionally excludes test_fetch.py: importing that module can
fetch market data and write a cache. Do not use unrestricted test discovery.
Market CSV/raw caches are omitted; market analysis may need a deliberate data
setup/fetch before live use. No live API compatibility was checked during export.
Legacy property deletion still acts immediately for authorized users.

See NATURAL_CRM_MVP.md, NATURAL_CRM_MVP2.md, NATURAL_EMAIL_DRAFT_MVP3_1.md, and
VOICE_DRAFT_DIAGNOSTICS.md for feature scope and operator-only retest instructions.
Draft text is AI-assisted and requires human review. New follow-up drafts never
enter the existing birthday send queue. Synthetic diagnostics are off by default.

Review SNAPSHOT_MANIFEST.json and SNAPSHOT_REVIEW.md before initializing Git.
