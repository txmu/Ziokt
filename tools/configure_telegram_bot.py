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


def configure(config_path, chat_ids, restart=True):
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
    token_path = root / 'bot.token'
    fd, temp_name = tempfile.mkstemp(prefix='.bot-token-', dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='ascii') as out:
            out.write(token + '\n');out.flush();os.fsync(out.fileno())
        os.replace(temp_name, token_path)
    finally:
        if os.path.exists(temp_name):os.unlink(temp_name)
    telegram = {'enabled': True, 'token_file': str(token_path), 'allowed_chat_ids': ids}
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
        subprocess.run(['systemctl','restart','ziokt-mcp'],check=True)
        subprocess.run(['systemctl','is-active','--quiet','ziokt-mcp'],check=True)
    return {'enabled':True,'chat_ids':ids,'token_printed':False,'service_restarted':restart}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('/home/admin/.local/share/ziokt-production/mcp/mcp.json'))
    parser.add_argument('--chat-id',action='append',default=[],help='Numeric Telegram chat ID; repeat for each allowed chat')
    parser.add_argument('--no-restart',action='store_true')
    args=parser.parse_args()
    print(json.dumps(configure(args.config,args.chat_id,not args.no_restart)))
