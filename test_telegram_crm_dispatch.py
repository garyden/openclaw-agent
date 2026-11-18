"""Exercise real PTB filters/Application.process_update offline, with temporary CRM."""
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import json
import unittest
from unittest.mock import AsyncMock, patch

from telegram import Chat, Message, MessageEntity, Update, User, Voice
from telegram.ext import Application, ApplicationBuilder, ExtBot

from client_manager import ClientManager
from natural_crm import NaturalCRM, parse_request, draft_name_matches
from voice_draft_diagnostics import VoiceDraftDiagnostics, analyze_synthetic_transcript

TODAY = date(2026, 11, 14)
ENV = {'TELEGRAM_OWNER_IDS': '7', 'TELEGRAM_ALLOWED_CHAT_IDS': '70'}
OVERDUE_VARIANTS = ['哪些客户过期了', '哪些客户已经过期', '哪些客户逾期了',
                    '哪些客户需要补跟进', '哪些客户错过了跟进日期',
                    '哪些客戶已經過期', '哪些客戶需要補跟進', '哪些客戶錯過了跟進日期']


class TelegramCRMDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import bot
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'memory.xml'
        self.crm = ClientManager(str(self.path))
        self.crm.add_client(name='Dispatch Test Client', status='active', next_followup=TODAY.isoformat())
        self.crm.add_client(name='Voice Tomorrow Test', status='touring', next_followup='2026-11-15')
        self.crm.add_client(name='Voice Overdue Test', status='paused', next_followup='2026-11-13')
        self.crm.add_client(name='John Smith', email='john@example.com', status='touring')
        self.crm.add_client(name='John Lee', email='lee@example.com', status='active')
        self.crm.add_client(name='No Email Test', status='active')
        self.crm.add_client(name='MVP Test Client', email='mvp@example.com', status='touring')
        self.before = self.path.read_bytes()
        self.handler = NaturalCRM(clock=lambda: 100, today_provider=lambda: TODAY)
        self.probe_time = 100
        self.probe = VoiceDraftDiagnostics(clock=lambda: self.probe_time)
        self.patches = [patch.dict('os.environ', ENV, clear=True), patch('bot.initialize_runtime'),
                        patch('bot.TOKEN', '123456:synthetic-token'), patch('bot.crm', self.crm),
                        patch('bot.natural_crm', self.handler), patch('bot.voice_draft_diagnostics', self.probe),
                        patch('bot.pending_tours', set()),
                        patch('bot.pending_email_drafts', {}), patch('bot.register_automatic_daily_brief'),
                        patch('daily_brief.application_today', return_value=TODAY)]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.forbidden = []
        for target in ['email_sender.send_email', 'email_sender.smtplib.SMTP', 'bot.send_email', 'bot.get_openai_client', 'bot.handle_ai_debug',
                       'bot.handle_memory_commands', 'bot.handle_property_analysis',
                       'bot.handle_property_queries', 'bot.handle_property_management',
                       'bot.handle_town_commands', 'bot.revise_email_draft_with_openai']:
            patcher = patch(target, side_effect=AssertionError('Unexpected fallback or external operation'))
            self.forbidden.append(patcher.start())
            self.addCleanup(patcher.stop)
        for method in ['_save_tree', 'update_client', 'delete_client', 'add_client']:
            patcher = patch.object(self.crm, method, side_effect=AssertionError('Read-only dispatch wrote CRM'))
            self.forbidden.append(patcher.start())
            self.addCleanup(patcher.stop)
        reply = patch.object(Message, 'reply_text', new_callable=AsyncMock)
        self.reply = reply.start()
        self.addCleanup(reply.stop)
        initialize = patch.object(ExtBot, 'initialize', new_callable=AsyncMock)
        initialize.start()
        self.addCleanup(initialize.stop)
        # main() registers the actual handlers onto an actual Application. Polling is mocked.
        builder = ApplicationBuilder().updater(None)
        with (patch('bot.ApplicationBuilder', return_value=builder),
              patch.object(Application, 'run_polling', autospec=True) as run_polling):
            bot.main()
            self.app = run_polling.call_args.args[0]
        object.__setattr__(self.app.bot, '_bot_user', User(999, 'Test Bot', True, username='crm_dispatch_test'))
        await self.app.initialize()
        self.addAsyncCleanup(self.app.shutdown)
        self.number = 0

    async def asyncTearDown(self):
        self.assertEqual(self.before, self.path.read_bytes())
        for mocked in self.forbidden:
            mocked.assert_not_called()

    async def dispatch(self, text, user=7, chat=70, voice=False):
        self.number += 1
        self.reply.reset_mock()
        entities = [MessageEntity(MessageEntity.BOT_COMMAND, 0, len(text.split()[0]))] if text and text.startswith('/') else None
        message = Message(message_id=self.number, date=datetime(2026, 11, 14, tzinfo=timezone.utc),
                          chat=Chat(chat, Chat.PRIVATE), from_user=User(user, 'Test Owner', False),
                          text=text, entities=entities,
                          voice=Voice('synthetic-audio', 'synthetic-unique', 1) if voice else None)
        message.set_bot(self.app.bot)
        update = Update(self.number, message=message)
        update.set_bot(self.app.bot)
        await self.app.process_update(update)
        return ''.join(call.args[0] for call in self.reply.await_args_list)

    async def test_both_reported_questions_through_real_dispatch(self):
        for text in ['今天有哪些客户需要跟进？', '今天哪些客户需要跟进']:
            with self.subTest(text=text):
                reply = await self.dispatch(text)
                self.assertIn('Today (2026-11-14)', reply)
                self.assertIn('Dispatch Test Client', reply)
                self.assertIn('Due: 2026-11-14', reply)
                self.assertIn('Status: active', reply)

    async def test_read_only_questions_work_during_tour_and_tour_numbers_still_work(self):
        self.assertIn('five things', await self.dispatch('/tour'))
        for text in ['今天有哪些客户需要跟进？', '今天哪些客户需要跟进']:
            self.assertIn('Today (2026-11-14)', await self.dispatch(text))
        self.assertIn('Find and update clients', await self.dispatch('2'))
        self.assertIn('Tour finished', await self.dispatch('/cancel_tour'))

    async def test_natural_variants_dispatch_as_queries_not_updates_or_properties(self):
        for text, label in [
            ('今天需要跟进哪些客户？', 'Today'),
            ('今天 哪些 客户 需要 跟进', 'Today'),
            ('请查看逾期客户', 'Overdue'),
            ('明天哪些客户需要联系', 'Tomorrow'),
            ('明天需要聯繫誰？', 'Tomorrow'),
            ('Who should I follow up with today?', 'Today'),
            ('Which clients need follow-up today?', 'Today'),
            ('Show me the follow-ups for tomorrow.', 'Tomorrow'),
            ('Who needs follow-up tomorrow?', 'Tomorrow'),
            ('Show overdue clients.', 'Overdue'),
        ]:
            with self.subTest(text=text):
                reply = await self.dispatch(text)
                self.assertIn(label, reply)
                self.assertIn('no changes or delivery', reply)
                self.assertFalse(self.handler.pending)

    async def test_no_results_always_replies_for_both_questions(self):
        with patch.object(self.crm, 'list_clients', return_value=[]):
            for text in ['今天有哪些客户需要跟进？', '今天哪些客户需要跟进']:
                reply = await self.dispatch(text)
                self.assertIn('No matching follow-ups', reply)

    async def test_unauthorized_real_dispatch_never_reads_or_replies(self):
        with patch.object(self.crm, 'list_clients', side_effect=AssertionError('Unauthorized read')):
            for text in ['今天有哪些客户需要跟进？', '今天哪些客户需要跟进', '/tour']:
                for user, chat in [(8, 70), (7, 80)]:
                    self.assertEqual(await self.dispatch(text, user, chat), '')

    async def test_slash_daily_brief_and_preview_cancel_still_dispatch(self):
        self.assertIn('Dispatch Test Client', await self.dispatch('/daily_brief'))
        self.assertIn('Update preview', await self.dispatch('set client Dispatch Test Client status paused'))
        self.assertIn('Canceled', await self.dispatch('cancel'))
        self.assertIn('No update preview', await self.dispatch('confirm'))

    async def test_query_exception_returns_sanitized_reply(self):
        with patch('natural_crm.build_followup_query', side_effect=RuntimeError('synthetic failure')):
            self.assertEqual(await self.dispatch('今天有哪些客户需要跟进？'),
                             'Could not process this request. Please try again.')

    async def test_voice_followup_transcript_reuses_read_only_router(self):
        import bot
        audio = SimpleNamespace(download_to_drive=AsyncMock())
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=audio)),
              patch('bot.transcribe_voice_file', return_value='今天哪些客户需要跟进'),
              patch('bot.extract_voice_intent_with_openai', return_value={'intent': 'unknown'}) as extract,
              patch('bot.extract_voice_client_update_with_openai', return_value=None) as legacy):
            reply = await self.dispatch(None, voice=True)
        self.assertIn('Today (2026-11-14)', reply)
        self.assertIn('Dispatch Test Client', reply)
        extract.assert_not_called()
        legacy.assert_not_called()

    async def test_voice_queries_today_tomorrow_overdue_in_both_languages(self):
        audio = SimpleNamespace(download_to_drive=AsyncMock())
        for transcript, label, expected in [
            ('今天哪些客户需要跟进', 'Today', 'Dispatch Test Client'),
            ('Who should I follow up with today?', 'Today', 'Dispatch Test Client'),
            ('明天需要联系谁？', 'Tomorrow', 'Voice Tomorrow Test'),
            ('Who should I follow up with tomorrow?', 'Tomorrow', 'Voice Tomorrow Test'),
            ('哪些客户已经逾期？', 'Overdue', 'Voice Overdue Test'),
            ('Show overdue clients.', 'Overdue', 'Voice Overdue Test'),
        ]:
            with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=audio)),
                  patch('bot.transcribe_voice_file', return_value=transcript),
                  patch('bot.extract_voice_intent_with_openai', side_effect=AssertionError('Legacy AI used')) as extract,
                  self.assertLogs('bot', level='INFO') as logs):
                reply = await self.dispatch(None, voice=True)
            self.assertIn(label, reply)
            self.assertIn(expected, reply)
            self.assertIn('no changes or delivery', reply)
            extract.assert_not_called()
            self.assertEqual([record.msg for record in logs.records],
                             ['voice_received', 'voice_downloaded', 'voice_transcribed',
                              'voice_followup_routed', 'voice_reply_sent'])
            for private in [transcript, expected, 'synthetic-audio', 'synthetic-unique']:
                self.assertNotIn(private, '\n'.join(logs.output))

    async def test_voice_no_results_replies_without_writes(self):
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='今天哪些客户需要跟进'),
              patch.object(self.crm, 'list_clients', return_value=[])):
            self.assertIn('No matching follow-ups', await self.dispatch(None, voice=True))

    async def test_voice_query_preserves_tour_and_pending_draft_and_supports_numeric_reply(self):
        import bot
        await self.dispatch('/tour')
        bot.pending_email_drafts[7] = {'client_name': 'Dispatch Test Client',
                                       'draft': {'subject': 'Synthetic', 'body': 'Synthetic draft'}}
        before = dict(bot.pending_email_drafts)
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='今天哪些客户需要跟进'),
              patch('bot.extract_voice_intent_with_openai', side_effect=AssertionError('Unexpected AI')) as extract):
            self.assertIn('Today (2026-11-14)', await self.dispatch(None, voice=True))
            with patch('bot.transcribe_voice_file', return_value='2'):
                self.assertIn('Find and update clients', await self.dispatch(None, voice=True))
            extract.assert_not_called()
        self.assertEqual(bot.pending_email_drafts, before)
        self.assertIn('Find and update clients', await self.dispatch('2'))
        self.assertIn('Tour finished', await self.dispatch('/cancel_tour'))

    async def test_unauthorized_voice_is_rejected_before_download_or_transcription(self):
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(side_effect=AssertionError('Unauthorized download'))) as download,
              patch('bot.transcribe_voice_file', side_effect=AssertionError('Unauthorized transcription')) as transcribe,
              patch.object(self.crm, 'list_clients', side_effect=AssertionError('Unauthorized CRM read'))):
            for user, chat in [(8, 70), (7, 80)]:
                self.assertEqual(await self.dispatch(None, user=user, chat=chat, voice=True), '')
            download.assert_not_awaited()
            transcribe.assert_not_called()

    async def test_voice_download_and_transcription_failures_are_sanitized_and_reply(self):
        for stage in ['get_file', 'download_to_drive', 'transcription']:
            audio = SimpleNamespace(download_to_drive=AsyncMock())
            get_file = AsyncMock(return_value=audio)
            failure = RuntimeError('synthetic-private-detail')
            if stage == 'get_file':
                get_file.side_effect = failure
            if stage == 'download_to_drive':
                audio.download_to_drive.side_effect = failure
            with (patch.object(ExtBot, 'get_file', new=get_file),
                  patch('bot.transcribe_voice_file', side_effect=failure) as transcribe,
                  self.assertLogs('bot', level='INFO') as logs):
                reply = await self.dispatch(None, voice=True)
            expected = 'voice_transcription_failed' if stage == 'transcription' else 'voice_download_failed'
            self.assertEqual(logs.records[-1].msg, expected)
            self.assertNotIn('synthetic-private-detail', '\n'.join(logs.output) + reply)
            self.assertIn('try again', reply.casefold())
            if stage != 'transcription':
                transcribe.assert_not_called()

    async def test_voice_empty_transcript_replies_and_does_not_route(self):
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='   '),
              patch('bot.extract_voice_intent_with_openai') as extract,
              self.assertLogs('bot', level='INFO') as logs):
            self.assertIn('could not recognize any text', await self.dispatch(None, voice=True))
        extract.assert_not_called()
        self.assertEqual(logs.records[-1].msg, 'voice_empty_transcript')

    async def test_voice_query_routing_failure_returns_friendly_reply(self):
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='Show overdue clients'),
              patch('natural_crm.build_followup_query', side_effect=RuntimeError('synthetic-private-detail')),
              self.assertLogs('bot', level='INFO') as logs):
            reply = await self.dispatch(None, voice=True)
        self.assertEqual(reply, 'Could not process the voice message. Please try again.')
        self.assertEqual(logs.records[-1].msg, 'voice_routing_failed')
        self.assertNotIn('synthetic-private-detail', '\n'.join(logs.output))

    async def test_existing_voice_exact_update_still_uses_existing_crm_update(self):
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='Update client Dispatch Test Client, status paused'),
              patch('bot.extract_voice_intent_with_openai', return_value={
                  'intent': 'update_client', 'client_name': 'Dispatch Test Client', 'fields': {'status': 'paused'}}),
              patch.object(self.crm, 'update_client_from_text', return_value={'name': 'Dispatch Test Client', 'status': 'paused'}) as update):
            reply = await self.dispatch(None, voice=True)
        update.assert_called_once_with('Dispatch Test Client', 'status=paused')
        self.assertIn('Client updated from voice', reply)

    async def test_existing_voice_close_match_update_still_requires_preview_and_cancellation(self):
        import bot
        with (patch('bot.pending_client_actions', {}),
              patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='Update client Dispatch Test Clien, status paused'),
              patch('bot.extract_voice_intent_with_openai', return_value={
                  'intent': 'update_client', 'client_name': 'Dispatch Test Clien', 'fields': {'status': 'paused'}})):
            reply = await self.dispatch(None, voice=True)
            self.assertIn('No client information has been changed yet', reply)
            self.assertEqual(bot.pending_client_actions[7]['kind'], 'update_client')
            self.assertIn('Client update canceled', await self.dispatch('/cancel_client_action'))
            self.assertFalse(bot.pending_client_actions)

    async def test_voice_reply_failure_is_categorized_without_private_details(self):
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='Show overdue clients'),
              self.assertLogs('bot', level='INFO') as logs):
            self.reply.side_effect = RuntimeError('synthetic-private-reply-failure')
            await self.dispatch(None, voice=True)
        self.assertEqual(self.reply.await_count, 2)  # Normal response plus friendly fallback attempt.
        self.assertIn('voice_reply_failed', [record.msg for record in logs.records])
        self.assertNotIn('synthetic-private-reply-failure', '\n'.join(logs.output))

    async def test_overdue_synonyms_dispatch_for_text_and_voice_during_tour(self):
        await self.dispatch('/tour')
        audio = SimpleNamespace(download_to_drive=AsyncMock())
        for text in OVERDUE_VARIANTS:
            for voice in [False, True]:
                with (self.subTest(text=text, voice=voice),
                      patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=audio)),
                      patch('bot.transcribe_voice_file', return_value=text + '？'),
                      patch('bot.extract_voice_intent_with_openai', side_effect=AssertionError('Read-only question reached legacy AI')) as extract):
                    reply = await self.dispatch(None if voice else text, voice=voice)
                    self.assertIn('Overdue (2026-11-14)', reply)
                    self.assertIn('Voice Overdue Test', reply)
                    self.assertIn('Due: 2026-11-13', reply)
                    self.assertIn('Status: paused', reply)
                    self.assertNotIn('Dispatch Test Client', reply)
                    self.assertNotIn('Voice Tomorrow Test', reply)
                    self.assertFalse(self.handler.pending)
                    extract.assert_not_called()
        self.assertIn('Find and update clients', await self.dispatch('2'))
        await self.dispatch('/cancel_tour')

    async def test_overdue_synonyms_always_reply_when_none_are_due(self):
        audio = SimpleNamespace(download_to_drive=AsyncMock())
        with patch.object(self.crm, 'list_clients', return_value=[]):
            for text in OVERDUE_VARIANTS:
                for voice in [False, True]:
                    with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=audio)),
                          patch('bot.transcribe_voice_file', return_value=text)):
                        self.assertIn('No matching follow-ups',
                                      await self.dispatch(None if voice else text, voice=voice))

    async def test_unrelated_or_ambiguous_expiry_is_not_a_followup_query(self):
        texts = ['什么东西过期了？', '哪些合同过期了？', '哪些客户的合同过期了？',
                 '哪些客户的证件已经过期？', '哪些客户的房源过期了？',
                 '哪些客户明天过期？', '哪些客户过期了并修改状态',
                 '哪些客户错过了看房日期？', '哪些客户需要补跟进并发送邮件',
                 '哪些客户没有过期？', '哪些客户没有错过跟进日期？',
                 'Which leases have expired?']
        audio = SimpleNamespace(download_to_drive=AsyncMock())
        # Preserve normal fallback behavior while ensuring no follow-up classification or writes.
        with (patch('natural_crm.build_followup_query', side_effect=AssertionError('Unrelated expiry classified')) as business,
              patch('bot.handle_memory_commands', new=AsyncMock(return_value=False)),
              patch('bot.handle_property_analysis', new=AsyncMock(return_value=False)),
              patch('bot.handle_property_queries', new=AsyncMock(return_value=False)),
              patch('bot.handle_property_management', new=AsyncMock(return_value=False)),
              patch('bot.handle_town_commands', new=AsyncMock(return_value=False)),
              patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=audio)),
              patch('bot.extract_voice_intent_with_openai', return_value={'intent': 'unknown'}),
              patch('bot.extract_voice_client_update_with_openai', return_value=None)):
            for text in texts:
                with self.subTest(text=text):
                    self.assertIsNone(parse_request(text))
                    for voice in [False, True]:
                        with patch('bot.transcribe_voice_file', return_value=text):
                            reply = await self.dispatch(None if voice else text, voice=voice)
                            self.assertNotIn('Overdue (', reply)
            business.assert_not_called()

    async def test_overdue_synonyms_still_require_authorization_for_text_and_voice(self):
        with (patch.object(self.crm, 'list_clients', side_effect=AssertionError('Unauthorized CRM read')),
              patch.object(ExtBot, 'get_file', new=AsyncMock()) as download,
              patch('bot.transcribe_voice_file') as transcribe):
            for text in OVERDUE_VARIANTS:
                for user, chat in [(8, 70), (7, 80)]:
                    self.assertEqual(await self.dispatch(text, user=user, chat=chat), '')
                    self.assertEqual(await self.dispatch(None, user=user, chat=chat, voice=True), '')
            download.assert_not_called()
            transcribe.assert_not_called()

    def mock_followup_model(self, draft=None):
        key = patch.dict('os.environ', {'OPENAI_API_KEY': 'synthetic-key'})
        key.start()
        self.addCleanup(key.stop)
        patcher = patch('email_generator.OpenAI')
        model = patcher.start()
        self.addCleanup(patcher.stop)
        draft = draft or {'subject': 'Scheduling another showing',
                          'body': 'Hi John,\n\nWould you have time for another showing?\n\nBest,\nYour agent'}
        model.return_value.responses.create.return_value.output_text = json.dumps(draft)
        return model

    async def test_followup_email_text_and_voice_are_bilingual_draft_only(self):
        import bot
        model = self.mock_followup_model()
        audio = SimpleNamespace(download_to_drive=AsyncMock())
        for text in ['帮我给 John Smith 写封邮件，问问他最近有没有时间继续看房',
                     'Draft a follow-up email to John Smith about scheduling another showing']:
            for voice in [False, True]:
                with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=audio)),
                      patch('bot.transcribe_voice_file', return_value=text),
                      patch('bot.extract_voice_intent_with_openai', side_effect=AssertionError('Draft reached legacy AI')) as extract):
                    reply = await self.dispatch(None if voice else text, voice=voice)
                self.assertIn('DRAFT — NOT SENT', reply)
                self.assertIn('Recipient / 收件人: John Smith', reply)
                self.assertIn('john@example.com', reply)
                self.assertIn('Subject: Scheduling another showing', reply)
                self.assertIn('Would you have time for another showing?', reply)
                self.assertFalse(self.handler.pending)
                self.assertFalse(bot.pending_email_drafts)
                extract.assert_not_called()
        self.assertEqual(model.call_count, 4)
        self.assertIn('No pending email draft', await self.dispatch('/send_last_email'))
        self.assertIn('No pending email draft', await self.dispatch('/confirm_send_email'))

    async def test_followup_draft_ambiguous_name_clarifies_without_guessing(self):
        model = self.mock_followup_model()
        for voice in [False, True]:
            text = 'Draft a follow-up email to John about another showing'
            with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
                  patch('bot.transcribe_voice_file', return_value=text)):
                before_calls = model.call_count
                reply = await self.dispatch(None if voice else text, voice=voice)
                self.assertIn('Enter the exact client name', reply)
                self.assertIn('John Smith', reply)
                self.assertIn('John Lee', reply)
                self.assertEqual(model.call_count, before_calls)
                if voice:
                    with patch('bot.transcribe_voice_file', return_value='John Smith'):
                        reply = await self.dispatch(None, voice=True)
                else:
                    reply = await self.dispatch('John Smith')
                self.assertIn('DRAFT — NOT SENT', reply)
                self.assertEqual(model.call_count, before_calls + 1)

    async def test_followup_draft_zero_matches_and_empty_crm_never_generate(self):
        model = self.mock_followup_model()
        for text in ['给 Nobody Test 写封邮件，问问是否有空',
                     'Draft a follow-up email to Nobody Test about availability']:
            self.assertIn('Client not found', await self.dispatch(text))
        with patch.object(self.crm, 'list_clients', return_value=[]):
            self.assertIn('Client not found', await self.dispatch('Draft an email to John Smith about availability'))
        model.assert_not_called()

    async def test_followup_draft_chinese_voice_without_punctuation(self):
        self.mock_followup_model()
        text = '帮我给John Smith写封邮件问问他最近有没有时间继续看房'
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value=text)):
            self.assertIn('DRAFT — NOT SENT', await self.dispatch(None, voice=True))

    async def test_followup_draft_missing_email_still_previews(self):
        self.mock_followup_model()
        reply = await self.dispatch('给No Email Test写封邮件，问问是否方便继续看房')
        self.assertIn('DRAFT — NOT SENT', reply)
        self.assertIn('MISSING / 未填写', reply)

    async def test_followup_draft_clarification_is_scoped_cancellable_and_expires(self):
        model = self.mock_followup_model()
        await self.dispatch('Draft an email to John about availability')
        # A different chat cannot resolve another chat's recipient selection.
        with patch.dict('os.environ', {'TELEGRAM_OWNER_IDS': '7,8', 'TELEGRAM_ALLOWED_CHAT_IDS': '70,80'}):
            for user, chat in [(7, 80), (8, 70)]:
                self.assertFalse(await self.handler.handle(self.event_for_scope('John Smith', user, chat), self.crm, 'John Smith'))
        model.assert_not_called()
        self.assertIn((7, 70), self.handler.pending)
        await self.dispatch('cancel')
        self.assertFalse(self.handler.pending)
        await self.dispatch('Draft an email to John about availability')
        self.handler.clock = lambda: 401
        self.assertIn('expired', await self.dispatch('John Smith'))
        self.assertFalse(self.handler.pending)
        model.assert_not_called()

    @staticmethod
    def event_for_scope(text, user, chat):
        return SimpleNamespace(effective_user=SimpleNamespace(id=user, is_bot=False),
                               effective_chat=SimpleNamespace(id=chat),
                               message=SimpleNamespace(text=text, reply_text=AsyncMock()))

    async def test_followup_draft_unauthorized_text_and_voice_do_not_read_or_generate(self):
        model = self.mock_followup_model()
        with (patch.object(self.crm, 'list_clients', side_effect=AssertionError('Unauthorized CRM read')),
              patch.object(ExtBot, 'get_file', new=AsyncMock()) as download):
            for user, chat in [(8, 70), (7, 80)]:
                self.assertEqual(await self.dispatch('Draft an email to John Smith about availability', user=user, chat=chat), '')
                self.assertEqual(await self.dispatch(None, user=user, chat=chat, voice=True), '')
        download.assert_not_called()
        model.assert_not_called()

    async def test_followup_draft_tour_and_priority_do_not_change_existing_flows(self):
        import bot
        model = self.mock_followup_model()
        bot.pending_email_drafts[7] = {'client_name': 'Existing Birthday Test',
                                       'draft': {'subject': 'Birthday', 'body': 'Synthetic birthday draft'}}
        before = dict(bot.pending_email_drafts)
        await self.dispatch('/tour')
        self.assertIn('Enter the exact client name', await self.dispatch('Draft an email to John about availability'))
        self.assertIn('DRAFT — NOT SENT', await self.dispatch('John Smith'))
        self.assertIn('Find and update clients', await self.dispatch('2'))
        self.assertEqual(bot.pending_email_drafts, before)
        self.assertIn('Overdue', await self.dispatch('Show overdue clients'))
        self.assertEqual(model.call_count, 1)
        await self.dispatch('/cancel_tour')
        self.assertIn('Update preview', await self.dispatch('set client John Smith status active'))
        self.assertIn('Canceled', await self.dispatch('cancel'))
        self.assertIn('Dispatch Test Client', await self.dispatch('/daily_brief'))

    async def test_followup_draft_missing_purpose_and_generation_failure_are_safe(self):
        model = self.mock_followup_model()
        self.assertIn('What should the draft ask about', await self.dispatch('Draft an email to John Smith'))
        model.assert_not_called()
        self.assertIn('DRAFT — NOT SENT', await self.dispatch('Ask about another showing'))
        model.return_value.responses.create.side_effect = RuntimeError('synthetic-private-provider-error')
        with self.assertLogs('bot', level='ERROR') as logs:
            reply = await self.dispatch('Draft an email to John Smith about availability')
        self.assertIn('Could not generate the draft', reply)
        self.assertNotIn('synthetic-private-provider-error', reply + '\n'.join(logs.output))
        self.assertFalse(self.handler.pending)

    async def test_followup_draft_long_body_is_fully_displayed_without_private_logs(self):
        body = 'An English draft sentence. ' * 200
        self.mock_followup_model({'subject': 'Follow-up', 'body': body})
        with self.assertNoLogs('bot', level='DEBUG'):
            reply = await self.dispatch('Draft an email to John Smith about availability')
        header = 'DRAFT — NOT SENT / 草稿，未发送\n'
        self.assertIn(body.strip(), reply.replace(header, ''))
        self.assertGreater(self.reply.await_count, 1)
        for call in self.reply.await_args_list:
            self.assertTrue(call.args[0].startswith(header))
            self.assertLessEqual(len(call.args[0].encode('utf-16-le')) // 2, 4096)

    def test_draft_parser_does_not_capture_queries_updates_or_birthday_intents(self):
        self.assertEqual(parse_request('Who should I follow up with today?')['intent'], 'followup_query')
        self.assertEqual(parse_request('update client John Smith, status touring')['intent'], 'update')
        self.assertIsNone(parse_request('Generate a birthday email for John Smith'))
        self.assertIsNone(parse_request('/generate_birthday_email John Smith'))
        self.assertIsNone(parse_request('Send an email to John Smith'))

    async def test_voice_draft_mvp_recipient_formatting_in_chinese_and_english(self):
        model = self.mock_followup_model()
        transcripts = [
            '帮我给 MVP Test Client 写封邮件，问问他最近有没有时间继续看房',
            'Draft a follow-up email to MVP Test Client about scheduling another showing',
            '帮我给 M V P Test Client 写封邮件，问问他最近有没有时间继续看房',
            'Draft a follow-up email to M.V.P. Test Client about scheduling another showing',
            'Draft a follow-up email to MVP Test Client, about scheduling another showing',
            '给“MVP Test Client”写封邮件，问问他是否有时间继续看房',
        ]
        for transcript in transcripts:
            with (self.subTest(transcript=transcript),
                  patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
                  patch('bot.transcribe_voice_file', return_value=transcript),
                  patch('bot.extract_voice_intent_with_openai', side_effect=AssertionError('Draft reached legacy AI'))):
                reply = await self.dispatch(None, voice=True)
                self.assertIn('DRAFT — NOT SENT', reply)
                self.assertIn('Recipient / 收件人: MVP Test Client', reply)
                self.assertIn('mvp@example.com', reply)
                payload = json.loads(model.return_value.responses.create.call_args.kwargs['input'])
                self.assertEqual(payload['client']['name'], 'MVP Test Client')
                self.assertFalse(self.handler.pending)
        self.assertEqual(model.call_count, len(transcripts))

    async def test_mvp_text_draft_keeps_same_recipient(self):
        model = self.mock_followup_model()
        for text in ['帮我给 MVP Test Client 写封邮件，问问他最近有没有时间继续看房',
                     'Draft a follow-up email to MVP Test Client about scheduling another showing']:
            self.assertIn('Recipient / 收件人: MVP Test Client', await self.dispatch(text))
        self.assertEqual(model.call_count, 2)

    async def test_draft_name_formatting_collisions_remain_ambiguous_for_voice(self):
        model = self.mock_followup_model()
        clients = [{'name': 'MVP Test Client', 'email': 'one@example.com', 'status': 'active'},
                   {'name': 'M V P Test Client', 'email': 'two@example.com', 'status': 'active'}]
        with (patch.object(self.crm, 'list_clients', return_value=clients),
              patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='Draft an email to M.V.P. Test Client about availability')):
            reply = await self.dispatch(None, voice=True)
        self.assertIn('Enter the exact client name', reply)
        self.assertNotIn('DRAFT — NOT SENT', reply)
        model.assert_not_called()
        with patch.object(self.crm, 'list_clients', return_value=clients):
            reply = await self.dispatch('MVP Test Client')
        self.assertIn('Email / 邮箱: one@example.com', reply)
        model.assert_called_once()

    async def test_genuinely_different_voice_name_still_requires_clarification(self):
        model = self.mock_followup_model()
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='Draft an email to MVP Task Client about availability')):
            reply = await self.dispatch(None, voice=True)
        self.assertIn('Enter the exact client name', reply)
        model.assert_not_called()
        # Clarification speech also uses formatting equivalence for the candidate name.
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='M V P Test Client')):
            reply = await self.dispatch(None, voice=True)
        self.assertIn('Recipient / 收件人: MVP Test Client', reply)
        model.assert_called_once()

    def test_draft_name_equivalence_does_not_guess_phonetic_or_compact_names(self):
        for heard in ['M V P Test Client', 'M.V.P. Test Client', 'MVP Test Client,', '“MVP Test Client”']:
            self.assertTrue(draft_name_matches(heard, 'MVP Test Client'))
        for heard in ['MVP Task Client', 'MVP', 'MVPTestClient', 'MVP测试客户']:
            self.assertFalse(draft_name_matches(heard, 'MVP Test Client'))

    async def test_developer_synthetic_diagnostic_actual_voice_dispatch_without_crm_or_ai(self):
        model = self.mock_followup_model()
        cases = [
            ('帮我给 MVP Test Client 写封邮件，问问他最近有没有时间继续看房', 'strict_exact', 'none'),
            ('Draft a follow-up email to M V P Test Client about another showing', 'format_exact', 'none'),
            ('Draft an email to MVP Task Client about another showing', 'fuzzy', 'fuzzy_name'),
            ('Draft an email to MVP about another showing', 'partial', 'partial_name'),
            ('Draft a follow-up email to MVP Test Client asking about another showing', 'fuzzy', 'fuzzy_name'),
            ('Please make an email', 'not_evaluated', 'intent_not_draft'),
        ]
        with patch.dict('os.environ', {'CRM_DRAFT_DIAGNOSTICS_ENABLED': 'true',
                                      'CRM_DRAFT_DIAGNOSTICS_DEVELOPER_ID': '7'}):
            for transcript, matching, reason in cases:
                self.assertIn('armed', await self.dispatch('/diagnose_voice_draft'))
                with (patch.object(self.crm, 'list_clients', side_effect=AssertionError('Diagnostic read real CRM')),
                      patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
                      patch('bot.transcribe_voice_file', return_value=transcript),
                      patch('voice_draft_diagnostics.inspect_synthetic_transcript_locally', side_effect=AssertionError('Local inspector called live')),
                      self.assertLogs('bot', level='INFO') as logs):
                    reply = await self.dispatch(None, voice=True)
                self.assertIn('Synthetic diagnostic complete', reply)
                records = [record for record in logs.records if record.msg == 'draft_diagnostic']
                self.assertEqual(len(records), 1)
                metadata = records[0].diagnostic
                self.assertEqual(metadata['matching'], matching)
                self.assertEqual(metadata['clarification'], reason)
                self.assertNotIn(transcript, reply + '\n'.join(logs.output))
                self.assertNotIn('MVP Test Client', reply + str(metadata))
                self.assertFalse(self.handler.pending)
            model.assert_not_called()

    async def test_diagnostic_off_by_default_and_non_developer_cannot_arm(self):
        self.assertEqual(await self.dispatch('/diagnose_voice_draft'), '')
        with patch.dict('os.environ', {'CRM_DRAFT_DIAGNOSTICS_ENABLED': 'true',
                                      'CRM_DRAFT_DIAGNOSTICS_DEVELOPER_ID': '8'}):
            self.assertEqual(await self.dispatch('/diagnose_voice_draft'), '')
        self.assertIsNone(self.probe._session)
        self.assertIn('five things', await self.dispatch('/tour'))
        self.assertIn('Today', await self.dispatch('今天哪些客户需要跟进'))

    async def test_diagnostic_one_shot_then_normal_voice_draft_behavior(self):
        model = self.mock_followup_model()
        with (patch.dict('os.environ', {'CRM_DRAFT_DIAGNOSTICS_ENABLED': 'true',
                                       'CRM_DRAFT_DIAGNOSTICS_DEVELOPER_ID': '7'}),
              patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value='Draft an email to MVP Test Client about availability')):
            await self.dispatch('/diagnose_voice_draft')
            self.assertIn('Synthetic diagnostic complete', await self.dispatch(None, voice=True))
            model.assert_not_called()
            self.assertIn('DRAFT — NOT SENT', await self.dispatch(None, voice=True))
            model.assert_called_once()

    async def test_synthetic_failing_route_matches_real_clarification_site(self):
        model = self.mock_followup_model()
        # A synthetic reproducer, not a claim about the unknown live transcript.
        transcript = 'Draft a follow-up email to MVP Test Client asking about another showing'
        metadata = analyze_synthetic_transcript(transcript)
        self.assertEqual(metadata['route'], 'natural_draft')
        self.assertEqual(metadata['extraction'], 'complete')
        self.assertEqual(metadata['candidate_tokens'], 4)
        self.assertEqual(metadata['matching'], 'fuzzy')
        self.assertEqual(metadata['site'], 'natural_resolve')
        with (patch.object(ExtBot, 'get_file', new=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock()))),
              patch('bot.transcribe_voice_file', return_value=transcript),
              patch('bot.extract_voice_intent_with_openai', side_effect=AssertionError('Unexpected legacy router'))):
            reply = await self.dispatch(None, voice=True)
        self.assertIn('请确认完整客户姓名', reply)
        model.assert_not_called()

    async def test_expired_voice_diagnostic_does_not_download_or_read_crm(self):
        with patch.dict('os.environ', {'CRM_DRAFT_DIAGNOSTICS_ENABLED': 'true',
                                      'CRM_DRAFT_DIAGNOSTICS_DEVELOPER_ID': '7'}):
            await self.dispatch('/diagnose_voice_draft')
            self.probe_time = 220
            with (patch.object(ExtBot, 'get_file', new=AsyncMock()) as download,
                  patch.object(self.crm, 'list_clients', side_effect=AssertionError('Expired diagnostic read CRM'))):
                self.assertIn('diagnostic expired', await self.dispatch(None, voice=True))
                download.assert_not_called()
            self.assertIsNone(self.probe._session)
