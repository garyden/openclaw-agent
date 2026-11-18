"""Read-only bilingual follow-up queries against synthetic, temporary XML."""
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import daily_brief
from client_manager import ClientManager
from daily_brief import application_today, build_followup_query
from natural_crm import NaturalCRM, parse_request

TODAY = date(2026, 11, 14)
ENV = {'TELEGRAM_OWNER_IDS': '7', 'TELEGRAM_ALLOWED_CHAT_IDS': '70'}


class FollowupQueryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'memory.xml'
        self.crm = ClientManager(str(self.path))
        for name, due, status in [
            ('Today Test', '2026-11-14', 'active'),
            ('明天测试', '2026-11-15', 'touring'),
            ('Overdue Test', '2026-11-13', 'paused'),
            ('Older Test', '2026/11/01', 'closed'),
            ('Future Test', '2026-11-16', 'new_lead'),
            ('Invalid Test', '2026-02-30', 'active'),
            ('Relative Test', 'tomorrow', 'active'),
            ('Missing Test', '', 'active'),
        ]:
            self.crm.add_client(name=name, next_followup=due, status=status)
        self.before = self.path.read_bytes()
        self.handler = NaturalCRM(clock=lambda: 100, today_provider=lambda: TODAY)
        import bot
        patchers = [patch.dict('os.environ', ENV, clear=True), patch('bot.crm', self.crm),
                    patch('bot.natural_crm', self.handler), patch('bot.pending_tours', set()),
                    patch('bot.pending_email_drafts', {})]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.forbidden = []
        for target in ('bot.send_email', 'bot.get_openai_client',
                       'bot.extract_voice_intent_with_openai', 'bot.register_automatic_daily_brief'):
            patcher = patch(target, side_effect=AssertionError('External operation forbidden'))
            self.forbidden.append(patcher.start())
            self.addCleanup(patcher.stop)
        for method in ('update_client', 'delete_client', 'add_client', 'add_clients_batch', '_save_tree'):
            patcher = patch.object(self.crm, method, side_effect=AssertionError('CRM write forbidden'))
            self.forbidden.append(patcher.start())
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.assertEqual(self.before, self.path.read_bytes())
        for mocked in self.forbidden:
            mocked.assert_not_called()

    def event(self, text, user=7, chat=70):
        return SimpleNamespace(effective_user=SimpleNamespace(id=user, is_bot=False),
                               effective_chat=SimpleNamespace(id=chat),
                               message=SimpleNamespace(text=text, reply_text=AsyncMock()))

    async def ask(self, text):
        event = self.event(text)
        import bot
        with (patch('bot.handle_memory_commands', side_effect=AssertionError('Legacy fallback forbidden')),
              patch('bot.handle_property_queries', side_effect=AssertionError('Property routing forbidden')),
              patch('bot.handle_property_analysis', side_effect=AssertionError('Property routing forbidden'))):
            await bot.handle_message(event, None)
        return ''.join(call.args[0] for call in event.message.reply_text.await_args_list)

    async def test_today_bilingual(self):
        for text in ['今天有哪些客户需要跟进？', '今天需要联系谁？',
                     'Who should I follow up with today?', 'Show clients due today.']:
            with self.subTest(text=text):
                reply = await self.ask(text)
                self.assertIn('Today Test', reply)
                self.assertIn('Due: 2026-11-14', reply)
                self.assertIn('Status: active', reply)
                self.assertIn('recorded follow-up due today', reply)
                self.assertNotIn('明天测试', reply)
                self.assertNotIn('Overdue Test', reply)

    async def test_tomorrow_bilingual(self):
        for text in ['明天需要联系谁？', '明天有哪些客户需要跟进？',
                     'Who should I follow up with tomorrow?', 'Please show follow-ups due tomorrow']:
            with self.subTest(text=text):
                reply = await self.ask(text)
                self.assertIn('明天测试', reply)
                self.assertIn('Due: 2026-11-15', reply)
                self.assertIn('Status: touring', reply)
                self.assertIn('prepare for the follow-up due tomorrow', reply)
                self.assertNotIn('Today Test', reply)
                self.assertNotIn('Overdue Test', reply)

    async def test_overdue_bilingual_sorted_and_grounded(self):
        for text in ['哪些客户已经逾期？', '查看逾期客户', 'Show overdue clients.', 'Which clients are overdue?']:
            with self.subTest(text=text):
                reply = await self.ask(text)
                self.assertLess(reply.index('Older Test'), reply.index('Overdue Test'))
                self.assertIn('Due: 2026-11-01', reply)
                self.assertIn('Status: closed', reply)
                self.assertIn('Due: 2026-11-13', reply)
                self.assertIn('Status: paused', reply)
                self.assertIn('reviewing this overdue CRM record', reply)
                self.assertNotIn('Today Test', reply)
                for ungrounded in ['appointment', 'previous conversation', 'requirements', '@']:
                    self.assertNotIn(ungrounded, reply)

    async def test_queries_do_not_log_customer_data(self):
        with self.assertNoLogs('bot', level='DEBUG'):
            await self.ask('今天有哪些客户需要跟进？')

    async def test_empty_results_for_all_scopes_and_languages(self):
        with patch.object(self.crm, 'list_clients', return_value=[]):
            for text in ['今天需要联系谁？', '明天需要联系谁？', '哪些客户已经逾期？',
                         'Show clients due today', 'Show clients due tomorrow', 'Show overdue clients']:
                self.assertIn('No matching follow-ups', await self.ask(text))

    async def test_malformed_and_missing_dates_are_ignored_without_repairs(self):
        for text in ['今天需要联系谁？', '明天需要联系谁？', 'Show overdue clients']:
            reply = await self.ask(text)
            for name in ['Invalid Test', 'Relative Test', 'Missing Test', 'Future Test']:
                self.assertNotIn(name, reply)

    async def test_authorization_before_any_crm_access(self):
        for text in ['今天需要联系谁？', 'Who should I follow up with today?', 'Show overdue clients']:
            for user, chat in [(8, 70), (7, 80)]:
                event = self.event(text, user, chat)
                with patch.object(self.crm, 'list_clients', side_effect=AssertionError('Unauthorized read')):
                    self.assertTrue(await self.handler.handle(event, self.crm, text))
                event.message.reply_text.assert_not_awaited()

    async def test_query_supersedes_write_preview_without_approval(self):
        await self.handler.handle(self.event('set client Today Test status paused'), self.crm,
                                  'set client Today Test status paused')
        self.assertEqual(self.handler.pending[(7, 70)]['stage'], 'confirm')
        await self.ask('今天需要联系谁？')
        self.assertFalse(self.handler.pending)
        await self.handler.handle(self.event('confirm'), self.crm, 'confirm')

    async def test_shared_daily_brief_date_and_read_only_classification(self):
        import bot
        with patch('daily_brief.application_today', return_value=TODAY):
            self.handler.today_provider = lambda: daily_brief.application_today()
            reply = await self.ask('今天需要联系谁？')
            brief = bot.build_daily_brief_message(7)
        self.assertIn('Today Test', reply)
        self.assertIn('Today Test', brief)
        self.assertNotIn('明天测试', brief)
        for scope, expected in [('today', 'Today Test'), ('tomorrow', '明天测试'), ('overdue', 'Older Test')]:
            result = build_followup_query(self.crm.list_clients(), scope, today=TODAY)
            self.assertEqual(result['items'][0]['client_name'], expected)

    async def test_long_results_are_split_without_loss(self):
        clients = [{'name': f'Synthetic {number}', 'next_followup': TODAY.isoformat(), 'status': 'active'}
                   for number in range(30)]
        with patch.object(self.crm, 'list_clients', return_value=clients):
            event = self.event('Show clients due today')
            await self.handler.handle(event, self.crm, event.message.text)
        replies = [call.args[0] for call in event.message.reply_text.await_args_list]
        self.assertGreater(len(replies), 1)
        self.assertTrue(all(len(reply.encode('utf-16-le')) // 2 <= 4096 for reply in replies))
        combined = ''.join(replies)
        for client in clients:
            self.assertIn('Client: ' + client['name'] + '\n', combined)

    def test_only_explicit_queries_are_recognized_before_client_lookup(self):
        self.assertEqual(parse_request('Show overdue clients')['intent'], 'followup_query')
        for text in ['Who should I follow up with today? Delete them.', '今天或者明天需要联系谁？']:
            self.assertIsNone(parse_request(text))
        self.assertEqual(parse_request('set client Today Test next_followup 2026-11-15')['intent'], 'update')
        with self.assertRaises(ValueError):
            build_followup_query([], 'unsupported', today=TODAY)


class ApplicationDateTest(unittest.TestCase):
    def test_configured_zone_not_host_or_utc_date(self):
        fixed = datetime(2026, 11, 15, 4, 30, tzinfo=timezone.utc)
        with patch.dict('os.environ', {'DAILY_BRIEF_TIMEZONE': 'America/New_York'}, clear=True):
            self.assertEqual(application_today(now=fixed), date(2026, 11, 14))
        with patch.dict('os.environ', {'DAILY_BRIEF_TIMEZONE': 'Asia/Shanghai'}, clear=True):
            self.assertEqual(application_today(now=fixed), date(2026, 11, 15))

    def test_default_zone_and_dst_boundary(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(application_today(now=datetime(2026, 3, 9, 3, 30, tzinfo=timezone.utc)),
                             date(2026, 3, 8))
        with self.assertRaises(ValueError):
            application_today(now=datetime(2026, 11, 14))
