# Natural Language CRM MVP 2: follow-up queries

Authorized owners can ask in Chinese or English:

- 今天有哪些客户需要跟进？ / Who should I follow up with today?
- 明天需要联系谁？ / Who should I follow up with tomorrow?
- 哪些客户已经逾期？ / Show overdue clients.

The application uses `DAILY_BRIEF_TIMEZONE` (default `America/New_York`) for
conversational queries, manual Daily Brief, and scheduled Daily Brief. Tomorrow
means the next calendar date there; overdue means strictly before today.

Responses contain the client's recorded name, due date, status, and a deterministic
suggestion based on whether that date is today, tomorrow, or overdue. Missing
statuses show `unknown`. Suggestions do not infer appointments, communication
history, or requirements. Paused and closed records remain included if their
follow-up date matches, consistent with existing Daily Brief behavior; review
whether contact is appropriate. Malformed/missing dates are skipped without repair.
Long results are split into Telegram-sized messages.

These are read-only text queries. They do not change XML, send email, or create
schedules. They reuse `build_daily_brief` classification and date parsing.
Authorization still runs first. Recognized read-only follow-up questions bypass
tour guidance without ending the tour; numbered tour replies still work. Queries
are recognized before general client lookups/updates and legacy property/town handling. As with an MVP 1 lookup,
a new query supersedes any pending conversational write preview; a later `confirm`
cannot approve that old preview. Slash commands and voice flows are unchanged.

## Manual verification (not performed automatically)

Use the existing bot process only when ready; do not start a second instance.
Use dedicated synthetic clients, not actual customers. Record their original
follow-up dates so they can be restored. Follow-up questions also work during `/tour`;
cancel the tour before testing other text CRM actions.

1. In the configured application timezone, choose explicit dates for today,
   tomorrow, and yesterday. Use MVP 1 preview/confirmation to assign these dates
   to three dedicated test records; keep their statuses known.
2. Ask the three Chinese questions above, then their English equivalents.
   Verify the expected synthetic record, due date, and status in each response.
   Existing real records may also appear; do not modify them for this test.
3. Compare today's/overdue sections with `/daily_brief`. Tomorrow's query must
   exclude today's and yesterday's test records.
4. From an unauthorized user/chat, verify queries produce no CRM response.
5. Preview a test status update, then ask a follow-up question. Verify a subsequent
   `confirm` does not save that superseded status change.
6. Verify queries themselves do not alter test records or send email. Restore
   the test records' original dates via explicit MVP 1 preview/confirmation.

No-results and malformed-date cases are covered offline without altering live
records. Run `.venv-arm64/bin/python -B run_safe_tests.py` for the full isolated
suite, including fixed-clock timezone and daylight-saving boundary tests.

## Routing regression retest

After loading the updated code through your existing single-instance deployment
procedure, open a private chat with the bot (do not launch an additional poller):

1. Send `/tour`, then `今天有哪些客户需要跟进？`. Expect a dated follow-up
   response or an explicit no-results response instead of a tour prompt.
2. Send `今天哪些客户需要跟进` without punctuation. Expect the same query result.
3. Send `2`. The tour topic should still work. Then send `/cancel_tour`.
4. Send `Who should I follow up with today?`, then `/daily_brief`; compare today's
   recorded follow-ups. These steps make no CRM writes or email deliveries.

Offline dispatch tests use actual PTB command/message filters and
`Application.process_update()` with initialization, polling, and replies mocked.
The original punctuated question already replied outside a tour in the inspected
code. Complete live silence was not reproduced offline. If private-chat tests
work but plain group messages do not, investigate Telegram group privacy/delivery
settings separately; no live Telegram settings or APIs were inspected or changed.

## Voice follow-up questions

Telegram voice messages now use the same deterministic read-only follow-up query
route after transcription, before legacy voice AI intent extraction or draft
revision. Existing voice updates and slash confirmations remain unchanged. Only
recognized read-only follow-up questions take the new route; speaking `confirm`
does not approve an MVP 1 text preview. During an active tour, a recognized query
can be answered without ending the tour, and spoken numeric selections 1–5 can
select a topic. Text tour numeric replies are unchanged.

Voice handling logs only fixed stage/failure labels: received, downloaded,
transcribed, followup_routed, reply_sent, tour_reply_sent, legacy_routed; failures
are download, transcription, routing, empty_transcript, or reply. No transcripts,
audio, identifiers, client details, exception text, credentials, or URLs are logged.
Friendly error replies are attempted where delivery is possible. Voice still
requires the existing transcription integration; text follow-up queries do not.

### Live voice retest (operator only; not run during implementation)

1. Load the updated code using your normal single-instance deployment procedure;
   do not launch another poller. Open a private chat with the bot.
2. Record `今天哪些客户需要跟进`. Expect the same dated result/no-results response
   as typing that question. Logs should progress through received, downloaded,
   transcribed, followup_routed, and reply_sent, with no transcript content.
3. Record `明天需要联系谁？` and `哪些客户已经逾期？`; verify their date categories.
4. Record `Who should I follow up with today?`, `Who should I follow up with tomorrow?`,
   and `Show overdue clients.`; compare with equivalent text queries and Daily Brief.
5. Send `/tour`, repeat a spoken follow-up query, then speak `2` (if transcribed as
   a digit) or type `2`. Verify the tour topic still works; send `/cancel_tour`.
6. Verify queries did not change any client fields or send emails. If a response
   fails, use the fixed stage/failure logs to distinguish download, transcription,
   and routing. Review transcription configuration privately if that stage fails;
   never paste credentials or customer/audio content into logs.

The pre-fix offline reproduction reached legacy voice parsing and echoed the
transcript rather than answering the question. Complete live silence was not
reproduced offline; the new stage diagnostics identify upstream failures safely.

## Chinese overdue follow-up wording

Text and transcribed speech share these client-qualified overdue synonyms:
`哪些客户过期了`, `哪些客户已经过期`, `哪些客户逾期了`,
`哪些客户需要补跟进`, and `哪些客户错过了跟进日期` (including corresponding
traditional-Chinese forms). All mean CRM `next_followup` dates strictly before
the application-local current date. They do not refer to expired contracts,
documents, listings, or appointments. Whole-sentence matching rejects unrelated,
negated, mixed-action, and ambiguous expiry questions.

After your usual single-instance deployment, type `哪些客户过期了？`, then record
the same phrase as voice. Repeat with `哪些客户需要补跟进` and
`哪些客户错过了跟进日期`. Each must agree with `Show overdue clients` and return
an explicit no-results answer when applicable. `哪些客户的合同过期了？` must not
produce a CRM overdue-follow-up result. No record changes or emails are expected.
