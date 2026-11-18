# AI Real Estate Assistant MVP 3.1: follow-up drafts

Authorized agents can type or speak:

- 帮我给 John Smith 写封邮件，问问他最近有没有时间继续看房
- Draft a follow-up email to John Smith about scheduling another showing.
- 给John Smith写封邮件问问他最近有没有时间继续看房 (without punctuation)

## Behavior and boundaries

The existing shared NaturalCRM parser recognizes explicit draft requests after
MVP 2 read-only follow-up questions and before general client lookup/update rules.
Text and transcribed voice use the same matching, clarification, and generation
logic. Existing ClientManager reads and client-reference matching are reused.
An exact full-name match can generate a draft immediately. Partial/fuzzy or
ambiguous names require selection of an exact displayed candidate; missing
clients produce an explanation. Missing purpose prompts for clarification.

The preview shows the recipient name, CRM email (or MISSING), English subject,
and full body. Each Telegram chunk is marked DRAFT — NOT SENT. A missing email
does not block preview. This feature has no delivery endpoint, send button, new
send command, XML write, or persisted draft. It does not populate the existing
sendable birthday draft queue; those separate birthday flows remain unchanged.

Only recipient/purpose clarification lives in memory, keyed by authorized user
and chat, with the existing five-minute expiry. Cancel/new requests clear it;
complete drafts are not retained. Cancellation applies to clarification, not an
already running generation request. Use a fresh complete request for revisions.

Generation reuses email_generator.py's normalization/validation helpers and the
existing OpenAI SDK/model. The model receives the stated purpose, name, status,
and writing style. Areas/requirements are included only when explicitly relevant
to a request about preferences/criteria/areas. Email, phone, address, birthday,
notes, and follow-up dates are not automatically sent as CRM context. Inputs are
JSON data, not generated executable instructions. The prompt requires English,
forbids invented facts/appointments/commitments, and separates desired actions
from established facts. Output must be a valid subject/body pair. Constructor,
API, or schema failures produce safe feedback without raw exception details.

The generation call runs in a worker thread with a 30-second SDK timeout and no
SDK retries. The feature needs configured OpenAI access at runtime; no credentials
or external services are inspected during offline testing. Matching is conservative
phrase recognition, not general chat. English and factual grounding are model
instructions, not an independent semantic fact checker: agents must review drafts.
No client details, draft bodies, or transcripts are logged.

Recognized drafts and their clarification can interrupt tour guidance without
ending the tour; numeric tour replies still work. Other MVP 1 updates retain
preview/confirmation. Spoken follow-up queries still take the MVP 2 route;
legacy voice updates and birthday drafting remain available.

## Manual Telegram retest (not run during implementation)

1. Load updated code using your normal single-instance deployment. Use a private
   chat and dedicated synthetic CRM clients with known names/emails; no real
   customer records need changing for this test.
2. With a synthetic exact match (substitute its full name), type the Chinese
   example and then the English example. Verify recipient/email, English subject,
   full body, and DRAFT — NOT SENT. Inspect for unsupported facts.
3. Record the same requests as voice; verify the same draft-only behavior.
4. Use an ambiguous partial name shared by synthetic records. Verify that no
   draft is generated until the exact candidate name is supplied, by text or voice.
   Try canceling, or wait over five minutes, then repeat the complete request.
5. Use a synthetic client whose email is missing. Verify a draft preview still
   appears with MISSING clearly shown. An unknown name must explain no match.
6. Try a draft during /tour; verify `2` and /cancel_tour still work. Check
   今天哪些客户需要跟进, /daily_brief, and an MVP 1 update preview followed by cancel.
7. Verify client fields remain unchanged and no emails are delivered. This preview
   cannot be sent through existing birthday send commands. Existing pending
   birthday drafts remain separate; do not use their send commands for this test.
8. From an unauthorized user/chat, verify no lookup, draft, or voice download occurs.

Offline: `.venv-arm64/bin/python -B run_safe_tests.py`, then `git diff --check`.

## Voice recipient formatting

Draft recipient resolution first preserves exact stored-name matching. If no
strict match exists, it accepts only unique formatting equivalents through the
existing client-reference normalizer: punctuation/quotes and spelled uppercase
CRM tokens (for example MVP, M V P, or M.V.P.). The same rule applies to draft
clarification replies. Multiple equivalent records still require explicit
selection of a stored full name. Partial, phonetic, translated, or compacted
names are not automatically promoted to exact matches. CRM updates and general
lookup matching are unchanged.

Offline regression tests cover both original Chinese/English requests and
synthetic ASR punctuation/acronym variants through actual voice dispatch. The
literal original requests resolved correctly before this fix; without inspecting
live transcripts, the precise ASR variation in a live failure cannot be confirmed.
