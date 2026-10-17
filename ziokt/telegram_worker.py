"""Owner-scoped long-polling Telegram command bridge for the MCP catalog."""
import hashlib
import json
import re
import secrets
import time

from .gateway_store import database, encoded
from .mcp import Service
from .protocol import secure_read, strict_json
from .telegram import TelegramBot


class TelegramWorker:
    def __init__(self, config_path):
        self.config_path = str(config_path)
        self.config = strict_json(secure_read(config_path))
        cfg = self.config.get('telegram', {})
        if cfg.get('enabled') is not True or cfg.get('worker_enabled') is not True:
            raise ValueError('Telegram command worker is not enabled')
        self.bot = TelegramBot(cfg)
        self.allowed_users = {str(item) for item in cfg.get('allowed_user_ids', [])}
        if not self.allowed_users:
            raise ValueError('Telegram requires an explicit allowed_user_ids owner list')
        if self.bot.status()['webhook_enabled']:
            raise ValueError('Telegram webhook is configured; remove it before enabling polling')
        self.config['config_path'] = self.config_path
        self.service = Service(self.config)
        self.client_id = 'ziokt-operator'
        client = self.service.client(self.client_id)
        if not client:
            raise ValueError('Telegram owner MCP client is unavailable')
        self.principal = {'client':self.client_id,'scopes':set(client['scopes']),'expires':2**63-1,'token_id':'telegram-owner'}
        self.commands = self._commands()
        with database(self.service.db) as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS telegram_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS telegram_inbox (
                update_id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL, user_id TEXT NOT NULL,
                message_id INTEGER NOT NULL, text TEXT NOT NULL, payload BLOB NOT NULL,
                received_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
              CREATE TABLE IF NOT EXISTS telegram_confirmations (
                code_hash TEXT PRIMARY KEY, update_id INTEGER NOT NULL, chat_id TEXT NOT NULL,
                user_id TEXT NOT NULL, tool TEXT NOT NULL, arguments BLOB NOT NULL,
                created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                state TEXT NOT NULL, result BLOB);
            ''')
        self.service.db.chmod(0o600)

    def _commands(self):
        command_map={'start':None,'help':None,'status':None,'tools':None,'mcp':None,'confirm':None,'cancel':None}
        candidates=[]
        for name,tool in sorted(self.service.tools.items()):
            if re.fullmatch('[a-z0-9_]{1,32}',name) and name not in command_map:
                command_map[name]=name
                candidates.append({'command':name,'description':(tool['description'][:256] or name)})
        menu=[
            {'command':'start','description':'Start the Ziokt Telegram command bot'},
            {'command':'help','description':'Show command and MCP tool usage'},
            {'command':'status','description':'Show MCP and Telegram service status'},
            {'command':'tools','description':'List available tools by page or prefix'},
            {'command':'mcp','description':'Call any MCP tool by name with JSON arguments'},
            {'command':'confirm','description':'Confirm a pending write by its one-time code'},
            {'command':'cancel','description':'Cancel a pending write by its one-time code'},
        ]
        # Keep a little space below Telegram's documented 100-command ceiling;
        # some bot scopes reserve slots for BotFather-managed commands.
        menu.extend(candidates[:18])
        self.bot.set_commands(menu)
        self.command_map=command_map
        return menu

    def run(self):
        offset=None
        with database(self.service.db) as db:
            row=db.execute("SELECT value FROM telegram_state WHERE key='next_offset'").fetchone()
            if row:offset=int(row[0])
        while True:
            try:
                updates=self.bot.poll(offset,45)
                if updates:
                    with database(self.service.db) as db:
                        for update in updates:
                            update_id=update.get('update_id')
                            message=update.get('message',{})
                            chat=message.get('chat',{});sender=message.get('from',{})
                            chat_id=str(chat.get('id',''));user_id=str(sender.get('id',''))
                            if type(update_id) is not int:continue
                            if chat_id in self.bot.allowed and user_id in self.allowed_users and type(message.get('message_id')) is int:
                                db.execute('INSERT OR IGNORE INTO telegram_inbox(update_id,chat_id,user_id,message_id,text,payload,received_at,status) VALUES (?,?,?,?,?,?,?,?)',
                                    (update_id,chat_id,user_id,message['message_id'],message.get('text','')[:4096],encoded(update),int(time.time()),'pending'))
                        offset=max(u['update_id'] for u in updates if type(u.get('update_id')) is int)+1
                        db.execute("INSERT OR REPLACE INTO telegram_state VALUES ('next_offset',?)",(str(offset),))
                        db.execute('DELETE FROM telegram_inbox WHERE received_at<?',(int(time.time())-30*86400,))
                self.process_pending()
            except KeyboardInterrupt:
                return
            except Exception:
                # Never log Telegram request URLs, token-bearing API paths or message payloads.
                time.sleep(3)

    def process_pending(self):
        with database(self.service.db) as db:
            rows=db.execute("SELECT update_id,chat_id,user_id,message_id,text FROM telegram_inbox WHERE status='pending' ORDER BY update_id LIMIT 50").fetchall()
        for update_id,chat_id,user_id,message_id,text in rows:
            try:
                reply=self.handle(chat_id,user_id,update_id,text)
                if reply:
                    self.send_chunks(chat_id,message_id,reply)
                with database(self.service.db) as db:
                    db.execute("UPDATE telegram_inbox SET status='processed' WHERE update_id=? AND status='pending'",(update_id,))
            except Exception:
                # Keep failures from one update from terminating the polling service.
                with database(self.service.db) as db:
                    db.execute("UPDATE telegram_inbox SET status='error' WHERE update_id=?",(update_id,))

    def handle(self,chat_id,user_id,update_id,text):
        if not text.startswith('/'):
            return '我在线。请用 /help 查看命令；可用 /mcp 工具名 {JSON参数} 调用全部 MCP 工具。'
        head,*tail=text.split(None,1)
        command=head[1:].split('@',1)[0].lower()
        rest=tail[0].strip() if tail else ''
        if command=='start':
            return 'Ziokt MCP Bot 已启动。使用 /help 查看用法，/status 查看服务，/tools 列出工具。所有写操作都需要通过 /confirm 确认。'
        if command=='help':return self.help(rest)
        if command=='status':
            status=self.service.execute(self.principal,'ziokt_components',{})
            return json.dumps({'mcp':'online','telegram':'online','webhook':False,'components':status.get('components',[]),'native_providers':status.get('native_providers',[]),'mcp_tools':len(self.service.tools),'writes_enabled':status.get('writes_enabled',False)},ensure_ascii=False,indent=2)
        if command=='tools':return self.list_tools(rest)
        if command=='confirm':return self.confirm(chat_id,user_id,rest)
        if command=='cancel':return self.cancel(chat_id,user_id,rest)
        if command=='mcp':
            parts=rest.split(None,1)
            if not parts:return '用法：/mcp 工具名 {JSON参数}；详情用 /help 工具名，列表用 /tools。'
            return self.invoke(chat_id,user_id,update_id,parts[0],parts[1] if len(parts)>1 else '{}')
        tool=self.command_map.get(command)
        if tool:return self.invoke(chat_id,user_id,update_id,tool,rest or '{}')
        return '未知命令。使用 /help 查看用法，/tools 查看 MCP 工具列表。'

    def help(self,topic):
        if topic:
            tool=self.service.tools.get(topic)
            if not tool:return '未找到工具：'+topic
            return json.dumps({'tool':topic,'scope':tool['scope'],'write':tool['annotations']['destructiveHint'],'description':tool['description'],'inputSchema':tool['inputSchema']},ensure_ascii=False,indent=2)
        return ('Ziokt MCP Bot 命令：\n'
            '/start — 开始使用\n/help [工具名] — 查看用法或工具参数\n/status — MCP、组件与 Telegram 状态\n'
            '/tools [页码或前缀] — 分页列出工具\n/mcp 工具名 {JSON参数} — 调用全部 MCP 工具\n'
            '/confirm 一次性代码 — 确认待执行写操作\n/cancel 一次性代码 — 取消写操作\n\n'
            '示例：/mcp gateway_forum_list {"limit":10}\n'
            '也可直接调用命令菜单中的短工具名；未显示在菜单中的工具仍可用 /mcp 调用。写操作先返回确认码，不确认不会执行。')

    def list_tools(self,selector):
        names=sorted(self.service.tools)
        if selector and selector.isdigit():
            page=int(selector)
            if page<1:return '页码从 1 开始。'
            page_size=50;subset=names[(page-1)*page_size:page*page_size]
            if not subset:return '没有这一页。共 %d 页。'%((len(names)+page_size-1)//page_size)
            return '工具 %d/%d：\n'%(page,len(names))+', '.join(subset)+'\n使用 /help 工具名 查看参数。'
        if selector:
            subset=[name for name in names if name.startswith(selector.lower())]
            return ('前缀 %s（%d 个）：\n'%(selector,len(subset))+', '.join(subset[:120])) if subset else '没有匹配工具。'
        return '共 %d 个工具。\n'%(len(names))+', '.join(names[:50])+'\n更多：/tools 2、/tools 3……；按前缀筛选：/tools corium_。'

    def invoke(self,chat_id,user_id,update_id,name,raw_args):
        tool=self.service.tools.get(name)
        if not tool:return '未知 MCP 工具：'+name+'。用 /tools 查找。'
        try:
            args=json.loads(raw_args) if raw_args else {}
            if not isinstance(args,dict):return '参数必须是 JSON 对象。示例：/mcp '+name+' {"key":"value"}'
        except (json.JSONDecodeError,ValueError):return 'JSON 参数无法解析。请用 /help '+name+' 查看 schema。'
        if 'idempotency_key' in args:return '幂等键由 Bot 按更新自动生成，请从参数中移除 idempotency_key。'
        if tool['annotations']['destructiveHint']:
            code=secrets.token_urlsafe(9)
            code_hash=hashlib.sha256(code.encode()).hexdigest()
            now=int(time.time())
            with database(self.service.db) as db:
                db.execute('INSERT INTO telegram_confirmations VALUES (?,?,?,?,?,?,?,?,?,NULL)',(code_hash,update_id,chat_id,user_id,name,encoded(args),now,now+300,'pending'))
            return '待确认写操作：'+name+'\n参数摘要：'+hashlib.sha256(encoded(args)).hexdigest()[:16]+'\n5 分钟内发送 /confirm '+code+' 执行；/cancel '+code+' 取消。'
        result=self.service.call(self.principal,name,args)
        return self.render(result)

    def confirm(self,chat_id,user_id,code):
        if not re.fullmatch('[A-Za-z0-9_-]{8,32}',code):return '确认码格式无效。'
        digest=hashlib.sha256(code.encode()).hexdigest();now=int(time.time())
        with database(self.service.db) as db:
            row=db.execute('SELECT update_id,chat_id,user_id,tool,arguments,expires_at,state,result FROM telegram_confirmations WHERE code_hash=?',(digest,)).fetchone()
            if not row or row[1]!=chat_id or row[2]!=user_id:return '确认码不存在或不属于当前会话。'
            if row[5]<=now:
                db.execute("UPDATE telegram_confirmations SET state='expired' WHERE code_hash=?",(digest,));return '确认码已过期，请重新提交操作。'
            if row[6]=='completed':return self.render(json.loads(row[7]))
            if row[6]!='pending':return '该确认正在处理或需要管理员核对，不会自动重复执行。'
            db.execute("UPDATE telegram_confirmations SET state='processing' WHERE code_hash=? AND state='pending'",(digest,))
        args=json.loads(row[4]);key=hashlib.sha256(('telegram-confirm:'+digest).encode()).hexdigest()
        result=self.service.call(self.principal,row[3],args,key)
        with database(self.service.db) as db:
            db.execute("UPDATE telegram_confirmations SET state='completed',result=? WHERE code_hash=?",(encoded(result),digest))
        return self.render(result)

    def cancel(self,chat_id,user_id,code):
        if not re.fullmatch('[A-Za-z0-9_-]{8,32}',code):return '确认码格式无效。'
        digest=hashlib.sha256(code.encode()).hexdigest()
        with database(self.service.db) as db:
            cur=db.execute("UPDATE telegram_confirmations SET state='cancelled' WHERE code_hash=? AND chat_id=? AND user_id=? AND state='pending'",(digest,chat_id,user_id))
        return '操作已取消。' if cur.rowcount else '确认码不存在、已过期或已处理。'

    @staticmethod
    def render(result):
        if not isinstance(result,dict):return str(result)
        contents=result.get('content',[])
        text='\n'.join(item.get('text','') for item in contents if isinstance(item,dict) and item.get('type')=='text')
        if result.get('isError'):return '工具调用失败：'+(text or '操作被拒绝；请查看 MCP 审计或原生状态。')
        if not text:text=json.dumps(result.get('structuredContent',result),ensure_ascii=False,indent=2)
        return text

    def send_chunks(self,chat_id,message_id,text):
        remaining=text or '完成。'
        if len(remaining.encode('utf-16-le'))//2>30000:
            remaining=remaining[:12000]+'\n…输出已截断，请用更窄的查询条件。'
        while remaining:
            used=0;cut=0
            for index,char in enumerate(remaining):
                width=len(char.encode('utf-16-le'))//2
                if used+width>3900:break
                used+=width;cut=index+1
            part=remaining[:cut];remaining=remaining[cut:]
            self.bot.send_reply(chat_id,message_id,part)
