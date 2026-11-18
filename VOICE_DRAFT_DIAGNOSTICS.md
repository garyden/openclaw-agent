# Temporary synthetic voice draft diagnostics

The live root cause is not yet verified. Do not broaden fuzzy matching or change
customer records based on guesses. Exact Chinese/English example requests still
resolve in offline tests; diagnostic output is evidence for the next change.

## Known clarification sites

- The exact Chinese `请确认完整客户姓名` response is in
  `NaturalCRM._resolve()`: it found partial/fuzzy/ambiguous candidates rather than
  one strict/formatting-exact record. Both draft requests and other CRM intents
  share that site. Complete draft requests enter it through `voice_draft_routed`.
- `NaturalCRM.handle()` in pending-name state emits the different Chinese
  `请输入候选客户的完整姓名` when a clarification reply does not select a candidate.
- No match emits `未找到客户，请提供完整姓名`.
- Legacy `format_ambiguous_client_reply()` emits an English full-name request;
  legacy close-match updates show an English preview/confirmation. These are not
  the same Chinese prompt. Tour input uses its separate numeric guidance reply.

Voice path: registered VOICE filter -> owner/chat guard -> download -> Whisper
transcription -> trim -> shared parse_request -> draft request or pending-draft
routing -> NaturalCRM.handle -> classify_client_match -> clarification or draft.
The shared parser strips an initial polite prefix; it does not silently rewrite
spoken client names. Matching normalization and classification are now exposed
through one shared function used by actual CRM resolution and the synthetic probe.

## Enable without editing .env

Set these two process environment variables in your normal single-instance launch
configuration, privately. Do not paste real IDs or credentials into shared logs:

- `CRM_DRAFT_DIAGNOSTICS_ENABLED=true`
- `CRM_DRAFT_DIAGNOSTICS_DEVELOPER_ID=<one existing authorized developer user ID>`

Both the existing owner and chat allowlists must still authorize that developer.
The mode is OFF by default; missing/malformed settings cannot arm it. It never
adds an authorization bypass. No token configuration is changed.

After loading updated code via the normal existing-instance deployment procedure:

1. Open the developer's allowed private bot chat. Send `/diagnose_voice_draft`.
   A generic acknowledgment arms that chat for one voice message within 120 seconds.
2. Record the same failing request, using only the synthetic `MVP Test Client`.
   Repeat separately for Chinese and English, re-arming before each recording.
3. The probe runs the real parser and matching decision against a fixed in-memory
   synthetic fixture. It does not read CRM XML, call draft AI, send email, or retain
   the transcript. Its Telegram acknowledgment contains no transcript or names.
4. Inspect the `Synthetic draft diagnostic v1` log. Share only this sanitized
   metadata line if assistance is needed. Fields use fixed enums and a token count
   capped at 20; they include routing branch, extraction status, Unicode-normalization
   change, match class, clarification reason, and expected clarification site.
5. The probe is consumed even if audio/transcription later fails. Expired probes
   reply with an expiry message without downloading or reading CRM. Other chats/
   users cannot consume it. Re-arm to repeat; otherwise subsequent voice messages
   use normal behavior. Unset both diagnostic variables after testing.

The report predicts resolution of a fresh request against the synthetic fixture;
it does not describe production CRM contents or another pending conversation. For
example, strict_exact/format_exact plus normal live clarification suggests a
remaining dataset/process-state difference requiring separate evidence. Legacy_voice
or other_crm means the fresh transcript did not extract as a follow-up draft. A
fuzzy result with a larger candidate token count can indicate recipient extraction
absorbed other words, but do not infer the exact words from metadata.

The fixture cannot reveal actual duplicates or changed capitalization in a live
CRM store. No claims about those records are made. No additional matching-policy
fix has been applied because the exact live transcript is unknown.

## Local-only exact inspection

`inspect_synthetic_transcript_locally(text, inspector)` is an offline/test-only
helper. It calls a supplied inspector with the exact synthetic text and extracted
recipient in local memory, then returns only sanitized analysis metadata. It has
no automatic console/file logging, storage, Telegram replies, or API calls and is
never called by the Telegram handler. Tests verify this separation.

Use it in a local synthetic test with a debugger callback to inspect variables.
Keep raw text out of shell arguments, test assertion messages, shared output,
terminal recordings, and logging callbacks. The probe intentionally provides no
mechanism to retrieve or persist raw live transcripts. A manually supplied local
fixture is not proof of the real ASR output.

## Offline verification

`.venv-arm64/bin/python -B run_safe_tests.py`
`git diff --check`

Tests reproduce the same clarification site with a deliberately constructed
synthetic request whose recipient extraction includes an extra word. This is a
reproducer of the branch, not a claim that the live transcription contains that
word. Existing CRM, Tour, birthday, voice updates, and follow-up regressions remain
in the full suite. No live test or external API call is made by the implementation.
