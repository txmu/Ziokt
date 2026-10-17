"""Narrow, allowlisted Telegram Bot API client for MCP tools."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .protocol import secure_read


class TelegramBot:
    def __init__(self, config):
        self.config = config
        token_file = config.get('token_file')
        if not isinstance(token_file, str):
            raise ValueError('Telegram token file is not configured')
        token = secure_read(token_file, 256).decode('ascii').strip()
        if not re.fullmatch(r'[0-9]{5,}:[A-Za-z0-9_-]{20,}', token):
            raise ValueError('Telegram token file has invalid format')
        self.token = token
        ids = config.get('allowed_chat_ids', [])
        if not isinstance(ids, list) or not ids or any(not isinstance(item, (str, int)) or not re.fullmatch(r'-?[0-9]{1,20}', str(item)) for item in ids):
            raise ValueError('Telegram chat allowlist is invalid')
        self.allowed = {str(item) for item in ids}

    def call(self, method, values=None):
        if method not in {'getMe','getWebhookInfo','getUpdates','getChat','getChatMember','sendMessage','editMessageText','deleteMessage','forwardMessage','copyMessage','sendPhoto','sendDocument','sendLocation','sendPoll','answerCallbackQuery','pinChatMessage','unpinChatMessage','setChatTitle','setChatDescription'}:
            raise ValueError('Telegram method is not enabled')
        url = 'https://api.telegram.org/bot' + self.token + '/' + method
        data = json.dumps(values or {}, separators=(',', ':')).encode()
        request = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json','Accept':'application/json'}, method='POST')
        from .gateway_store import NoRedirect
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=20) as response:
                raw = response.read(1_048_577)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ValueError('Telegram API request failed; check service connectivity and Bot API status') from None
        if len(raw) > 1_048_576:
            raise ValueError('Telegram API response exceeded size limit')
        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError('Telegram API returned an invalid response') from None
        if not isinstance(result, dict) or result.get('ok') is not True:
            # Telegram may include token-bearing request details in diagnostics. Never reflect them.
            raise ValueError('Telegram API rejected the operation')
        return result.get('result')

    def status(self):
        me = self.call('getMe')
        webhook = self.call('getWebhookInfo')
        return {'bot': {key: me[key] for key in ('id','is_bot','first_name','username','can_join_groups','can_read_all_group_messages','supports_inline_queries') if key in me}, 'webhook_enabled': bool(webhook.get('url')), 'pending_update_count': webhook.get('pending_update_count', 0), 'polling_compatible': not bool(webhook.get('url'))}

    def updates(self, offset=None):
        values = {'limit':100,'timeout':0,'allowed_updates':['message','edited_message','channel_post','edited_channel_post','callback_query','my_chat_member','chat_member']}
        if offset is not None: values['offset'] = offset
        rows = self.call('getUpdates', values)
        safe=[]
        for row in rows:
            msg = row.get('message') or row.get('edited_message') or row.get('channel_post') or row.get('edited_channel_post') or {}
            chat = msg.get('chat') or (row.get('callback_query') or {}).get('message',{}).get('chat') or {}
            chat_id = str(chat.get('id',''))
            if chat_id not in self.allowed: continue
            safe.append(row)
        return {'updates':safe,'count':len(safe),'filtered':len(rows)-len(safe)}

    def chat_id(self, value):
        chat_id = str(value)
        if chat_id not in self.allowed: raise ValueError('Telegram chat is outside the configured allowlist')
        return int(chat_id)

    def chat(self, chat_id): return self.call('getChat',{'chat_id':self.chat_id(chat_id)})
    def member(self, chat_id, user_id): return self.call('getChatMember',{'chat_id':self.chat_id(chat_id),'user_id':user_id})
    def send(self, chat_id, text): return self.call('sendMessage',{'chat_id':self.chat_id(chat_id),'text':text})
