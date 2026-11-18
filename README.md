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

No application has been started as part of the snapshot preparation. Dependency
installation and live bot operation are separate deliberate operator actions.
Before any live use, create local configuration from .env.example. Existing shell
variables take precedence. Owner AND chat allowlists are required. The optional
config/agent_profile.example.json is generic; its private runtime copy belongs at
config/agent_profile.json and is ignored. Never commit real configuration or data.

## Data isolation and operational limitations

Default XML paths are based on the location of these exported modules and point
to this snapshot's own memory/memory.xml. No original production path or data is
copied. The safe test runner blocks its .env/XML stores and network access; tests
use temporary XML and mocked services.

Development/testing/production environment selection is NOT implemented. Default
CRM and legacy property memory share one XML path per checkout. Safe tests are
isolated, but arbitrary manual scripts or another bot process can use that same
checkout-local file. Do not place production data in a development checkout, use
symlinks to production stores, or run more than one process against a store. A
separate reviewed configuration change is required for enforced environment/data
root separation. This snapshot does not claim that production isolation is complete.

The safe suite intentionally excludes test_fetch.py: importing that module can
fetch market data and write a cache. Do not use unrestricted test discovery.
Market CSV/raw caches are omitted; market analysis may need a deliberate data
setup/fetch before live use. No live API compatibility was checked during export.
Legacy property deletion still acts immediately for authorized users; no new
safety policy or production data migration was introduced by this export.

See NATURAL_CRM_MVP.md, NATURAL_CRM_MVP2.md, NATURAL_EMAIL_DRAFT_MVP3_1.md, and
VOICE_DRAFT_DIAGNOSTICS.md for feature scope and operator-only retest instructions.
Draft text is AI-assisted and requires human review. New follow-up drafts never
enter the existing birthday send queue. Synthetic diagnostics are off by default.

Review SNAPSHOT_MANIFEST.json and SNAPSHOT_REVIEW.md before initializing Git.
