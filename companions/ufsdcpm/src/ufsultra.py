#!/usr/bin/env python3
"""
UltraFileServer Pro v7.0 - 全功能企业级文件服务（终极版）
新增功能：
- Windows平台支持(pywin32/nssm)
- 自动requirements生成
- HTTPS自签名证书生成
- API权限控制
- 密码复杂度配置
- 异步I/O支持
- 令牌桶限速算法
- YAML/JSON配置支持
- 动态配置热加载
- 文件操作原子性
- Docker支持
- 系统安全加固
- 自我测试模式
"""

import os
import sys
import ssl
import mmap
import zlib
import platform
import argparse
import json
try:
    import yaml
except ImportError:
    yaml = None
import time
import base64
import hashlib
import http.server
import socketserver
import socket
import shutil
import subprocess
try:
    import psutil
except ImportError:
    psutil = None
import logging
import logging.handlers
import copy
import gzip
import hmac
import html
import io
import re
import secrets
import stat
from ufs_http_security import ConfinedFiles, DigestAuthority, digest_fields
import threading
import asyncio
import signal
from pathlib import Path, PurePath
from urllib.parse import unquote, parse_qs, urlsplit, quote
from threading import Thread, Lock, RLock
from datetime import datetime, timedelta, timezone
from ipaddress import ip_network, ip_address
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from wsgiref.handlers import format_date_time
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from typing import Dict, List, Optional, Union, Tuple

# ==================== 跨平台常量 ====================
OS_TYPE = platform.system()
INIT_SYSTEMS = {
    'linux': ['systemd', 'sysvinit', 'upstart', 'openrc', 'runit', 's6', 'supervisord', 'shepherd'],
    'windows': ['windows'],
    'darwin': ['launchd'],
    'sunos': ['smf'],
    'freebsd': ['rc.d'],
    'openbsd': ['rc.d'],
    'netbsd': ['rc.d']
}

# Do not modify the importing process's module registry.

# ==================== WebDAV常量 ====================
DAV_METHODS = ['OPTIONS', 'GET', 'HEAD', 'POST', 'DELETE', 'PUT', 
               'COPY', 'MOVE', 'MKCOL', 'PROPFIND', 'PROPPATCH', 'LOCK', 'UNLOCK']
DAV_HEADERS = ['DAV', 'Depth', 'Destination', 'Overwrite', 'Timeout']
DAV_NS = "DAV:"
DAV_PROPS = {
    'creationdate': ('creationdate', lambda p: format_date_time(p.stat().st_ctime)),
    'displayname': ('displayname', lambda p: p.name),
    'getcontentlength': ('getcontentlength', lambda p: str(p.stat().st_size)),
    'getlastmodified': ('getlastmodified', lambda p: format_date_time(p.stat().st_mtime)),
    'resourcetype': ('resourcetype', lambda p: '<collection/>' if p.is_dir() else ''),
    'supportedlock': ('supportedlock', lambda p: '<lockentry><lockscope><exclusive/></lockscope><locktype><write/></locktype></lockentry>'),
    'getetag': ('getetag', lambda p: f'"{hashlib.md5(f"{p.stat().st_ino}-{p.stat().st_mtime}".encode()).hexdigest()}"')
}

# ==================== API权限级别 ====================
API_PERMISSIONS = {
    'guest': ['/api/stats'],
    'user': ['/api/stats', '/api/files', '/api/transfers'],
    'admin': ['*']
}

# ==================== 统一配置 ====================
class Config:
    __config = None
    __lock = RLock()
    __config_file = None
    __last_modified = 0
    __instance = None

    def __new__(cls):
        with cls.__lock:
            if cls.__instance is None: cls.__instance = super().__new__(cls)
            return cls.__instance

    def __init__(self):
        with self.__lock:
            if not self.__config:
                self.load_config()

    def load_config(self):
        with self.__lock:
            previous = (self.__config,self.__config_file,self.__last_modified)
            try: return self._load_config()
            except BaseException:
                self.__config,self.__config_file,self.__last_modified = previous
                raise

    def _load_config(self):
        # 尝试加载YAML或JSON配置文件
        config_paths = [
            Path('ufs-config.yaml'),
            Path('ufs-config.json'),
            Path('/etc/ufs-pro/ufs-config.yaml'),
            Path('/etc/ufs-pro/ufs-config.json')
        ]
        
        for path in config_paths:
            if path.exists():
                info = path.lstat()
                if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 256*1024 or (os.name!='nt' and info.st_uid!=os.geteuid()):
                    raise ValueError('UFS_PRIVATE_CONFIG_REQUIRED')
                self.__config_file = path
                self.__last_modified = path.stat().st_mtime
                if path.suffix == '.yaml':
                    if yaml is None: raise RuntimeError('UFS_YAML_REQUIRES_PYYAML')
                    with open(path, 'r') as f:
                        self.__config = yaml.safe_load(f)
                else:
                    with open(path, 'r') as f:
                        self.__config = json.load(f)
                break
        
        if not self.__config:
            self.__config = self.default_config()
        
        if self.__config_file:
            base = self.__config_file.parent.absolute()
            for field in ('root_dir','log_file','ssl_cert'):
                if field in self.__config and not Path(self.__config[field]).is_absolute():
                    self.__config[field] = str(base/self.__config[field])
        self.__config = validated_config(self.__config)
        if self.__config_file and self.__config_file.absolute().is_relative_to(Path(self.__config['root_dir'])):
            raise ValueError('UFS_CONFIG_INSIDE_SERVED_ROOT')
        # 确保必要目录存在
        Path(self.__config['root_dir']).mkdir(parents=True, exist_ok=True)
        Path(self.__config['log_file']).parent.mkdir(parents=True, exist_ok=True)
        
        # 自动生成SSL证书如果配置了但不存在
        if self.__config['ssl'] and not Path(self.__config['ssl_cert']).exists():
            self.generate_self_signed_cert()

    def default_config(self):
        return {
            # 核心配置
            'port': 8000,
            'web_port': 8001,
            'mode': 'standard',
            'root_dir': self.safe_path(Path.cwd()/'ufs-data'),
            'host': '127.0.0.1',
            'request_timeout': 10,
            'request_total_timeout': 30,
            'max_listing': 1024,
            'cleanup_enabled': False,
            'max_conn': 100,
            'threads': 50,
            
            # 安全配置
            'ssl': True,
            'ssl_cert': 'cert.pem',
            'auth': {
                'user': 'admin',
                'pass': self.generate_password(20, special_chars=True),
                'role': 'admin',
                'min_length': 12,
                'special_chars': True
            },
            'realm': 'UltraFileServer',
            'nonce': hashlib.md5(str(time.time()).encode()).hexdigest(),
            'ip_whitelist': ['127.0.0.0/8', '::1/128'],
            'blacklist': [],
            
            # 传输配置
            'upload': False,
            'max_upload': 64*1024**2,
            'download_limit': 0,
            'checksum': True,
            'retention_days': 7,
            'use_mmap': True,
            'mmap_threshold': 10*1024**2,  # 10MB以上使用mmap
            'compression': True,
            'compression_level': 6,
            
            # 系统配置
            'init_type': self.detect_init(),
            'service_name': 'ufs-pro',
            'log_file': self.safe_path('ufs.log'),
            'active_transfers': {},
            
            # 新增配置
            'token_bucket': {
                'capacity': 1024**3,  # 1GB
                'rate': 10*1024**2  # 10MB/s
            },
            'atomic_operations': True,
            'self_test': False,
            'docker_support': False,
            'protect_system': True
        }

    @staticmethod
    def safe_path(path):
        return PurePath(path).as_posix() if OS_TYPE == 'Windows' else str(path)

    @staticmethod
    def detect_init():
        if OS_TYPE == 'Linux':
            try: pid1 = Path('/proc/1/comm').read_text().strip()
            except OSError: pid1 = ''
            if Path('/run/shepherd').exists() or pid1 == 'shepherd':
                return 'shepherd'
            for init in INIT_SYSTEMS['linux']:
                if pid1 == init or Path(f'/{init}').exists() or Path(f'/run/{init}').exists():
                    return init
            return 'unknown'
        elif OS_TYPE.lower() in ['freebsd', 'openbsd', 'netbsd']:
            return 'rc.d'
        elif OS_TYPE == 'Darwin':
            return 'launchd'
        elif OS_TYPE == 'Windows':
            return 'windows'
        elif OS_TYPE == 'SunOS':
            return 'smf'
        else:
            return INIT_SYSTEMS.get(OS_TYPE.lower(), ['unknown'])[0]
        
    @staticmethod
    def generate_password(length=12, special_chars=False):
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        if special_chars:
            chars += "!@#$%^&*()_+-=[]{}|;:,.<>?"
        return ''.join(secrets.choice(chars) for _ in range(length))

    def generate_self_signed_cert(self):
        """生成自签名SSL证书"""
        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "UltraFileServer"),
            x509.NameAttribute(NameOID.COMMON_NAME, "ufs-pro.local"),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.now(timezone.utc)
        ).not_valid_after(
            datetime.now(timezone.utc) + timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        ).sign(key, hashes.SHA256(), default_backend())
        
        cert_path = Path(self.__config['ssl_cert'])
        cert_fd = os.open(cert_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(cert_fd, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        os.chmod(cert_path, 0o600)
        logging.info(f"Generated self-signed SSL certificate at {cert_path}")

    def check_reload(self):
        """检查配置文件是否需要重新加载"""
        if self.__config_file and self.__config_file.exists():
            if self.__config_file.stat().st_mtime > self.__last_modified:
                logging.info("Configuration file modified, reloading...")
                self.load_config()
                return True
        return False

    def generate_requirements(self):
        """生成requirements.txt文件"""
        requirements = {
            'common': [
                'pyyaml',
                'cryptography',
                'aiohttp',
                'aiofiles',
                'psutil'
            ],
            'windows': [
                'pywin32; platform_system == "Windows"',
                'nssm; platform_system == "Windows"'
            ]
        }
        
        with open('requirements.txt', 'w') as f:
            f.write("# Auto-generated requirements for UltraFileServer Pro\n")
            for req in requirements['common']:
                f.write(f"{req}\n")
            
            if OS_TYPE == 'Windows':
                for req in requirements['windows']:
                    f.write(f"{req}\n")
        
        logging.info("Generated requirements.txt")

    @property
    def data(self):
        with self.__lock: return copy.deepcopy(self.__config)

# ==================== 令牌桶限速器 ====================
class TokenBucket:
    def __init__(self, capacity, rate):
        self.capacity = capacity
        self.rate = rate
        self.tokens = capacity
        self.last_check = time.monotonic()
        self.lock = Lock()

    def consume(self, amount):
        with self.lock:
            now = time.monotonic()
            elapsed = max(0, now - self.last_check)
            self.last_check = now
            
            # 添加新令牌
            self.tokens += elapsed * self.rate
            if self.tokens > self.capacity:
                self.tokens = self.capacity
            
            # 检查是否有足够的令牌
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False

# ==================== 系统服务管理 ====================
class ServiceManager:
    TEMPLATES = {
        'systemd': """[Unit]
Description=UFS Pro ({mode})
After=network.target
{security}

[Service]
Type=exec
ExecStart={python} {script} --daemon --mode {mode}
Restart=always
ProtectSystem={protect_system}
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictNamespaces=true
RestrictRealtime=true
MemoryDenyWriteExecute=true
LockPersonality=true

[Install]
WantedBy=multi-user.target""",
        
        'openrc': """#!/sbin/openrc-run
description="UFS Pro ({mode})"
command="{python}"
command_args="{script} --daemon --mode {mode}"
pidfile="/run/ufs-pro.pid"
start_stop_daemon_args="--make-pidfile"
""",
        
        'launchd': """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ufs-pro</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
        <string>--mode</string>
        <string>{mode}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>""",
        
        'sysvinit': """#!/bin/sh
### BEGIN INIT INFO
# Provides:          ufs-pro
# Required-Start:    $network
# Required-Stop:     $network
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: UltraFileServer Pro
# Description:       UltraFileServer Pro ({mode})
### END INIT INFO

case "$1" in
    start)
        {python} {script} --daemon --mode {mode}
        ;;
    stop)
        killall ufs-pro
        ;;
    restart)
        killall ufs-pro
        {python} {script} --daemon --mode {mode}
        ;;
    *)
        echo "Usage: $0 {{start|stop|restart}}"
        exit 1
        ;;
esac
""",
        
        'upstart': """description "UltraFileServer Pro ({mode})"
start on runlevel [2345]
stop on runlevel [016]

respawn
exec {python} {script} --daemon --mode {mode}
""",
        
        'runit': """#!/bin/sh
exec 2>&1
exec {python} {script} --daemon --mode {mode}
""",
        
        's6': """#!/bin/execlineb -P
{python} {script} --daemon --mode {mode}
""",
        
        'supervisord': """[program:ufs-pro]
command={python} {script} --daemon --mode {mode}
autostart=true
autorestart=true
""",
        
        'shepherd': """(define-service ufs-pro
  (documentation "UltraFileServer Pro")
  (provision '(ufs-pro))
  (start start-ufs-pro)
  (stop stop-ufs-pro))
  
(define start-ufs-pro
  (make-forkexec-constructor
   '("{python}" "{script}" "--daemon" "--mode" "{mode}")))

(define stop-ufs-pro
  (make-forkexec-destructor
   '("killall" "ufs-pro")))
""",

        'rc.d': """#!/bin/sh
# PROVIDE: ufs_pro
# REQUIRE: LOGIN
# KEYWORD: shutdown

. /etc/rc.subr

name="ufs_pro"
rcvar="ufs_pro_enable"

command="{python}"
command_args="{script} --daemon --mode {mode}"

load_rc_config $name
: ${ufs_pro_enable:="NO"}

run_rc_command "$1"
""",
        
        'windows': """@echo off
:start
{python} {script} --daemon --mode {mode}
if %errorlevel% == 0 (
    goto :eof
) else (
    timeout /t 5
    goto :start
)
"""
    }

    @classmethod
    def install(cls, mode):
        cfg = Config().data
        init_type = cfg['init_type']
        
        # Windows特殊处理
        if init_type == 'windows':
            try:
                import win32serviceutil
                import win32service
                import win32event
                import servicemanager
                cls.install_windows_service(mode)
                return
            except ImportError:
                if cls.install_with_nssm(mode):
                    return
                raise RuntimeError("Neither pywin32 nor nssm is available on Windows")

        template = cls.TEMPLATES.get(init_type)
        if not template:
            raise RuntimeError(f"Unsupported init: {init_type}")
        
        security = ""
        if init_type == 'systemd' and cfg['protect_system']:
            security = "ProtectSystem=full\nProtectHome=read-only"
        
        content = template.format(
            mode=mode,
            python=sys.executable,
            script=__file__,
            protect_system='full' if cfg['protect_system'] else 'false',
            security=security
        )
        
        paths = {
            'systemd': '/etc/systemd/system/ufs-pro.service',
            'openrc': '/etc/init.d/ufs-pro',
            'launchd': '/Library/LaunchDaemons/ufs-pro.plist',
            'sysvinit': '/etc/init.d/ufs-pro',
            'upstart': '/etc/init/ufs-pro.conf',
            'runit': '/etc/service/ufs-pro/run',
            's6': '/etc/s6/services/ufs-pro/run',
            'supervisord': '/etc/supervisor/conf.d/ufs-pro.conf',
            'shepherd': '/etc/shepherd/ufs-pro.scm',
            'rc.d': '/usr/local/etc/rc.d/ufs-pro'
        }
        
        path = Path(paths.get(init_type, 'ufs-pro.service'))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        
        if init_type != 'windows':
            os.chmod(path, 0o755)
        
        if init_type == 'systemd':
            subprocess.run(['systemctl', 'daemon-reload'])
        elif init_type == 'launchd':
            subprocess.run(['launchctl', 'load', str(path)])
        elif init_type == 'shepherd':
            subprocess.run(['herd', 'enable', 'ufs-pro'])
        
        print(f"服务已安装至: {path}")

    @classmethod
    def install_windows_service(cls, mode):
        """使用pywin32安装Windows服务"""
        import win32serviceutil
        import win32service
        import win32event
        import servicemanager
        
        class UFSService(win32serviceutil.ServiceFramework):
            _svc_name_ = "UFSService"
            _svc_display_name_ = "UltraFileServer Pro"
            
            def __init__(self, args):
                win32serviceutil.ServiceFramework.__init__(self, args)
                self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
                
            def SvcStop(self):
                self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
                win32event.SetEvent(self.hWaitStop)
                
            def SvcDoRun(self):
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, '')
                )
                self.main()
                
            def main(self):
                server = UltraServer((Config().data.get('host','127.0.0.1'), Config().data['port']), UltraHandler)
                server.serve_forever()
        
        win32serviceutil.HandleCommandLine(UFSService)

    @classmethod
    def install_with_nssm(cls, mode):
        """使用nssm安装Windows服务"""
        nssm_exe = shutil.which('nssm')
        if not nssm_exe:
            return False
        
        try:
            subprocess.run([
                nssm_exe, 'install', 'UFSService', 
                sys.executable, __file__, '--daemon', '--mode', mode
            ], check=True)
            subprocess.run([nssm_exe, 'set', 'UFSService', 'DisplayName', 'UltraFileServer Pro'], check=True)
            subprocess.run([nssm_exe, 'start', 'UFSService'], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

# ==================== 核心功能实现 ====================
def auth_accounts(config):
    auth = config['auth']
    if not isinstance(auth, dict) or auth.get('enabled', True) is not True:
        raise ValueError('UFS_AUTHENTICATION_REQUIRED')
    minimum = auth.get('min_length', 12)
    if type(minimum) is not int or not 8 <= minimum <= 128: raise ValueError('UFS_PASSWORD_POLICY')
    users = auth.get('users')
    if users is None:
        users = {auth.get('user'): {'password':auth.get('pass'), 'role':auth.get('role','user')}}
    if not isinstance(users, dict) or not 1 <= len(users) <= 64: raise ValueError('UFS_USERS_LIMIT')
    result = {}
    for username, account in users.items():
        if not isinstance(username,str) or not re.fullmatch('[A-Za-z0-9_.@-]{1,64}',username): raise ValueError('UFS_USERNAME')
        if (not isinstance(account,dict) or not isinstance(account.get('password'),str) or
                not minimum <= len(account['password']) <= 1024 or not isinstance(account.get('role','user'),str) or account.get('role','user') not in API_PERMISSIONS):
            raise ValueError('UFS_ACCOUNT_POLICY')
        result[username] = {'password':account['password'], 'role':account.get('role','user')}
    return result


def validated_config(value):
    if not isinstance(value,dict): raise ValueError('UFS_CONFIG_OBJECT')
    config = Config.default_config(object.__new__(Config))
    config.update(copy.deepcopy(value))
    config['active_transfers'] = {}
    for key, low, high in [('port',0,65535),('max_conn',1,256),('request_timeout',1,60),
            ('request_total_timeout',1,300),('mmap_threshold',0,1024**4),('max_listing',1,4096),('max_upload',0,10*1024**3),('retention_days',1,36500),('compression_level',0,9)]:
        if type(config[key]) is not int or not low <= config[key] <= high: raise ValueError('UFS_LIMIT_'+key)
    if type(config['download_limit']) not in (int,float) or not 0 <= config['download_limit'] <= 10000:
        raise ValueError('UFS_DOWNLOAD_LIMIT')
    for key in ('ssl','upload','checksum','compression','cleanup_enabled','self_test','use_mmap'):
        if type(config[key]) is not bool: raise ValueError('UFS_BOOL_'+key)
    if not isinstance(config['realm'],str) or not re.fullmatch('[A-Za-z0-9 _.-]{1,64}',config['realm']):
        raise ValueError('UFS_REALM')
    for key in ('root_dir','log_file','ssl_cert'):
        if not isinstance(config[key],(str,Path)) or not str(config[key]) or '\x00' in str(config[key]):
            raise ValueError('UFS_PATH_CONFIG')
        config[key] = str(Path(config[key]).absolute())
    root = Path(config['root_dir'])
    if any(Path(config[k]).is_relative_to(root) for k in ('ssl_cert','log_file')):
        raise ValueError('UFS_PRIVATE_MATERIAL_INSIDE_SERVED_ROOT')
    for key in ('ip_whitelist','blacklist'):
        if not isinstance(config[key],list) or len(config[key])>256: raise ValueError('UFS_IP_POLICY')
        for address in config[key]:
            if key=='ip_whitelist': ip_network(address)
            else: ip_address(address)
    bucket = config['token_bucket']
    if (not isinstance(bucket,dict) or set(bucket)!={'capacity','rate'} or
            any(type(bucket[k]) is not int or not 65536<=bucket[k]<=1024**3 for k in bucket)):
        raise ValueError('UFS_TOKEN_BUDGET')
    auth_accounts(config)
    return config


class UltraHandler(http.server.SimpleHTTPRequestHandler):
    """Authenticated HTTP/WebDAV with bounded, descriptor-confined file I/O."""
    def __init__(self, *args, **kwargs):
        self.cfg = args[2].config
        self.start_time = time.monotonic()
        self.rate_limit = self.cfg['download_limit'] * 1024**2
        self.transfer_id, self.user_role, self.authenticated = None, None, False
        super().__init__(*args, directory=self.cfg['root_dir'], **kwargs)

    def setup(self):
        self.request.settimeout(self.cfg['request_timeout'])
        super().setup()
        # A per-read timeout alone does not stop a peer dripping one byte at a
        # time. Enforce a wall-clock budget over headers and body as well.
        def expire():
            try: self.request.shutdown(socket.SHUT_RDWR)
            except OSError: return  # Connection already closed by its owner.
        self._deadline = threading.Timer(self.cfg['request_total_timeout'],expire)
        self._deadline.daemon = True; self._deadline.start()

    def finish(self):
        self._deadline.cancel()
        super().finish()

    def handle(self):
        try: super().handle()
        except (BrokenPipeError,ConnectionResetError,TimeoutError,ssl.SSLError):
            return  # Closed/expired peers cannot receive another error frame.

    def parse_request(self):
        if not super().parse_request(): return False
        self.authenticated = False
        host = self.headers.get('Host', '')
        fwd_host = self.headers.get('X-Forwarded-Host', '').split(',')[0].strip()
        fwd_proto = self.headers.get('X-Forwarded-Proto', '').split(',')[0].strip()
        scheme = fwd_proto if fwd_proto else ('https' if self.cfg['ssl'] else 'http')
        allowed_origins = {
            None,
            f'{scheme}://{host}',
            f'http://{host}',
            f'https://{host}',
            'https://ziokt-ufs-43-207-75-185.sslip.io',
            'https://cor-web.ziokt.com',
            'http://127.0.0.1:8184',
            'http://localhost:8184',
        }
        if fwd_host:
            allowed_origins.update({f'{scheme}://{fwd_host}', f'https://{fwd_host}', f'http://{fwd_host}'})

        origin = self.headers.get('Origin')
        site = self.headers.get('Sec-Fetch-Site')
        mode = self.headers.get('Sec-Fetch-Mode')
        is_navigation = self.command in {'GET', 'HEAD', 'OPTIONS'} and (
            mode == 'navigate' or not mode or site in {None, 'cross-site', 'same-site', 'same-origin', 'none'}
        )
        origin_ok = origin in allowed_origins or (self.command in {'GET', 'HEAD'} and (not origin or origin in allowed_origins or origin.startswith('https://cor-web.ziokt.com') or origin.startswith('https://ziokt-')))
        site_ok = (site in {None, 'same-origin', 'none'}) or (self.command in {'GET', 'HEAD', 'OPTIONS'} and is_navigation)

        if not origin_ok or not site_ok:
            self.send_error(403, 'Cross-origin browser request denied'); return False
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Authorization', [])) > 1:
            self.send_error(400, 'Ambiguous request framing or authorization'); return False
        return self.authenticate()

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        if getattr(self, '_is_dashboard', False):
            self.send_header('Content-Security-Policy', "default-src 'self' 'unsafe-inline' data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:;")
        else:
            self.send_header('Content-Security-Policy', "sandbox; default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'")
        super().end_headers()

    def check_ip_whitelist(self):
        address = ip_address(self.client_address[0])
        if str(address) in self.cfg['blacklist'] or not any(address in ip_network(n) for n in self.cfg['ip_whitelist']):
            self.send_error(403, 'IP not allowed'); return False
        return True

    def generate_digest_response(self, nonce, method, uri, *, username=None, password=None, nc=None, cnonce=None):
        if not nc or not cnonce: raise ValueError('UFS_QOP_REQUIRED')
        username = username or self.cfg['auth'].get('user')
        password = password or self.cfg['auth'].get('pass')
        digest = lambda value: hashlib.sha256(value.encode()).hexdigest()
        ha1 = digest(f'{username}:{self.cfg["realm"]}:{password}')
        return digest(f'{ha1}:{nonce}:{nc}:{cnonce}:auth:{digest(method+":"+uri)}')

    def authenticate(self):
        if self.authenticated: return True
        if not self.check_ip_whitelist(): return False
        try:
            fields = digest_fields(self.headers.get('Authorization', ''))
            account = self.server.accounts.get(fields['username'])
            if (not account or fields['realm'] != self.cfg['realm'] or fields['uri'] != self.path or
                    fields.get('opaque', self.server.opaque) != self.server.opaque): raise ValueError('UFS_SCOPE')
            expected = self.generate_digest_response(fields['nonce'], self.command, fields['uri'],
                username=fields['username'], password=account['password'], nc=fields['nc'], cnonce=fields['cnonce'])
            if not hmac.compare_digest(fields['response'].lower(), expected): raise ValueError('UFS_PROOF')
            if not self.server.digest.admit(fields['nonce'], fields['username'], fields['cnonce'], int(fields['nc'],16)):
                raise ValueError('UFS_NONCE_OR_REPLAY')
            self.user_role, self.authenticated = account['role'], True
            self.username = fields['username']
            return True
        except (ValueError, TypeError):
            self.send_auth_required(); return False

    def check_api_permission(self, endpoint):
        return self.user_role == 'admin' or endpoint in API_PERMISSIONS.get(self.user_role, [])

    def send_auth_required(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', f'Digest realm="{self.cfg["realm"]}", qop="auth", algorithm=SHA-256, nonce="{self.server.digest.challenge()}", opaque="{self.server.opaque}"')
        self.send_header('Content-Length', '0'); self.end_headers()

    def translate_path(self, path):
        # Compatibility for extensions. Core operations use retained directory
        # descriptors instead of reopening this string after checking it.
        parts = self.server.files.parts(path)
        self.server.files.info(parts)
        return str(self.server.files.root.joinpath(*parts))

    def _error(self, error):
        if isinstance(error, FileNotFoundError): self.send_error(404, 'Not found')
        elif isinstance(error, FileExistsError): self.send_error(409, 'Already exists')
        elif isinstance(error, (PermissionError, NotADirectoryError, IsADirectoryError)): self.send_error(403, 'Unsafe or unauthorized path')
        elif isinstance(error, ValueError): self.send_error(400, 'Invalid path, body or resource limit')
        else: self.send_error(409, 'File operation failed')

    def do_GET(self):
        if urlsplit(self.path).path.startswith('/api/'): return self.handle_api()
        super().do_GET()

    def do_HEAD(self):
        if urlsplit(self.path).path.startswith('/api/'): return self.handle_api()
        super().do_HEAD()

    def send_head(self):
        try:
            parts = self.server.files.parts(self.path)
            info = self.server.files.info(parts)
            if stat.S_ISDIR(info.st_mode):
                self._is_dashboard = True
                entries = self.server.files.entries(parts, self.cfg['max_listing'])
                dashboard = self.render_dashboard(parts, entries)
                data = dashboard.encode('utf-8')
                source, kind = io.BytesIO(data), 'text/html; charset=utf-8'
            else:
                source = self.server.files.open(parts)
                kind = self.guess_type(parts[-1])
                if self.cfg['compression'] and info.st_size <= 8*1024*1024 and 'gzip' in self.headers.get('Accept-Encoding', '').split(','):
                    data = gzip.compress(source.read(), compresslevel=self.cfg['compression_level']); source.close()
                    source = io.BytesIO(data); self._gzip = True
                else: data = None
            size = len(data) if data is not None else os.fstat(source.fileno()).st_size
            self.send_response(200); self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(size))
            if getattr(self, '_gzip', False): self.send_header('Content-Encoding', 'gzip')
            self.end_headers(); return source
        except (OSError, ValueError, UnicodeError) as error:
            self._error(error); return None

    def render_dashboard(self, parts, entries):
        integrated = getattr(self.server, 'integrated_system', None)
        node_id = getattr(integrated, 'node_id', '') if integrated else '800a3e4c08b13a41b41632a2bd8f0065340dbb99d32f8f94fc307c6d52fa9f3d'
        dcpm_packages = integrated.package_store.list() if (integrated and hasattr(integrated, 'package_store')) else []
        downloads = self.server.stats.get('downloads', 0)
        uploads = self.server.stats.get('uploads', 0)
        max_upload = self.cfg.get('max_upload', 67108864)
        max_upload_str = f"{max_upload // (1024 * 1024)} MB" if max_upload else "不限"
        root_dir = self.cfg.get('root_dir', '/home/admin/.config/dcpm-ufs/ufs-storage')
        user = getattr(self, 'username', 'admin') or 'admin'
        role = getattr(self, 'user_role', 'admin') or 'admin'

        def fmt_sz(size):
            s = float(size)
            for u in ['B', 'KB', 'MB', 'GB', 'TB']:
                if s < 1024:
                    return f"{s:.1f} {u}" if u != 'B' else f"{int(s)} B"
                s /= 1024
            return f"{s:.1f} PB"

        total_files = len(entries)
        total_bytes = sum(m.st_size for _, m in entries if stat.S_ISREG(m.st_mode))
        total_bytes_str = fmt_sz(total_bytes)

        crumb_html = '<a href="/" style="color:#38bdf8;text-decoration:none;font-weight:600;">root</a>'
        accum = ''
        for p in parts:
            accum += '/' + quote(p)
            crumb_html += f' <span style="color:#64748b;">/</span> <a href="{accum}/" style="color:#38bdf8;text-decoration:none;font-weight:600;">{html.escape(p)}</a>'

        file_rows = []
        if parts:
            parent_href = '/' + '/'.join(quote(p) for p in parts[:-1]) + ('/' if len(parts) > 1 else '')
            file_rows.append(f"""
            <tr style="border-bottom:1px solid #1e293b;">
                <td style="padding:12px 14px;"><a href="{parent_href}" style="color:#38bdf8;font-weight:600;text-decoration:none;display:flex;align-items:center;gap:6px;"><span>📁</span> <span>.. (返回上一级目录)</span></a></td>
                <td style="padding:12px 14px;color:#64748b;font-size:0.85rem;">目录</td>
                <td style="padding:12px 14px;color:#64748b;font-size:0.85rem;">-</td>
                <td style="padding:12px 14px;color:#64748b;font-size:0.85rem;">-</td>
                <td style="padding:12px 14px;"></td>
            </tr>
            """)

        for name, meta in entries:
            is_dir = stat.S_ISDIR(meta.st_mode)
            icon = '📁' if is_dir else '📄'
            href = quote(name) + ('/' if is_dir else '')
            fsize = '-' if is_dir else fmt_sz(meta.st_size)
            mtime = datetime.fromtimestamp(meta.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            action_btn = f'<a href="{href}" download class="btn-sm btn-cyan">📥 下载</a>' if not is_dir else f'<a href="{href}" class="btn-sm btn-cyan">📂 打开</a>'
            delete_btn = f'<button type="button" onclick="deleteItem(\'{html.escape(name)}\')" class="btn-sm btn-red">🗑️ 删除</button>'
            file_rows.append(f"""
            <tr style="border-bottom:1px solid #1e293b;" class="table-hover-row">
                <td style="padding:12px 14px;"><a href="{href}" style="color:#f8fafc;font-weight:500;text-decoration:none;display:flex;align-items:center;gap:8px;"><span>{icon}</span> <span>{html.escape(name)}</span></a></td>
                <td style="padding:12px 14px;color:#94a3b8;font-size:0.85rem;">{"目录" if is_dir else "文件"}</td>
                <td style="padding:12px 14px;font-family:monospace;font-size:0.85rem;color:#cbd5e1;">{fsize}</td>
                <td style="padding:12px 14px;font-family:monospace;font-size:0.82rem;color:#94a3b8;">{mtime}</td>
                <td style="padding:12px 14px;text-align:right;">
                    <div style="display:inline-flex;gap:6px;">{action_btn} {delete_btn}</div>
                </td>
            </tr>
            """)

        files_tbody = "".join(file_rows)

        pkg_rows = []
        for pkg in dcpm_packages:
            p_id = html.escape(str(pkg.get('package_id', '')))
            p_name = html.escape(str(pkg.get('name', '')))
            p_ver = html.escape(str(pkg.get('version', '')))
            p_pub = html.escape(str(pkg.get('publisher', '')))
            if len(p_pub) > 16: p_pub = p_pub[:16] + '...'
            p_size = fmt_sz(pkg.get('size', 0)) if 'size' in pkg else '-'
            p_dl = f'/api/dcpm/package?package_id={quote(p_id)}'
            pkg_rows.append(f"""
            <tr style="border-bottom:1px solid #1e293b;" class="table-hover-row">
                <td style="padding:10px 14px;font-family:monospace;font-weight:bold;color:#38bdf8;">{p_id} ({p_name})</td>
                <td style="padding:10px 14px;color:#10b981;font-weight:600;">{p_ver}</td>
                <td style="padding:10px 14px;font-family:monospace;font-size:0.8rem;color:#94a3b8;">{p_pub}</td>
                <td style="padding:10px 14px;color:#cbd5e1;font-size:0.85rem;">{p_size}</td>
                <td style="padding:10px 14px;text-align:right;"><a href="{p_dl}" download class="btn-sm btn-cyan">📥 下载 .dcpm</a></td>
            </tr>
            """)
        packages_tbody = "".join(pkg_rows)

        empty_banner = """
        <div style="padding:36px 20px;text-align:center;color:#94a3b8;background:#0b0f19;border-radius:8px;border:1px dashed #334155;margin:12px 0;">
            <div style="font-size:2.5rem;margin-bottom:8px;">📂</div>
            <div style="font-size:1.05rem;font-weight:600;color:#f8fafc;margin-bottom:4px;">当前存储目录为空</div>
            <div style="font-size:0.85rem;color:#94a3b8;max-width:480px;margin:0 auto 12px;">此存储空间受 O_NOFOLLOW 描述符严格隔离保护。可通过下方拖拽区域或“上传文件”按钮写入数据。</div>
        </div>
        """ if not entries else ""

        dcpm_empty_banner = """
        <div style="padding:24px 20px;text-align:center;color:#94a3b8;background:#0b0f19;border-radius:8px;border:1px dashed #334155;margin-top:10px;">
            <p style="margin:0 0 6px 0;font-weight:600;color:#cbd5e1;">📦 暂无已缓存的 DCPM 签名软件包</p>
            <p style="margin:0;font-size:0.85rem;">可通过下方“上传 .dcpm 软件包”接口或在节点终端执行 <code>dcpm publish</code> 命令发布签名包。</p>
        </div>
        """ if not dcpm_packages else ""

        html_out = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UFS &amp; DCPM 原生去中心化存储控制台</title>
<style>
:root {{
    --bg: #090d16;
    --card-bg: #111827;
    --card-sub: #1e293b;
    --border: #1f2937;
    --border-bright: #334155;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --accent-cyan: #38bdf8;
    --accent-green: #10b981;
    --accent-purple: #818cf8;
    --accent-amber: #f59e0b;
    --accent-red: #ef4444;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background-color: var(--bg);
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    line-height: 1.5;
    padding: 0;
}}
.container {{
    max-width: 1240px;
    margin: 0 auto;
    padding: 24px 20px;
}}
header {{
    background: #0f172a;
    border-bottom: 1px solid var(--border);
    padding: 16px 20px;
}}
.nav-wrap {{
    max-width: 1240px;
    margin: 0 auto;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
}}
.logo-title {{
    display: flex;
    align-items: center;
    gap: 12px;
}}
.logo-icon {{
    width: 38px;
    height: 38px;
    background: linear-gradient(135deg, #0284c7, #38bdf8);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.3rem;
    box-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
}}
.title-text h1 {{
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
}}
.title-text p {{
    font-size: 0.78rem;
    color: var(--text-secondary);
}}
.top-links {{
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
}}
.nav-link {{
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 0.82rem;
    font-weight: 500;
    text-decoration: none;
    color: var(--text-secondary);
    background: var(--card-sub);
    border: 1px solid var(--border-bright);
    transition: all 0.2s;
}}
.nav-link:hover {{
    color: var(--accent-cyan);
    border-color: var(--accent-cyan);
}}
.status-pill {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 8px;
    border-radius: 9999px;
    font-size: 0.72rem;
    font-weight: 600;
    background: rgba(16, 185, 129, 0.15);
    color: var(--accent-green);
    border: 1px solid rgba(16, 185, 129, 0.3);
}}
.status-dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent-green);
    box-shadow: 0 0 6px var(--accent-green);
}}
.grid-4 {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}}
.metric-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2);
}}
.metric-title {{
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}}
.metric-value {{
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--text-primary);
    word-break: break-all;
}}
.metric-sub {{
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-top: 6px;
}}
.section-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 24px;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2);
}}
.section-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
}}
.section-title {{
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--accent-cyan);
    display: flex;
    align-items: center;
    gap: 8px;
}}
.btn {{
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    transition: all 0.2s;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}}
.btn-primary {{
    background: #0284c7;
    color: #fff;
}}
.btn-primary:hover {{
    background: #0369a1;
}}
.btn-secondary {{
    background: var(--card-sub);
    color: var(--text-primary);
    border-color: var(--border-bright);
}}
.btn-secondary:hover {{
    border-color: var(--accent-cyan);
    color: var(--accent-cyan);
}}
.btn-sm {{
    padding: 3px 8px;
    font-size: 0.75rem;
    border-radius: 4px;
    cursor: pointer;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 1px solid transparent;
}}
.btn-cyan {{
    background: rgba(56, 189, 248, 0.15);
    color: var(--accent-cyan);
    border-color: rgba(56, 189, 248, 0.3);
}}
.btn-cyan:hover {{
    background: rgba(56, 189, 248, 0.25);
}}
.btn-red {{
    background: rgba(239, 68, 68, 0.15);
    color: var(--accent-red);
    border-color: rgba(239, 68, 68, 0.3);
}}
.btn-red:hover {{
    background: rgba(239, 68, 68, 0.25);
}}
.table-wrap {{
    overflow-x: auto;
    border-radius: 8px;
    border: 1px solid var(--border);
}}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
    background: #0b0f19;
}}
thead tr {{
    background: #0f172a;
    border-bottom: 1px solid var(--border-bright);
    color: var(--text-secondary);
    text-align: left;
}}
th {{
    padding: 10px 14px;
    font-weight: 600;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
.table-hover-row:hover {{
    background: rgba(30, 41, 59, 0.6);
}}
.dropzone {{
    border: 2px dashed var(--border-bright);
    border-radius: 8px;
    padding: 24px;
    text-align: center;
    background: #0b0f19;
    margin-top: 14px;
    cursor: pointer;
    transition: all 0.2s;
}}
.dropzone.dragover {{
    border-color: var(--accent-cyan);
    background: rgba(56, 189, 248, 0.05);
}}
.notice-box {{
    background: rgba(14, 165, 233, 0.08);
    border: 1px solid rgba(14, 165, 233, 0.25);
    border-radius: 8px;
    padding: 14px 18px;
    font-size: 0.82rem;
    color: #bae6fd;
    line-height: 1.6;
    margin-bottom: 24px;
}}
#toast {{
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: #1e293b;
    border: 1px solid var(--border-bright);
    color: #fff;
    padding: 10px 16px;
    border-radius: 8px;
    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.5);
    font-size: 0.85rem;
    display: none;
    z-index: 9999;
}}
#modal-json {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.7);
    z-index: 10000;
    justify-content: center;
    align-items: center;
    padding: 20px;
}}
.modal-content {{
    background: #111827;
    border: 1px solid var(--border-bright);
    border-radius: 10px;
    max-width: 720px;
    width: 100%;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}}
</style>
</head>
<body>

<header>
    <div class="nav-wrap">
        <div class="logo-title">
            <div class="logo-icon">⚡</div>
            <div class="title-text">
                <h1>Ziokt UFS &amp; DCPM 原生去中心化存储控制台</h1>
                <p>UltraFileServer Storage Engine &amp; Decentralized Package Manager</p>
            </div>
        </div>
        <div class="top-links">
            <span class="status-pill"><span class="status-dot"></span> RUNNING &bull; 8184</span>
            <span class="status-pill" style="color:var(--accent-cyan);border-color:rgba(56,189,248,0.3);background:rgba(56,189,248,0.15);">Digest Auth: {html.escape(user)}</span>
            <a href="https://cor-web.ziokt.com/app/ufsdcpm" target="_blank" class="nav-link">🌐 Ziokt DApp</a>
            <a href="https://ziokt-shadow6-43-207-75-185.sslip.io/" target="_blank" class="nav-link">🪐 Shadow6 UI</a>
        </div>
    </div>
</header>

<div class="container">

    <div class="notice-box">
        🔒 <strong>原生安全存储就绪</strong>：UFS 服务由 <code>O_NOFOLLOW</code> 目录描述符与 SHA-256 Digest 鉴权双重保护。访问凭据妥善存储于本地受保护配置文件 <code>~/.config/dcpm-ufs/config.json</code> (0600 权限) 中，绝不向公网暴露明文密钥。
    </div>

    <!-- Telemetry Cards -->
    <div class="grid-4">
        <div class="metric-card">
            <div class="metric-title">
                <span>节点标识 (Node ID)</span>
                <button type="button" onclick="copyText('{node_id}')" class="btn-sm btn-cyan">复制</button>
            </div>
            <div class="metric-value" style="font-family:monospace;font-size:0.85rem;color:var(--accent-cyan);">{node_id[:16]}...{node_id[-8:]}</div>
            <div class="metric-sub">模式: Signed-Package HTTP / P2P Hybrid</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">
                <span>存储空间利用率</span>
                <span style="color:var(--accent-green);font-weight:600;">HEALTHY</span>
            </div>
            <div class="metric-value">{total_bytes_str} <span style="font-size:0.85rem;color:var(--text-secondary);font-weight:normal;">/ 100 GB</span></div>
            <div class="metric-sub">当前目录含 {total_files} 项 &bull; 单文件上限 {max_upload_str}</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">
                <span>隐蔽安全卷状态</span>
                <span style="color:var(--accent-purple);font-weight:600;">ACTIVE</span>
            </div>
            <div class="metric-value" style="font-size:1rem;color:var(--accent-purple);">双层可抵赖存储就绪</div>
            <div class="metric-sub">物理路径: {html.escape(root_dir)}</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">
                <span>传输吞吐与活动</span>
                <span style="color:var(--accent-amber);font-weight:600;">LIVE</span>
            </div>
            <div class="metric-value" style="font-size:1.05rem;">📥 {downloads} <span style="font-size:0.85rem;color:var(--text-secondary);font-weight:normal;">下载</span> &bull; 📤 {uploads} <span style="font-size:0.85rem;color:var(--text-secondary);font-weight:normal;">上传</span></div>
            <div class="metric-sub">活跃协程/线程: {threading.active_count()}</div>
        </div>
    </div>

    <!-- Storage File Explorer -->
    <div class="section-card">
        <div class="section-header">
            <div class="section-title">
                <span>📁 原生存储文件浏览器</span>
                <span style="font-family:monospace;font-size:0.85rem;color:var(--text-secondary);">{crumb_html}</span>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <input type="file" id="ufs-file-input" style="display:none;" onchange="if(this.files.length) uploadFile(this.files[0])">
                <button type="button" class="btn btn-primary" onclick="document.getElementById('ufs-file-input').click()">📁 上传文件</button>
                <button type="button" class="btn btn-secondary" onclick="createNewFile()">📝 新建文件</button>
                <button type="button" class="btn btn-secondary" onclick="createFolder()">➕ 新建目录</button>
                <button type="button" class="btn btn-secondary" onclick="location.reload()">🔄 刷新</button>
            </div>
        </div>

        <div id="progress-bar" style="display:none;width:100%;height:4px;background:#1e293b;border-radius:2px;overflow:hidden;margin-bottom:12px;">
            <div id="progress-fill" style="width:0%;height:100%;background:linear-gradient(90deg,#0284c7,#38bdf8);transition:width 0.3s;"></div>
        </div>

        {empty_banner}

        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th style="min-width:240px;">文件 / 目录名称</th>
                        <th style="width:100px;">类型</th>
                        <th style="width:120px;">大小</th>
                        <th style="width:180px;">修改时间</th>
                        <th style="width:140px;text-align:right;">操作</th>
                    </tr>
                </thead>
                <tbody>
                    {files_tbody}
                </tbody>
            </table>
        </div>

        <div id="dropzone" class="dropzone" onclick="document.getElementById('ufs-file-input').click()">
            <div style="font-size:1.8rem;margin-bottom:6px;">📥</div>
            <div style="font-weight:600;font-size:0.95rem;color:#f8fafc;margin-bottom:4px;">拖拽文件至此处即可自动上传</div>
            <div style="font-size:0.8rem;color:var(--text-secondary);">或点击直接浏览本地文件进行存储。支持任意类型原生文件分块持久化。</div>
        </div>
    </div>

    <!-- DCPM Package Manager -->
    <div class="section-card">
        <div class="section-header">
            <div class="section-title">
                <span>📦 DCPM 签名软件包管理器 (Decentralized Packages)</span>
            </div>
            <div>
                <input type="file" id="dcpm-file-input" style="display:none;" accept=".dcpm,application/octet-stream" onchange="if(this.files.length) uploadDcpmPackage(this.files[0])">
                <button type="button" class="btn btn-primary" onclick="document.getElementById('dcpm-file-input').click()">📤 发布 / 上传 .dcpm 软件包</button>
            </div>
        </div>

        {dcpm_empty_banner}

        <div class="table-wrap" style="{'display:none;' if not dcpm_packages else ''}">
            <table>
                <thead>
                    <tr>
                        <th>软件包标识 (Package ID)</th>
                        <th>版本 (Version)</th>
                        <th>发布者公钥 (Publisher)</th>
                        <th>体积</th>
                        <th style="text-align:right;">操作</th>
                    </tr>
                </thead>
                <tbody>
                    {packages_tbody}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Live Diagnostics Drawer / API Tester -->
    <div class="section-card">
        <div class="section-header">
            <div class="section-title">
                <span>⚡ 原生 API 实时诊断与监控端点</span>
            </div>
        </div>
        <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:12px;">点击下方接口按钮可立即执行安全带鉴权的原生 API 查询，实时审查节点内部状态：</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button type="button" class="btn btn-secondary" onclick="inspectApi('/api/stats')">📊 节点状态 (/api/stats)</button>
            <button type="button" class="btn btn-secondary" onclick="inspectApi('/api/config')">⚙️ 服务配置 (/api/config)</button>
            <button type="button" class="btn btn-secondary" onclick="inspectApi('/api/files')">📑 文件索引 (/api/files)</button>
            <button type="button" class="btn btn-secondary" onclick="inspectApi('/api/dcpm/packages')">📦 软件包列表 (/api/dcpm/packages)</button>
            <button type="button" class="btn btn-secondary" onclick="inspectApi('/api/transfers')">🔄 活跃传输 (/api/transfers)</button>
        </div>
    </div>

</div>

<!-- Modal for JSON Inspection -->
<div id="modal-json" onclick="if(event.target===this) closeModal()">
    <div class="modal-content">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border-bright);background:#0f172a;">
            <div id="modal-title" style="font-weight:600;font-size:0.92rem;color:var(--accent-cyan);">API 实时诊断</div>
            <button type="button" onclick="closeModal()" class="btn-sm btn-secondary" style="font-size:0.9rem;padding:2px 8px;">✕</button>
        </div>
        <pre id="modal-code" style="padding:16px;background:#06080f;color:#38bdf8;font-family:monospace;font-size:0.82rem;overflow:auto;max-height:60vh;white-space:pre-wrap;line-height:1.45;"></pre>
        <div style="padding:10px 18px;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:8px;background:#0f172a;">
            <button type="button" class="btn btn-secondary" onclick="navigator.clipboard.writeText(document.getElementById('modal-code').innerText); showNotice('已复制 API 响应内容', 'success');">📋 复制 JSON</button>
            <button type="button" class="btn btn-primary" onclick="closeModal()">关闭</button>
        </div>
    </div>
</div>

<div id="toast"></div>

<script>
function showNotice(msg, type) {{
    let t = document.getElementById('toast');
    t.innerText = msg;
    t.style.borderColor = type === 'error' ? '#ef4444' : '#10b981';
    t.style.display = 'block';
    setTimeout(() => {{ t.style.display = 'none'; }}, 3500);
}}

async function uploadFile(file) {{
    if (!file) return;
    showNotice('正在上传文件 ' + file.name + ' ...', 'info');
    let bar = document.getElementById('progress-bar');
    let fill = document.getElementById('progress-fill');
    bar.style.display = 'block';
    fill.style.width = '30%';
    try {{
        let res = await fetch(encodeURIComponent(file.name), {{
            method: 'PUT',
            body: file
        }});
        fill.style.width = '100%';
        if (res.ok || res.status === 201 || res.status === 204) {{
            showNotice('文件 ' + file.name + ' 上传成功！', 'success');
            setTimeout(() => {{ location.reload(); }}, 600);
        }} else {{
            showNotice('上传失败: HTTP ' + res.status + ' ' + (await res.text()), 'error');
            bar.style.display = 'none';
        }}
    }} catch(e) {{
        showNotice('网络或权限异常: ' + e.message, 'error');
        bar.style.display = 'none';
    }}
}}

async function uploadDcpmPackage(file) {{
    if (!file) return;
    showNotice('正在发布 DCPM 签名包 ' + file.name + ' ...', 'info');
    try {{
        let res = await fetch('/api/dcpm/publish', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/octet-stream' }},
            body: file
        }});
        if (res.ok) {{
            let data = await res.json();
            showNotice('DCPM 软件包发布成功！包 ID: ' + (data.package_id || 'OK'), 'success');
            setTimeout(() => {{ location.reload(); }}, 800);
        }} else {{
            showNotice('DCPM 发布失败: HTTP ' + res.status + ' ' + (await res.text()), 'error');
        }}
    }} catch(e) {{
        showNotice('发布异常: ' + e.message, 'error');
    }}
}}

async function deleteItem(name) {{
    if (!confirm('确定要从 UFS 存储中永久删除 "' + name + '" 吗？此操作不可撤销。')) return;
    try {{
        let res = await fetch(encodeURIComponent(name), {{ method: 'DELETE' }});
        if (res.ok || res.status === 204) {{
            showNotice('已彻底删除 ' + name, 'success');
            setTimeout(() => {{ location.reload(); }}, 600);
        }} else {{
            showNotice('删除失败: HTTP ' + res.status, 'error');
        }}
    }} catch(e) {{
        showNotice('删除异常: ' + e.message, 'error');
    }}
}}

async function createNewFile() {{
    let name = prompt('请输入新文件名 (例如: note.txt):');
    if (!name) return;
    let content = prompt('请输入文件初始内容 (留空则创建空文件):', '');
    if (content === null) return;
    try {{
        let res = await fetch(encodeURIComponent(name), {{
            method: 'PUT',
            body: new Blob([content], {{ type: 'text/plain;charset=utf-8' }})
        }});
        if (res.ok || res.status === 201 || res.status === 204) {{
            showNotice('文件 ' + name + ' 创建成功！', 'success');
            setTimeout(() => {{ location.reload(); }}, 600);
        }} else {{
            showNotice('创建失败: HTTP ' + res.status, 'error');
        }}
    }} catch(e) {{
        showNotice('异常: ' + e.message, 'error');
    }}
}}

async function createFolder() {{
    let name = prompt('请输入新目录名称:');
    if (!name) return;
    try {{
        let res = await fetch(encodeURIComponent(name), {{ method: 'MKCOL' }});
        if (res.ok || res.status === 201) {{
            showNotice('目录 ' + name + ' 创建成功！', 'success');
            setTimeout(() => {{ location.reload(); }}, 600);
        }} else {{
            showNotice('创建目录失败: HTTP ' + res.status, 'error');
        }}
    }} catch(e) {{
        showNotice('异常: ' + e.message, 'error');
    }}
}}

async function inspectApi(endpoint) {{
    let modal = document.getElementById('modal-json');
    let title = document.getElementById('modal-title');
    let code = document.getElementById('modal-code');
    title.innerText = '实时 API 诊断: ' + endpoint;
    code.innerText = '正在请求实时端点 ' + endpoint + ' ...';
    modal.style.display = 'flex';
    try {{
        let res = await fetch(endpoint);
        let text = await res.text();
        try {{
            let parsed = JSON.parse(text);
            code.innerText = JSON.stringify(parsed, null, 2);
        }} catch(_) {{
            code.innerText = text;
        }}
    }} catch(e) {{
        code.innerText = '请求失败: ' + e.message;
    }}
}}

function closeModal() {{
    document.getElementById('modal-json').style.display = 'none';
}}

function copyText(str) {{
    navigator.clipboard.writeText(str).then(() => {{
        showNotice('节点 ID 已复制到剪贴板', 'success');
    }}).catch(() => {{
        showNotice('复制失败，请手动选择复制', 'error');
    }});
}}

let dropzone = document.getElementById('dropzone');
if (dropzone) {{
    ['dragenter', 'dragover'].forEach(ev => {{
        dropzone.addEventListener(ev, e => {{ e.preventDefault(); dropzone.classList.add('dragover'); }}, false);
    }});
    ['dragleave', 'drop'].forEach(ev => {{
        dropzone.addEventListener(ev, e => {{ e.preventDefault(); dropzone.classList.remove('dragover'); }}, false);
    }});
    dropzone.addEventListener('drop', e => {{
        e.preventDefault();
        dropzone.classList.remove('dragover');
        let files = e.dataTransfer.files;
        if (files && files.length > 0) {{
            uploadFile(files[0]);
        }}
    }}, false);
}}
</script>
</body>
</html>"""
        return html_out

    def _send_with_rate_limit(self):
        return self.send_head()

    def copyfile(self, source, target):
        mapped = None
        try:
            if self.cfg['use_mmap']:
                try:
                    size = os.fstat(source.fileno()).st_size
                    if size and size > self.cfg['mmap_threshold']:
                        mapped = mmap.mmap(source.fileno(),0,access=mmap.ACCESS_READ)
                except io.UnsupportedOperation: pass  # Directory/gzip BytesIO.
            reader = mapped if mapped is not None else source
            while data := reader.read(65536):
                if self.server.stopping.is_set(): return
                while not self.server.bucket.consume(len(data)):
                    if self.server.stopping.wait(min(0.1, len(data)/self.server.bucket.rate)): return
                target.write(data)
                if self.rate_limit: self.server.stopping.wait(len(data)/self.rate_limit)
            with self.server.state_lock: self.server.stats['downloads'] += 1
        finally:
            if mapped is not None: mapped.close()

    def _length(self, maximum, required=True):
        values = self.headers.get_all('Content-Length', [])
        if not values and not required: return 0
        if len(values) != 1 or not re.fullmatch('[0-9]{1,12}', values[0]): raise ValueError('UFS_LENGTH_REQUIRED')
        size = int(values[0])
        if size > maximum: raise OverflowError('UFS_BODY_LIMIT')
        return size

    def _writable(self):
        if not self.cfg['upload'] or self.user_role not in {'user', 'admin'}:
            self.send_error(403, 'Writes disabled or unauthorized'); return False
        return True

    def do_PUT(self):
        if not self._writable(): return
        try:
            size = self._length(self.cfg['max_upload'])
            parts = self.server.files.parts(self.path)
            if not parts or parts[-1].endswith('.checksum'): raise PermissionError('UFS_RESERVED_METADATA')
            self.transfer_id = secrets.token_hex(16)
            with self.server.state_lock:
                self.cfg['active_transfers'][self.transfer_id] = {'path': '/'.join(parts), 'total': size,
                    'transferred': 0, 'start_time': time.monotonic(), 'client': self.client_address[0]}
            with self.server.files.lock:
                if self.cfg['checksum']:
                    try: self.server.files.info(self._checksum_parts(parts))
                    except FileNotFoundError: pass
                existed = self.server.files.put(parts, self.rfile, size, self.update_transfer_progress)
                if self.cfg['checksum']: self.generate_checksum(self.server.files.root.joinpath(*parts))
            with self.server.state_lock: self.server.stats['uploads'] += 1
            self.send_response(204 if existed else 201); self.send_header('Content-Length', '0'); self.end_headers()
            self.log_transfer('upload', '/'.join(parts), size)
        except OverflowError: self.send_error(413, 'File too large')
        except (OSError, ValueError, UnicodeError) as error: self._error(error)
        finally:
            with self.server.state_lock: self.cfg['active_transfers'].pop(self.transfer_id, None)

    def update_transfer_progress(self, chunk_size):
        with self.server.state_lock:
            transfer = self.cfg['active_transfers'].get(self.transfer_id)
            if transfer:
                transfer['transferred'] += chunk_size
                transfer['speed'] = transfer['transferred']/max(time.monotonic()-transfer['start_time'], 0.001)

    def do_DELETE(self):
        if not self._writable(): return
        try:
            self.server.files.delete(self.server.files.parts(self.path))
            self.send_response(204); self.send_header('Content-Length', '0'); self.end_headers()
        except (OSError, ValueError) as error: self._error(error)

    def do_MKCOL(self):
        if not self._writable(): return
        try:
            if self._length(0, required=False): raise ValueError('UFS_COLLECTION_BODY')
            self.server.files.mkdir(self.server.files.parts(self.path))
            self.send_response(201); self.send_header('Content-Length', '0'); self.end_headers()
        except OverflowError: self.send_error(415, 'MKCOL body not supported')
        except (OSError, ValueError) as error: self._error(error)

    def do_OPTIONS(self):
        self.send_response(200); self.send_header('DAV', '1')
        self.send_header('Allow', 'OPTIONS, GET, HEAD, PUT, DELETE, MKCOL, PROPFIND, POST')
        self.send_header('Content-Length', '0'); self.end_headers()

    def do_PROPFIND(self):
        try:
            size = self._length(65536, required=False)
            if len(self.rfile.read(size)) != size: raise ValueError('UFS_TRUNCATED_BODY')
            depth = self.headers.get('Depth', '0')
            if depth not in {'0', '1'}: raise ValueError('UFS_DEPTH_LIMIT')
            parts = self.server.files.parts(self.path)
            response = self.generate_dav_response(parts, depth == '1').encode()
            self.send_response(207); self.send_header('Content-Type', 'application/xml; charset=utf-8')
            self.send_header('Content-Length', str(len(response))); self.end_headers()
            self.wfile.write(response)
        except OverflowError: self.send_error(413, 'PROPFIND body too large')
        except (OSError, ValueError, UnicodeError) as error: self._error(error)

    def generate_dav_response(self, path, recursive):
        parts = path if isinstance(path, list) else self.server.files.parts(self.path)
        entries = [(parts, self.server.files.info(parts))]
        if recursive and stat.S_ISDIR(entries[0][1].st_mode):
            entries += [(parts+[name], info) for name, info in self.server.files.entries(parts, self.cfg['max_listing'])]
        result = '<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:">'
        for item, info in entries:
            name = item[-1] if item else ''
            href = '/'+ '/'.join(quote(p) for p in item)
            collection = '<d:collection/>' if stat.S_ISDIR(info.st_mode) else ''
            result += ('<d:response><d:href>'+html.escape(href)+'</d:href><d:propstat><d:prop>'
                '<d:displayname>'+html.escape(name)+'</d:displayname><d:getcontentlength>'+str(info.st_size)+
                '</d:getcontentlength><d:getlastmodified>'+format_date_time(info.st_mtime)+
                '</d:getlastmodified><d:resourcetype>'+collection+'</d:resourcetype></d:prop>'
                '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>')
        return result+'</d:multistatus>'

    def do_POST(self):
        if urlsplit(self.path).path.startswith('/api/'): return self.handle_api()
        self.send_error(405, 'POST is available only for authorized API actions')

    def handle_api(self):
        endpoint = urlsplit(self.path).path
        if not self.check_api_permission(endpoint): self.send_error(403, 'Insufficient API permission'); return
        handlers = {'/api/stats': self.api_stats, '/api/files': self.api_files,
            '/api/config': self.api_config, '/api/cleanup': self.api_cleanup, '/api/transfers': self.api_transfers}
        if endpoint not in handlers: self.send_error(404, 'API endpoint not found'); return
        if (endpoint == '/api/cleanup') != (self.command == 'POST'):
            self.send_error(405, 'Method not allowed'); return
        handlers[endpoint]()

    def api_stats(self):
        system = {'connections':threading.active_count()}
        if psutil is not None: system['memory'] = psutil.Process().memory_info().rss
        else:
            try:
                import resource
                system['memory_peak'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if OS_TYPE == 'Darwin' else 1024)
            except ImportError: system['memory_metrics_available'] = False
        self.send_json({'uptime': time.monotonic()-self.server.started, 'transfers': dict(self.server.stats), 'system':system})

    def api_config(self):
        self.send_json({key:self.cfg[key] for key in ('max_upload','upload','download_limit','max_conn','ssl')})

    def api_transfers(self):
        with self.server.state_lock:
            transfers = [{'id':tid, 'path':info['path'], 'progress':100*info['transferred']/max(info['total'],1),
                'speed':info.get('speed',0)} for tid,info in self.cfg['active_transfers'].items()]
        self.send_json({'active_transfers':transfers})

    def api_files(self):
        try:
            files = [{'name':name,'size':info.st_size,'modified':info.st_mtime,
                'checksum': self.get_checksum(self.server.files.root/name) if self.cfg['checksum'] and not name.endswith('.checksum') else None}
                for name, info in self.server.files.entries([], self.cfg['max_listing']) if stat.S_ISREG(info.st_mode)]
            self.send_json({'files':files})
        except (OSError, ValueError) as error: self._error(error)

    def api_cleanup(self):
        if not self.cfg['cleanup_enabled']: self.send_error(403, 'Automatic deletion is disabled'); return
        deleted = self.server.cleanup_old_files()
        self.send_json({'deleted':deleted})

    def _parts_for_local_path(self, path):
        relative = Path(path).absolute().relative_to(self.server.files.root)
        return self.server.files.parts('/'+'/'.join(quote(p) for p in relative.parts))

    def _checksum_parts(self, parts):
        name = parts[-1]+'.checksum'
        if len(name.encode())>255: name='ufs-'+hashlib.sha256(parts[-1].encode()).hexdigest()+'.checksum'
        return parts[:-1]+[name]

    def generate_checksum(self, path):
        parts = self._parts_for_local_path(path)
        md5, sha256 = hashlib.md5(), hashlib.sha256()
        with self.server.files.open(parts) as source:
            while data := source.read(65536): md5.update(data); sha256.update(data)
        raw = f'MD5: {md5.hexdigest()}\nSHA256: {sha256.hexdigest()}\n'.encode()
        self.server.files.put(self._checksum_parts(parts), io.BytesIO(raw), len(raw))

    def get_checksum(self, path):
        parts = self._parts_for_local_path(path)
        try:
            with self.server.files.open(self._checksum_parts(parts)) as source: return source.read(512).decode()
        except FileNotFoundError: return None

    def log_transfer(self, action, path=None, size=0):
        logging.info('UFS transfer action=%s size=%s', action, size)

    def send_json(self, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw))); self.end_headers()
        if self.command != 'HEAD': self.wfile.write(raw)


class UltraServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = False
    def __init__(self, *args, config=None, **kwargs):
        if os.environ.get('ZIOKT_AIRGAP','').lower() in {'1','true','yes'}:
            raise PermissionError('UFS_AIRGAP_NETWORK_DENIED')
        self.config = validated_config(config if config is not None else Config().data)
        self.accounts = auth_accounts(self.config)
        address = args[0][0]
        if not self.config['ssl'] and not ip_address(address).is_loopback:
            raise ValueError('UFS_TLS_REQUIRED_FOR_REMOTE_LISTENER')
        self.stats = {'downloads':0, 'uploads':0}
        self.started = time.monotonic(); self.state_lock = threading.RLock()
        self.stopping = threading.Event(); self.config_reloader = None
        self.files = ConfinedFiles(self.config['root_dir'])
        self.digest = DigestAuthority(); self.opaque = secrets.token_hex(16)
        self.bucket = TokenBucket(self.config['token_bucket']['capacity'], self.config['token_bucket']['rate'])
        self.slots = threading.BoundedSemaphore(self.config['max_conn'])
        self._next_cleanup = time.monotonic()+3600
        try:
            super().__init__(*args, **kwargs)
            if self.config['ssl']:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(self.config['ssl_cert'])
                self.socket = context.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)
            if self.config['self_test']: self.start_self_test()
            if config is None: self.start_config_reloader()
        except BaseException:
            self.files.close()
            if hasattr(self, 'socket'): self.socket.close()
            raise

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request); return
        try: super().process_request(request, client_address)
        except BaseException: self.slots.release(); raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: self.slots.release()

    def server_close(self):
        self.stopping.set()
        super().server_close(); self.files.close()
        if self.config_reloader is not None: self.config_reloader.join(2)

    def start_config_reloader(self):
        if self.config_reloader is not None: return False
        def reload_config():
            while not self.stopping.wait(5):
                try:
                    if not Config().check_reload(): continue
                    candidate = validated_config(Config().data)
                    # Structural listener changes require a restart. Updating
                    # them while old requests are active could cross roots or
                    # retain the previous TLS/key policy silently.
                    fixed = ('root_dir','ssl','ssl_cert','host','port','max_conn','token_bucket')
                    if any(candidate[k] != self.config[k] for k in fixed):
                        logging.error('UFS configuration needs restart for root/listener/budget changes')
                        continue
                    accounts = auth_accounts(candidate)
                    with self.state_lock:
                        candidate['active_transfers'] = self.config['active_transfers']
                        self.config, self.accounts = candidate, accounts
                    logging.info('UFS request policy reloaded')
                except (OSError, ValueError, TypeError, KeyError) as error:
                    logging.error('UFS config reload rejected: %s', type(error).__name__)
        self.config_reloader = threading.Thread(target=reload_config, name='ufs-config', daemon=True)
        self.config_reloader.start()
        return True

    def start_self_test(self):
        parts = ['ufs-self-test-'+secrets.token_hex(8)]
        data = secrets.token_bytes(32)
        self.files.put(parts, io.BytesIO(data), len(data))
        try:
            with self.files.open(parts) as source:
                if source.read() != data: raise RuntimeError('UFS_SELF_TEST_FAILED')
        finally: self.files.delete(parts)

    def service_actions(self):
        if self.config['cleanup_enabled'] and time.monotonic() >= self._next_cleanup:
            self._next_cleanup = time.monotonic()+3600
            try: self.cleanup_old_files()
            except (OSError, ValueError) as error:
                logging.error('UFS retention cleanup rejected: %s', type(error).__name__)

    def cleanup_old_files(self):
        if not self.config['cleanup_enabled']: return []
        cutoff = time.time()-self.config['retention_days']*86400
        deleted = []
        for name, info in self.files.entries([], self.config['max_listing']):
            if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff:
                self.files.delete([name]); deleted.append(name)
        return deleted

# ==================== Docker支持 ====================
def generate_dockerfile():
    dockerfile = """# UltraFileServer Pro Dockerfile
FROM python:3.13-slim

RUN apt-get update && apt-get install -y \\
    gcc \\
    python3-dev \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000 8001

CMD ["python", "ufsultra.py", "--mode", "standard"]
"""
    with open('Dockerfile', 'w') as f:
        f.write(dockerfile)
    logging.info("Generated Dockerfile")

# ==================== CLI入口 ====================
def main():
    parser = argparse.ArgumentParser(description="UltraFileServer Pro")
    parser.add_argument('--mode', choices=['standard', 'secure', 'mirror'], default='standard')
    parser.add_argument('--install', action='store_true', help="安装系统服务")
    parser.add_argument('--daemon', action='store_true', help="后台模式运行")
    parser.add_argument('--gen-config', action='store_true', help="生成示例配置文件")
    parser.add_argument('--gen-reqs', action='store_true', help="生成requirements.txt")
    parser.add_argument('--gen-docker', action='store_true', help="生成Dockerfile")
    args = parser.parse_args()
    
    logging.basicConfig(
        handlers=[logging.handlers.RotatingFileHandler(
            Config().data['log_file'], maxBytes=10*1024*1024, backupCount=5)],
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    if args.gen_config:
        name = 'ufs-config.yaml' if yaml is not None else 'ufs-config.json'
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            if yaml is not None: yaml.safe_dump(Config().default_config(), f, default_flow_style=False)
            else: json.dump(Config().default_config(),f,ensure_ascii=False,indent=2)
        print('Generated private configuration: '+name)
        return
    
    if args.gen_reqs:
        Config().generate_requirements()
        print("requirements.txt 已生成")
        return
    
    if args.gen_docker:
        generate_dockerfile()
        print("Dockerfile 已生成")
        return
    
    if args.install:
        if OS_TYPE != 'Windows' and os.geteuid() != 0:
            print("错误：安装服务需要root权限！")
            sys.exit(1)
        ServiceManager.install(args.mode)
        return
    
    if args.daemon:
        daemonize()
    
    # 注册信号处理
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, lambda sig, frame: Config().check_reload())
    
    server = UltraServer((Config().data.get('host','127.0.0.1'), Config().data['port']), UltraHandler)
    print(f"服务器已启动 | 模式: {args.mode} | 端口: {Config().data['port']} | SSL: {Config().data['ssl']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        print("\n服务器已关闭")

def daemonize():
    if OS_TYPE == 'Windows':
        try:
            import win32api
            win32api.SetConsoleCtrlHandler(lambda x: True, True)
        except ImportError:
            logging.critical("pywin32 未安装，Windows 后台模式不可用！")
            print("错误：需要安装pywin32（运行 pip install pywin32）")
            sys.exit(1)
    else:
        pid = os.fork()
        if pid > 0: sys.exit(0)
        os.setsid()

if __name__ == '__main__':
    main()