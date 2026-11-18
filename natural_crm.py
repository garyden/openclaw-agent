"""Conservative bilingual text CRM: parse data, preview writes, then confirm.

Draft generation is review-only; no generated commands, storage initialization, or delivery.
"""
from __future__ import annotations

from datetime import date
import asyncio
import re
import unicodedata
from time import monotonic

from authorization import authorized
from client_manager import VALID_STATUSES, normalize_client_status
from client_reference import resolve_client_reference
from daily_brief import application_today, build_followup_query
from email_generator import generate_followup_email
from crm_logging import log_event

CONFIRM = {'confirm', 'confirm update', '确认', '確認', '确认修改', '確認修改'}
CANCEL = {'cancel', 'cancel update', '取消', '取消修改'}


def normalize_name(value):
    return ' '.join(value.casefold().split())


def draft_name_matches(heard_name, stored_name):
    """Formatting equivalence only; never promote fuzzy/partial names to exact."""
    heard_name = unicodedata.normalize('NFKC', heard_name)
    stored_name = unicodedata.normalize('NFKC', stored_name)
    if resolve_client_reference(heard_name, [{'name': stored_name}])['status'] == 'exact':
        return True
    # ASR can spell a known uppercase acronym: MVP -> M V P or M.V.P.
    # Both sides are compared, and the caller requires a unique matching record.
    def spelled_acronyms(name):
        return re.sub(r'\b[A-Z]{2,}\b', lambda match: ' '.join(match[0]), name)
    return resolve_client_reference(spelled_acronyms(heard_name),
                                    [{'name': spelled_acronyms(stored_name)}])['status'] == 'exact'


def classify_client_match(name, clients, *, draft=False):
    """Shared decision for actual CRM resolution and isolated diagnostic fixtures."""
    exact = [c for c in clients if normalize_name(c['name']) == normalize_name(name)]
    if exact:
        return ('strict_exact' if len(exact) == 1 else 'duplicate_exact'), exact
    if draft:
        formatted = [c for c in clients if draft_name_matches(name, c['name'])]
        if formatted:
            return ('format_exact' if len(formatted) == 1 else 'format_collision'), formatted
    partial = [c for c in clients if normalize_name(name) in normalize_name(c['name'])] if name else []
    if partial:
        return 'partial', partial
    resolution = resolve_client_reference(name, clients)
    candidates = resolution['candidates']
    if not candidates:
        return 'no_match', []
    return ('fuzzy' if len(candidates) == 1 else 'fuzzy_ambiguous'), candidates


def parse_followup_query(text):
    # Normalize typography/spacing only within this closed, read-only grammar.
    text = ' '.join(unicodedata.normalize('NFKC', text).casefold().split()).rstrip('?!.。').strip()
    chinese_text = re.sub(r'\s+', '', text)
    chinese = re.fullmatch(
        r'(今天|明天)(?:有哪些|哪些|有谁|有誰|有哪[些个])?(?:客户|客戶)?'
        r'(?:需要|要|该|該)?(?:跟进|跟進|联系|聯繫)'
        r'(?:谁|誰|哪些客户|哪些客戶|(?:的客户|的客戶)(?:有哪些)?)?', chinese_text)
    english = re.fullmatch(
        r'(?:who (?:should|do) i (?:follow[ -]?up(?: with)?|contact)|'
        r'who needs (?:a )?follow[ -]?up|'
        r'(?:show|list)(?: me)?(?: the)? (?:clients|follow[ -]?ups)(?: (?:due|for))?|'
        r'which clients (?:need (?:a )?follow[ -]?up|are due(?: for (?:a )?follow[ -]?up)?)) '
        r'(today|tomorrow)', text)
    if chinese:
        return 'today' if chinese[1] == '今天' else 'tomorrow'
    if english:
        return english[1]
    # Client-qualified, whole-sentence forms only; never infer overdue from 过期 alone.
    if re.fullmatch(
        r'(?:哪些(?:客户|客戶)(?:的)?(?:跟进|跟進)?(?:已经|已經)?(?:逾期|过期|過期)(?:了)?|'
        r'哪些(?:客户|客戶)(?:需要|要)(?:补跟进|補跟進)|'
        r'哪些(?:客户|客戶)(?:已经|已經)?(?:错过|錯過)(?:了)?(?:跟进|跟進)日期|'
        r'(?:查看|列出|显示|顯示)?(?:所有)?(?:逾期|过期|過期)(?:的)?(?:客户|客戶))', chinese_text):
        return 'overdue'
    if re.fullmatch(r'(?:(?:show|list)(?: me)? overdue (?:clients|follow[ -]?ups)|'
                    r'which clients are overdue)', text):
        return 'overdue'
    return None


def format_followup_query(result):
    labels = {'today': '今天 / Today', 'tomorrow': '明天 / Tomorrow', 'overdue': '已逾期 / Overdue'}
    actions = {
        'today': '查看今天到期的CRM记录，确认适合联系后跟进。 / Review the recorded follow-up due today; contact the client if appropriate.',
        'tomorrow': '查看CRM记录，为明天的跟进做准备。 / Review the CRM record and prepare for the follow-up due tomorrow.',
        'overdue': '优先查看逾期的CRM记录，确认适合联系后跟进。 / Prioritize reviewing this overdue CRM record; follow up if appropriate.',
    }
    scope = result['scope']
    lines = [f"{labels[scope]} ({result['date'].isoformat()})"]
    if not result['items']:
        lines.append('没有匹配的跟进记录。 / No matching follow-ups.')
    for item in result['items']:
        lines.append(f"客户 / Client: {item['client_name']}\n"
                     f"到期日 / Due: {item['followup_date'].isoformat()}\n"
                     f"状态 / Status: {item['status']}\n"
                     f"建议 / Suggested action: {actions[scope]}")
    lines.append('仅依据CRM跟进日期；只读查询，未修改或发送。 / Based only on CRM follow-up dates; no changes or delivery.')
    return '\n\n'.join(lines)


def parse_email_draft_request(text):
    """Explicit draft requests only; client identity and purpose remain data."""
    english = re.fullmatch(
        r'(?:draft|write|compose|prepare)(?: me)? (?:a |an )?(?:follow[ -]?up )?email '
        r'(?:to|for) (.+?)(?: (?:about|regarding|to ask about) (.+))?', text, re.I)
    chinese = re.fullmatch(
        r'(?:给|給)\s*(.+?)\s*(?:写|寫|起草)(?:一)?(?:封|份)?(?:跟进|跟進)?(?:邮件|郵件)'
        r'(?:[，,:：]?\s*(.+))?', text)
    match = english or chinese
    if match:
        name, purpose = match.groups()
        return {'intent': 'followup_email', 'name': name.strip(), 'purpose': (purpose or '').strip()}
    return None


def parse_request(text):
    """Only anchored, explicit CRM requests; values remain data throughout."""
    text = re.sub(r'^(?:please\s+|请|請|帮我|幫我)', '', text.strip(), flags=re.I).strip()
    scope = parse_followup_query(text)
    if scope is not None:
        return {'intent': 'followup_query', 'scope': scope}
    draft_request = parse_email_draft_request(text)
    if draft_request is not None:
        return draft_request
    if re.fullmatch(r'(?:list clients|show all clients|列出(?:所有)?客户|列出(?:所有)?客戶|查看所有客户|查看所有客戶)', text, re.I):
        return {'intent': 'lookup', 'name': ''}
    lookup = re.fullmatch(
        r'(?:(?:find|search|lookup|get|show)\s+clients?\s+|(?:查找|查询|查詢|查看|搜索|找|查一下|看一下|查)(?:一下)?(?:客户|客戶)\s*)(.+)', text, re.I)
    if lookup:
        return {'intent': 'lookup', 'name': lookup[1].strip()}
    english = re.fullmatch(
        r'(?:update|set|change)\s+(?:client\s+)?(.+?)(?:\s*,\s*|\s+)'
        r'(status|next[ _-]follow[ _-]?up(?: date)?)\s*(?:[:=]\s*|\s+(?:to\s+)?)(.+)', text, re.I)
    chinese = re.fullmatch(
        r'(?:把|将|將|更新)?(?:客户|客戶)\s*(.+?)\s*(?:的)?'
        r'(状态|狀態|下次跟进(?:日期)?|下次跟進(?:日期)?)\s*(?:改为|改為|改成|设为|設為|设置为|設置為|更新为|更新為|为|為|[:：=])\s*(.+)', text)
    match = english or chinese
    if match:
        name, field, value = match.groups()
        field = 'status' if field.casefold() in {'status', '状态', '狀態'} else 'next_followup'
        return {'intent': 'update', 'name': name.strip(), 'field': field, 'raw_value': value.strip()}
    # Recognized CRM mutation outside this MVP must not reach legacy handlers.
    if re.match(r'(?:(?:update|set|change|add|delete|remove)\s+client\b|(?:把|将|將|更新|添加|新增|删除|刪除)?(?:客户|客戶))', text, re.I):
        return {'intent': 'unsupported'}
    return None


def validate_value(field, raw):
    if field not in {'status', 'next_followup'} or not isinstance(raw, str):
        return None
    if field == 'status':
        return normalize_client_status(raw)
    # Intentionally ask for a full date instead of guessing locale, year, or timezone.
    match = re.fullmatch(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', raw)
    if match:
        raw = f'{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}'
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


class NaturalCRM:
    def __init__(self, ttl_seconds=300, clock=monotonic, today_provider=application_today, profile=None):
        self.pending = {}
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.today_provider = today_provider
        self.profile = profile

    def has_pending_draft(self, update):
        if not authorized(update):
            return False
        key = (update.effective_user.id, update.effective_chat.id)
        state = self.pending.get(key)
        return bool(state and state['expires'] > self.clock()
                    and state['intent'] == 'followup_email')

    async def handle(self, update, crm, text):
        if not authorized(update):
            return True  # Silent denial, including when called without the outer guard.
        key = (update.effective_user.id, update.effective_chat.id)
        now = self.clock()
        state = self.pending.get(key)
        expired = state is not None and state['expires'] <= now
        for stale in [k for k, v in self.pending.items() if v['expires'] <= now]:
            del self.pending[stale]
        word = text.strip().casefold()
        request = parse_request(text)
        if expired and request is None:
            await update.message.reply_text('操作已过期，请重新提出请求。 / Request expired; start again.')
            return True
        if word in CANCEL:
            self.pending.pop(key, None)
            await update.message.reply_text('已取消，未修改数据。 / Canceled; no data changed.')
            return True
        if word in CONFIRM:
            if state is None or state.get('stage') != 'confirm':
                await update.message.reply_text('没有可确认的修改，请先完成预览。 / No update preview to confirm.')
                return True
            # Consume before any storage call: a failure cannot leave a reusable approval.
            self.pending.pop(key, None)
            matches = [c for c in crm.list_clients()
                       if normalize_name(c['name']) == normalize_name(state['client']['name'])]
            if len(matches) != 1 or matches[0] != state['client']:
                await update.message.reply_text('客户记录已变化，请重新请求并确认。 / Record changed; request a fresh preview.')
                return True
            value = validate_value(state['field'], state['value'])
            if value is None:
                await update.message.reply_text('修改无效，请重新请求。 / Invalid update; start again.')
                return True
            crm.update_client(matches[0]['name'], **{state['field']: value})
            await update.message.reply_text('修改已保存。 / Update saved.')
            return True
        if request is not None:
            # A new request supersedes any previous confirmation/clarification.
            self.pending.pop(key, None)
            if request['intent'] == 'unsupported':
                await update.message.reply_text('此功能暂不支持。可查询客户、修改状态或下次跟进日期。 / Supported: client lookup, status, next follow-up date.')
                return True
            return await self._resolve(update, crm, key, {**request, 'expires': now + self.ttl_seconds})
        if state is not None and not expired:
            if state['stage'] == 'name':
                selected = [name for name in state['candidates']
                            if normalize_name(name) == normalize_name(text.strip())]
                if not selected and state['intent'] == 'followup_email':
                    selected = [name for name in state['candidates'] if draft_name_matches(text.strip(), name)]
                if len(selected) == 1:
                    state = {**state, 'name': selected[0]}
                    return await self._resolve(update, crm, key, state)
                await update.message.reply_text('请输入候选客户的完整姓名，或回复取消。 / Enter an exact candidate name or cancel.')
            elif state['stage'] == 'purpose':
                return await self._resolve(update, crm, key, {**state, 'purpose': text.strip()})
            elif state['stage'] == 'value':
                value = validate_value(state['field'], text.strip())
                if value is not None:
                    state = {**state, 'raw_value': text.strip()}
                    return await self._resolve(update, crm, key, state)
                await self._ask_value(update, state['field'])
            else:
                # Unknown replies cannot become approval for a later accidental confirm.
                self.pending.pop(key, None)
                await update.message.reply_text('修改未确认，预览已取消。 / Update not confirmed; preview canceled.')
            return True
        return False

    async def _resolve(self, update, crm, key, state):
        clients = crm.list_clients()
        if state['intent'] == 'followup_query':
            result = build_followup_query(clients, state['scope'], today=self.today_provider())
            message = format_followup_query(result)
            # At most 4,000 UTF-16 units, including names containing emoji.
            for offset in range(0, len(message), 2000):
                await update.message.reply_text(message[offset:offset + 2000])
            return True
        name = state['name']
        if not name and state['intent'] == 'lookup':
            await update.message.reply_text('\n'.join(c['name'] for c in clients) or '没有客户。 / No clients.')
            return True
        match_kind, candidates = classify_client_match(name, clients, draft=state['intent'] == 'followup_email')
        if match_kind in {'strict_exact', 'format_exact'}:
            client = candidates[0]
        else:
            if not candidates:
                self.pending.pop(key, None)
                await update.message.reply_text('未找到客户，请提供完整姓名。 / Client not found; provide the full name.')
                return True
            # Even a unique partial/fuzzy match needs explicit identity clarification.
            self.pending[key] = {**state, 'stage': 'name', 'candidates': [c['name'] for c in candidates]}
            await update.message.reply_text('请确认完整客户姓名（或取消）： / Enter the exact client name (or cancel):\n' +
                                            '\n'.join(c['name'] for c in candidates))
            return True
        if state['intent'] == 'lookup':
            self.pending.pop(key, None)
            await update.message.reply_text(crm.format_client_report(client))
            return True
        if state['intent'] == 'followup_email':
            if not state['purpose']:
                self.pending[key] = {**state, 'stage': 'purpose'}
                await update.message.reply_text('请说明邮件目的（或取消）。 / What should the draft ask about? Or cancel.')
                return True
            # No draft content enters XML or the existing sendable birthday draft queue.
            self.pending.pop(key, None)
            try:
                draft = await asyncio.to_thread(generate_followup_email, client, state['purpose'], self.profile)
            except Exception:
                draft = None
            if draft is None:
                log_event('request_failed')
                await update.message.reply_text('暂时无法生成草稿，未发送任何邮件。 / Could not generate the draft. Nothing was sent; try again later.')
                return True
            preview = (f"Recipient / 收件人: {client['name']}\n"
                       f"Email / 邮箱: {client.get('email') or 'MISSING / 未填写'}\n"
                       f"Subject: {draft['subject']}\n\n{draft['body']}")
            for offset in range(0, len(preview), 1800):
                await update.message.reply_text('DRAFT — NOT SENT / 草稿，未发送\n' + preview[offset:offset + 1800])
            return True
        value = validate_value(state['field'], state['raw_value'])
        if value is None:
            self.pending[key] = {**state, 'stage': 'value'}
            await self._ask_value(update, state['field'])
            return True
        # Keep a snapshot: another command changing this record invalidates approval.
        self.pending[key] = {**state, 'stage': 'confirm', 'client': dict(client), 'value': value}
        followup_note = '\n仅更新CRM日期，不创建定时提醒。 / CRM date only; no timed reminder.' if state['field'] == 'next_followup' else ''
        await update.message.reply_text(
            f"修改预览 / Update preview\n客户 / Client: {client['name']}\n"
            f"字段 / Field: {state['field']}\n原值 / Before: {client.get(state['field'], '')}\n"
            f"新值 / After: {value}{followup_note}\n"
            '尚未保存。回复“确认”或“取消”（confirm / cancel）。5分钟内有效。 / Not saved; expires in 5 minutes.')
        return True

    @staticmethod
    async def _ask_value(update, field):
        message = ('请输入准确日期 YYYY-MM-DD（或取消）；不会猜测相对日期。 / Enter an exact date YYYY-MM-DD or cancel.'
                   if field == 'next_followup' else
                   '请输入状态（或取消）： / Enter a status or cancel: ' + ', '.join(sorted(VALID_STATUSES)))
        await update.message.reply_text(message)
