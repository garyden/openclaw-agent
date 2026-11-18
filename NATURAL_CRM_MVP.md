# Natural Language CRM MVP 1

Authorized owners can use ordinary text for name lookup/search, client status,
and next-follow-up dates. Existing slash commands, voice handling, email flows,
and XML schema are unchanged. The new route uses conservative bilingual phrase
matching and the existing client matching/storage code; it makes no OpenAI calls.

| Action | Chinese example | English example |
| --- | --- | --- |
| List | 列出所有客户 | list clients |
| Lookup/search | 查找客户MVP Test Client | find client MVP Test Client |
| Status | 把客户MVP Test Client的状态改为看房中 | update client MVP Test Client, status touring |
| Follow-up | 客户MVP Test Client下次跟进设为2026-12-20 | set client MVP Test Client next follow up to 2026-12-20 |
| Confirm | 确认 | confirm |
| Cancel | 取消 | cancel |

A write previews the full client name, field, and old/new values before saving.
Every new conversational write requires confirmation, even for an exact name.
Partial/fuzzy names require entering the exact displayed candidate name before
showing details or previewing a write. Dates must include a year: YYYY-MM-DD or
YYYY年M月D日. Relative/ambiguous/invalid dates prompt for clarification.

Pending state is separate from legacy voice/email state and keyed by both user
and chat. It expires five minutes after the original request; clarification does
not extend the deadline. Cancel, completion, failed storage, changed records, a
new recognized request, or an unknown reply to a preview invalidate approval.
Expired state is removed on subsequent text interaction. State is memory-only,
so restart also removes it. Replies to an unfinished clarification are consumed
until resolved, canceled, superseded, or expired. `/tour` keeps priority; cancel
the tour to use the CRM conversation.

Only `status` and `next_followup` can be written by this route. No generated
command strings are executed or reparsed. Follow-up changes update the CRM date;
they do not create individual scheduled reminders. Adding/deleting clients,
email sending, arbitrary fields, and open-ended conversation are outside this
MVP. Exact names are required to select search results; pronouns are unsupported.
Legacy property/town behavior remains available outside a pending conversation.

## Manual Telegram check (not run automatically)

Use the existing bot process when ready; do not start a second instance. Use a
dedicated synthetic record named `MVP Test Client`, created deliberately in your
test setup, never an actual customer. Give it a valid initial YYYY-MM-DD follow-up
date and save its initial status/date for restoration.

1. Send `查找客户MVP Test Client`, then `find client MVP Test Client`; check the record.
2. Send `把客户MVP Test Client的状态改为看房中`; verify the before/after preview.
   Reply `取消`; look up the record to verify no change.
3. Send `update client MVP Test Client, status touring`; reply `confirm`.
   Look up the record to verify the status. Repeating `confirm` must do nothing.
4. Send `客户MVP Test Client下次跟进设为明天`. Supply a chosen full test date only
   after the clarification prompt, inspect the preview, then confirm or cancel.
5. Search using an incomplete name. Enter only the exact dedicated test record's
   displayed name when prompted; never select a real customer.
6. Preview another test update, then try confirmation from a different allowed
   chat/user; verify it cannot approve the original action. Wait over five minutes
   and verify that the original preview can no longer be confirmed.
7. Send unrelated text or a plain-text email-send request (no slash commands); verify no record changes or
   emails occur. Check `/tour`, `/cancel_tour`, and existing read-only slash commands.
8. Restore the synthetic record's initial status/date through preview/confirmation.

Offline verification: `.venv-arm64/bin/python -B run_safe_tests.py`.
Tests use temporary XML, synthetic identities, mocked replies/providers, and the
existing safety guard that blocks production XML/configuration and network access.
