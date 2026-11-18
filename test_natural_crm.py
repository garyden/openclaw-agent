"""Bilingual CRM conversations: temporary XML only, no external services."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from client_manager import ClientManager
from natural_crm import NaturalCRM, parse_request, validate_value

ENV = {'TELEGRAM_OWNER_IDS': '7,8', 'TELEGRAM_ALLOWED_CHAT_IDS': '70,80'}


class NaturalCRMTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'memory.xml'
        self.crm = ClientManager(str(self.path))
        self.crm.add_client(name='Alice Chen', status='active', next_followup='2026-12-01')
        self.crm.add_client(name='Alice Cheng', status='paused')
        self.crm.add_client(name='张三', status='active')
        self.now = 100
        self.handler = NaturalCRM(clock=lambda: self.now)
        env = patch.dict(os.environ, ENV, clear=True)
        env.start()
        self.addCleanup(env.stop)
        import bot
        self.patchers = [patch('bot.pending_tours', set()), patch('bot.crm', self.crm), patch('bot.natural_crm', self.handler),
                         patch('bot.send_email', side_effect=AssertionError('Email forbidden')),
                         patch('bot.get_openai_client', side_effect=AssertionError('AI forbidden')),
                         patch('bot.extract_voice_intent_with_openai', side_effect=AssertionError('AI forbidden'))]
        self.external_mocks = []
        for index, patcher in enumerate(self.patchers):
            mocked = patcher.start()
            if index >= 3:
                self.external_mocks.append(mocked)
            self.addCleanup(patcher.stop)
        self.original = self.path.read_bytes()

    def tearDown(self):
        for mocked in self.external_mocks:
            mocked.assert_not_called()

    def event(self, text, user=7, chat=70):
        return SimpleNamespace(effective_user=SimpleNamespace(id=user, is_bot=False),
                               effective_chat=SimpleNamespace(id=chat),
                               message=SimpleNamespace(text=text, reply_text=AsyncMock()))

    async def say(self, text, user=7, chat=70):
        event = self.event(text, user, chat)
        handled = await self.handler.handle(event, self.crm, text)
        replies = [call.args[0] for call in event.message.reply_text.await_args_list]
        return handled, '\n'.join(replies)

    async def test_bilingual_lookup_and_list_are_read_only(self):
        for text, expected in [('查找客户张三', '张三'), ('find client Alice Chen', 'Alice Chen'),
                               ('列出所有客户', '张三'), ('list clients', 'Alice Chen')]:
            with self.subTest(text=text):
                handled, reply = await self.say(text)
                self.assertTrue(handled)
                self.assertIn(expected, reply)
                self.assertEqual(self.original, self.path.read_bytes())

    async def test_status_preview_and_confirmation_in_both_languages(self):
        for text, name, value, confirm in [
            ('把客户张三的状态改为看房中', '张三', 'touring', '确认'),
            ('update client Alice Chen, status paused', 'Alice Chen', 'paused', 'confirm')]:
            with self.subTest(text=text):
                before = self.path.read_bytes()
                _, reply = await self.say(text)
                self.assertIn('Update preview', reply)
                self.assertIn('Before: active', reply)
                self.assertIn('After: ' + value, reply)
                self.assertEqual(before, self.path.read_bytes())
                await self.say(confirm)
                self.assertEqual(self.crm.get_client(name)['status'], value)
                self.assertFalse(self.handler.pending)
                saved = self.path.read_bytes()
                await self.say(confirm)
                self.assertEqual(saved, self.path.read_bytes())

    async def test_followup_preview_and_confirm_preserve_other_fields(self):
        for text, name, expected in [
            ('set client Alice Chen next follow up to 2026-12-20', 'Alice Chen', '2026-12-20'),
            ('客户张三下次跟进设为2026年12月21日', '张三', '2026-12-21')]:
            before = self.crm.get_client(name)
            _, reply = await self.say(text)
            self.assertIn('CRM date only', reply)
            self.assertIn('After: ' + expected, reply)
            self.assertEqual(before, self.crm.get_client(name))
            await self.say('确认')
            self.assertEqual(self.crm.get_client(name), {**before, 'next_followup': expected})

    async def test_cancellation_invalidates_preview(self):
        for cancel in ['取消', 'cancel']:
            await self.say('set client 张三 status to paused')
            await self.say(cancel)
            await self.say('confirm')
            self.assertFalse(self.handler.pending)
            self.assertEqual(self.original, self.path.read_bytes())

    async def test_ambiguous_client_requires_full_name_then_preview(self):
        await self.say('update client Alice, status touring')
        self.assertEqual(self.handler.pending[(7, 70)]['stage'], 'name')
        await self.say('confirm')
        self.assertEqual(self.original, self.path.read_bytes())
        _, reply = await self.say('Alice Chen')
        self.assertIn('Update preview', reply)
        await self.say('confirm')
        self.assertEqual(self.crm.get_client('Alice Chen')['status'], 'touring')
        self.assertEqual(self.crm.get_client('Alice Cheng')['status'], 'paused')

    async def test_unique_partial_and_fuzzy_identity_are_not_guessed(self):
        for text in ['find client 张', 'find client Alice Chenn']:
            _, reply = await self.say(text)
            self.assertIn('exact client name', reply)
            self.assertNotIn('Status:', reply)
            self.assertEqual(self.original, self.path.read_bytes())
            await self.say('cancel')

    async def test_search_selection_is_read_only(self):
        _, reply = await self.say('search clients Alice')
        self.assertIn('Alice Chen', reply)
        self.assertIn('Alice Cheng', reply)
        _, reply = await self.say('Alice Cheng')
        self.assertIn('Status: paused', reply)
        self.assertEqual(self.original, self.path.read_bytes())

    async def test_relative_and_invalid_dates_require_clarification(self):
        for raw in ['明天', 'tomorrow', '12/01', '2026-02-30']:
            _, reply = await self.say('客户张三下次跟进设为' + raw)
            self.assertIn('YYYY-MM-DD', reply)
            await self.say('confirm')
            self.assertEqual(self.original, self.path.read_bytes())
            _, reply = await self.say('2026-12-25')
            self.assertIn('Update preview', reply)
            self.assertEqual(self.original, self.path.read_bytes())
            await self.say('cancel')

    async def test_timeout_invalidates_approval_and_clarification(self):
        for text in ['set client 张三 status paused', 'find client Alice',
                     '客户张三下次跟进设为明天']:
            await self.say(text)
            self.now += 301
            _, reply = await self.say('confirm')
            self.assertIn('expired', reply)
            self.assertFalse(self.handler.pending)
            self.assertEqual(self.original, self.path.read_bytes())

    async def test_different_user_and_chat_cannot_confirm(self):
        await self.say('set client 张三 status paused')
        for user, chat in [(8, 70), (7, 80), (8, 80)]:
            await self.say('confirm', user, chat)
            self.assertEqual(self.original, self.path.read_bytes())
        self.assertIn((7, 70), self.handler.pending)
        await self.say('confirm')
        self.assertEqual(self.crm.get_client('张三')['status'], 'paused')

    async def test_unauthorized_access_has_no_reply_read_write_or_approval(self):
        await self.say('set client 张三 status paused')
        with patch.object(self.crm, 'list_clients', side_effect=AssertionError('CRM read forbidden')):
            for user, chat in [(9, 70), (7, 90)]:
                for text in ['find client 张三', 'confirm', '取消']:
                    handled, reply = await self.say(text, user, chat)
                    self.assertTrue(handled)
                    self.assertEqual(reply, '')
        self.assertEqual(self.original, self.path.read_bytes())
        self.assertIn((7, 70), self.handler.pending)

    async def test_unknown_unsupported_negation_and_injection_never_write_or_send(self):
        for text in ['hello', 'send the email', '给客户发邮件', 'do not update client 张三 status paused',
                     '不要把客户张三状态改为暂停', 'update client 张三 email x@example.com',
                     'set client 张三 status active | email=other@example.com',
                     '客户张三状态改为暂停并发送邮件', 'delete client 张三']:
            with self.subTest(text=text):
                await self.say(text)
                await self.say('confirm')
                self.assertEqual(self.original, self.path.read_bytes())

    async def test_unknown_reply_invalidates_preview(self):
        await self.say('set client 张三 status paused')
        await self.say('maybe later')
        await self.say('confirm')
        self.assertFalse(self.handler.pending)
        self.assertEqual(self.original, self.path.read_bytes())

    async def test_new_request_supersedes_preview(self):
        await self.say('set client 张三 status paused')
        await self.say('find client Alice Chen')
        await self.say('confirm')
        self.assertFalse(self.handler.pending)
        self.assertEqual(self.original, self.path.read_bytes())

    async def test_changed_record_invalidates_confirmation(self):
        await self.say('set client 张三 status paused')
        self.crm.update_client('张三', notes='Changed by another command')
        before = self.path.read_bytes()
        _, reply = await self.say('confirm')
        self.assertIn('Record changed', reply)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(self.handler.pending)

    async def test_text_routing_precedes_legacy_and_keeps_tour_first(self):
        import bot
        event = self.event('find client 张三')
        with patch('bot.handle_memory_commands', side_effect=AssertionError('legacy called')):
            await bot.handle_message(event, None)
        self.assertIn('张三', event.message.reply_text.await_args.args[0])
        with (patch('bot.handle_tour_reply', new=AsyncMock(return_value=True)),
              patch.object(self.handler, 'handle', new=AsyncMock()) as handler):
            await bot.handle_message(self.event('2'), None)
            handler.assert_not_awaited()
        with (patch('bot.handle_tour_reply', new=AsyncMock(return_value=False)),
              patch('bot.handle_memory_commands', new=AsyncMock(return_value=True)) as legacy):
            await bot.handle_message(self.event('记住我喜欢投资房产'), None)
            legacy.assert_awaited_once()
        self.assertEqual(self.original, self.path.read_bytes())

    async def test_chinese_identity_and_date_clarification_then_confirmation(self):
        self.crm.add_client(name='张三丰', status='active')
        before = self.path.read_bytes()
        await self.say('客户张下次跟进设为明天')
        self.assertEqual(self.handler.pending[(7, 70)]['stage'], 'name')
        await self.say('张三')
        self.assertEqual(self.handler.pending[(7, 70)]['stage'], 'value')
        await self.say('2026-12-25')
        self.assertEqual(self.handler.pending[(7, 70)]['stage'], 'confirm')
        self.assertEqual(before, self.path.read_bytes())
        await self.say('确认')
        self.assertEqual(self.crm.get_client('张三')['next_followup'], '2026-12-25')
        self.assertEqual(self.crm.get_client('张三丰')['next_followup'], '')

    async def test_cancellation_clears_identity_and_date_clarification(self):
        for text in ['find client Alice', '客户张三下次跟进设为明天']:
            await self.say(text)
            await self.say('取消')
            await self.say('Alice Chen')
            await self.say('2026-12-25')
            await self.say('确认')
            self.assertFalse(self.handler.pending)
            self.assertEqual(self.original, self.path.read_bytes())

    async def test_storage_failure_consumes_confirmation(self):
        await self.say('set client 张三 status paused')
        with patch.object(self.crm, 'update_client', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                await self.say('confirm')
        self.assertFalse(self.handler.pending)
        self.assertEqual(self.original, self.path.read_bytes())

    async def test_all_six_statuses_normalize_before_preview_and_confirmation(self):
        cases = [
            ('新线索', 'New Lead', 'new_lead'),
            ('跟进中', 'ACTIVE', 'active'),
            ('看房中', 'viewing homes', 'touring'),
            ('已报价', 'Offer Submitted', 'offer_submitted'),
            ('已成交', 'deal closed', 'closed'),
            ('暂停', 'On Hold', 'paused'),
        ]
        for chinese, english, canonical in cases:
            for text, confirmation in [
                (f'把客户张三的状态改为{chinese}', '确认'),
                (f'update client 张三, status {english}', 'confirm')]:
                with self.subTest(text=text):
                    before = self.path.read_bytes()
                    _, reply = await self.say(text)
                    self.assertIn('After: ' + canonical, reply)
                    self.assertEqual(self.handler.pending[(7, 70)]['value'], canonical)
                    self.assertEqual(before, self.path.read_bytes())
                    await self.say(confirmation)
                    self.assertEqual(self.crm.get_client('张三')['status'], canonical)
                    import xml.etree.ElementTree as ET
                    statuses = [node.text for node in ET.parse(self.path).findall('./clients/client/status')]
                    from client_manager import VALID_STATUSES
                    self.assertTrue(all(status in VALID_STATUSES for status in statuses))
                    self.assertFalse(self.handler.pending)

    async def test_all_six_statuses_can_be_canceled_in_both_languages(self):
        for alias in ['新客户', '活跃', '正在看房', '已出价', '成交', '暂缓',
                      'new-lead', 'active', 'touring', 'submitted offer', 'closed', 'paused']:
            with self.subTest(alias=alias):
                _, reply = await self.say(f'set client 张三 status to {alias}')
                self.assertIn('Update preview', reply)
                await self.say('取消' if any(ord(c) > 127 for c in alias) else 'cancel')
                await self.say('confirm')
                self.assertEqual(self.original, self.path.read_bytes())
                self.assertFalse(self.handler.pending)

    async def test_unknown_ambiguous_and_negated_statuses_need_clarification(self):
        for alias in ['未知状态', '可能看房中', '看房中或暂停', '不看房中',
                      'unknown', 'active or paused', 'not touring', 'maybe closed',
                      'offer', 'done', 'inactive']:
            with self.subTest(alias=alias):
                _, reply = await self.say(f'客户张三状态改为{alias}')
                self.assertNotIn('Update preview', reply)
                self.assertEqual(self.handler.pending[(7, 70)]['stage'], 'value')
                await self.say('confirm')
                self.assertEqual(self.original, self.path.read_bytes())
                await self.say('cancel')

    async def test_exact_reported_chinese_sentence_through_bot_text_handler(self):
        import bot
        self.crm.add_client(name='MVP Test Client', status='active')
        before = self.path.read_bytes()
        event = self.event('把客户MVP Test Client的状态改为看房中')
        await bot.handle_message(event, None)
        self.assertIn('After: touring', event.message.reply_text.await_args.args[0])
        self.assertEqual(before, self.path.read_bytes())
        await bot.handle_message(self.event('确认'), None)
        self.assertEqual(self.crm.get_client('MVP Test Client')['status'], 'touring')

    def test_parser_validates_only_explicit_fields_and_dates(self):
        self.assertEqual(parse_request('please update client Alice Chen, status touring')['field'], 'status')
        self.assertEqual(parse_request('把客户张三的下次跟进日期改为2026-12-20')['field'], 'next_followup')
        self.assertIsNone(validate_value('status', 'paused; name=Other'))
        self.assertIsNone(validate_value('email', '2026-12-20'))
        self.assertIsNone(validate_value('next_followup', '2026-02-30'))
