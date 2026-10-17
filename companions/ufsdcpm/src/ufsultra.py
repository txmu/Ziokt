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
                entries = self.server.files.entries(parts, self.cfg['max_listing'])
                listing = '<!doctype html><meta charset="utf-8"><title>UFS</title><ul>'
                for name, meta in entries:
                    suffix = '/' if stat.S_ISDIR(meta.st_mode) else ''
                    listing += '<li><a href="'+quote(name)+suffix+'">'+html.escape(name)+suffix+'</a></li>'
                data = (listing+'</ul>').encode()
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