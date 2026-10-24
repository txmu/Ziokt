#!/usr/bin/env python3
"""Securely enable Telegram Bot API tools in an existing private MCP config."""
import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ziokt.telegram import TelegramBot


def configure(config_path, chat_ids, user_ids=(), restart=True, *, service_user=None, source_root=None, python_executable=None, mcp_unit=None, telegram_unit=None):
    if restart:
        if not service_user or not re.fullmatch('[A-Za-z_][A-Za-z0-9_-]{0,31}',service_user):raise ValueError('explicit service user required')
        if any(not isinstance(unit,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',unit) for unit in (mcp_unit,telegram_unit)) or mcp_unit==telegram_unit:raise ValueError('explicit distinct MCP and Telegram service names required')
        for path in (config_path,source_root,python_executable):
            if path is None or not Path(path).is_absolute() or any(c in str(path) for c in '\n\r\x00'):raise ValueError('safe absolute service paths required')

    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text())
    root = config_path.parent / 'telegram'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    token = getpass.getpass('Telegram Bot Token (hidden): ').strip()
    if not re.fullmatch(r'[0-9]{5,}:[A-Za-z0-9_-]{20,}', token):
        raise ValueError('Bot Token format is invalid')
    ids = sorted(set(chat_ids))
    if not ids or any(not re.fullmatch(r'-?[0-9]{1,20}', item) for item in ids):
        raise ValueError('Provide one or more numeric --chat-id values')
    users=set(user_ids)
    if any(not re.fullmatch(r'[0-9]{1,20}', item) for item in users):
        raise ValueError('User IDs must be positive numeric Telegram IDs')
    users.update(item for item in ids if int(item)>0)  # Private-chat owner ID equals the chat ID.
    if not users:
        raise ValueError('Group chats require at least one explicit --user-id owner')
    token_path = root / 'bot.token'
    fd, temp_name = tempfile.mkstemp(prefix='.bot-token-', dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='ascii') as out:
            out.write(token + '\n');out.flush();os.fsync(out.fileno())
        os.replace(temp_name, token_path)
    finally:
        if os.path.exists(temp_name):os.unlink(temp_name)
    telegram = {'enabled': True, 'worker_enabled':True, 'token_file': str(token_path), 'allowed_chat_ids': ids,'allowed_user_ids':sorted(users)}
    try:
        TelegramBot(telegram).status()  # Validate the token against Telegram before enabling tools.
    except Exception:
        token_path.unlink(missing_ok=True)
        raise
    config['telegram'] = telegram
    for client in ('ziokt-operator','ziokt-browser'):
        if client in config.get('clients',{}):
            config['clients'][client]['scopes'] = sorted(set(config['clients'][client].get('scopes',[])) | {'telegram:read','telegram:write'})
    config['cimd_scopes'] = sorted(set(config.get('cimd_scopes',[])) | {'telegram:read','telegram:write'})
    fd, temp_name = tempfile.mkstemp(prefix='.mcp-config-', dir=config_path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(config, out, ensure_ascii=False, indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
        os.replace(temp_name, config_path)
    finally:
        if os.path.exists(temp_name):os.unlink(temp_name)
    if restart:
        unit=Path(__file__).resolve().parents[1]/'gateway/systemd/ziokt-telegram-bot.service.template'
        def argument(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
        text=unit.read_text()
        for name,value in {'SERVICE_USER':service_user,'SOURCE_ROOT':argument(source_root),'PYTHON':argument(python_executable),'MCP_CONFIG':argument(config_path),'MCP_UNIT':mcp_unit}.items():text=text.replace('@@'+name+'@@',value)
        with tempfile.TemporaryDirectory(prefix='ziokt-telegram-unit-') as directory:
            rendered=Path(directory)/'telegram.service';rendered.write_text(text)
            subprocess.run(['sudo','-n','install','-m','0644',str(rendered),'/etc/systemd/system/'+telegram_unit+'.service'],check=True)
        subprocess.run(['sudo','-n','systemctl','daemon-reload'],check=True)
        subprocess.run(['sudo','-n','systemctl','restart',mcp_unit],check=True)
        subprocess.run(['sudo','-n','systemctl','enable',telegram_unit],check=True)
        subprocess.run(['sudo','-n','systemctl','restart',telegram_unit],check=True)
        for service in (mcp_unit,telegram_unit):
            subprocess.run(['systemctl','is-active','--quiet',service],check=True)
    return {'enabled':True,'worker_enabled':True,'chat_count':len(ids),'owner_user_count':len(users),'token_printed':False,'service_restarted':restart}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--service-user');parser.add_argument('--source-root',type=Path);parser.add_argument('--python',type=Path);parser.add_argument('--mcp-unit');parser.add_argument('--telegram-unit')
    parser.add_argument('--chat-id',action='append',default=[],help='Numeric Telegram chat ID; repeat for each allowed chat')
    parser.add_argument('--user-id',action='append',default=[],help='Allowed Telegram sender ID (required for group chats); repeat per owner')
    parser.add_argument('--no-restart',action='store_true')
    args=parser.parse_args()
    print(json.dumps(configure(args.config,args.chat_id,args.user_id,not args.no_restart,service_user=args.service_user,source_root=args.source_root,python_executable=args.python,mcp_unit=args.mcp_unit,telegram_unit=args.telegram_unit)))
