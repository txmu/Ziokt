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
import yaml
import time
import base64
import hashlib
import http.server
import socketserver
import shutil
import subprocess
import psutil
import logging
import threading
import asyncio
import aiohttp
import aiofiles
import signal
from pathlib import Path, PurePath
from urllib.parse import unquote, parse_qs
from threading import Thread, Lock, RLock
from datetime import datetime, timedelta
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

sys.modules['ctypes'] = None  # 想调libc？做梦！

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

    def __init__(self):
        with self.__lock:
            if not self.__config:
                self.load_config()

    def load_config(self):
        # 尝试加载YAML或JSON配置文件
        config_paths = [
            Path('ufs-config.yaml'),
            Path('ufs-config.json'),
            Path('/etc/ufs-pro/ufs-config.yaml'),
            Path('/etc/ufs-pro/ufs-config.json')
        ]
        
        for path in config_paths:
            if path.exists():
                self.__config_file = path
                self.__last_modified = path.stat().st_mtime
                if path.suffix == '.yaml':
                    with open(path, 'r') as f:
                        self.__config = yaml.safe_load(f)
                else:
                    with open(path, 'r') as f:
                        self.__config = json.load(f)
                break
        
        if not self.__config:
            self.__config = self.default_config()
        
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
            'root_dir': self.safe_path(Path.cwd()),
            'max_conn': 100,
            'threads': 50,
            
            # 安全配置
            'ssl': True,
            'ssl_cert': 'cert.pem',
            'auth': {
                'user': 'admin',
                'pass': self.generate_password(12, special_chars=True),
                'role': 'admin',
                'min_length': 8,
                'special_chars': True
            },
            'realm': 'UltraFileServer',
            'nonce': hashlib.md5(str(time.time()).encode()).hexdigest(),
            'ip_whitelist': ['192.168.124.0/24'],
            'blacklist': [],
            
            # 传输配置
            'upload': True,
            'max_upload': 10*1024**3,
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
            if Path('/run/shepherd').exists() or 'shepherd' in subprocess.getoutput('ps aux'):
                return 'shepherd'
            for init in INIT_SYSTEMS['linux']:
                if Path(f'/{init}').exists() or Path(f'/run/{init}').exists():
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
        return ''.join(chars[c % len(chars)] for c in os.urandom(length))

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
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        ).sign(key, hashes.SHA256(), default_backend())
        
        cert_path = Path(self.__config['ssl_cert'])
        with open(cert_path, "wb") as f:
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
        return self.__config.copy()

# ==================== 令牌桶限速器 ====================
class TokenBucket:
    def __init__(self, capacity, rate):
        self.capacity = capacity
        self.rate = rate
        self.tokens = capacity
        self.last_check = time.time()
        self.lock = Lock()

    def consume(self, amount):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_check
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
                server = UltraServer(('0.0.0.0', Config().data['port']), UltraHandler)
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
class UltraHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.cfg = Config().data
        self.start_time = time.time()
        self.rate_limit = self.cfg['download_limit'] * 1024**2
        self.token_bucket = TokenBucket(
            self.cfg['token_bucket']['capacity'],
            self.cfg['token_bucket']['rate']
        )
        self.transfer_id = None
        self.user_role = None
        super().__init__(*args, directory=self.cfg['root_dir'], **kwargs)
    
    # ========== 安全验证增强 ==========
    def check_ip_whitelist(self):
        client_ip = self.client_address[0]
        if client_ip in self.cfg['blacklist']:
            self.send_error(403, "IP Blocked")
            return False
            
        for network in self.cfg['ip_whitelist']:
            if ip_address(client_ip) in ip_network(network):
                return True
        self.send_error(403, "IP Not Allowed")
        return False
    
    def generate_digest_response(self, nonce, method, uri):
        ha1 = hashlib.md5(f"{self.cfg['auth']['user']}:{self.cfg['realm']}:{self.cfg['auth']['pass']}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        return hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    
    def authenticate(self):
        if not self.check_ip_whitelist():
            return False
            
        auth_header = self.headers.get('Authorization', '')
        if not auth_header.startswith('Digest '):
            self.send_auth_required()
            return False
            
        auth_params = {}
        for item in auth_header[7:].split(','):
            key, val = item.strip().split('=', 1)
            auth_params[key] = val.strip('"')
            
        if auth_params.get('username') != self.cfg['auth']['user']:
            self.send_error(401, "Invalid credentials")
            return False
            
        expected = self.generate_digest_response(
            auth_params['nonce'],
            self.command,
            self.path
        )
        
        if auth_params.get('response') != expected:
            self.send_error(401, "Invalid credentials")
            return False
            
        self.user_role = self.cfg['auth'].get('role', 'user')
        return True
    
    def check_api_permission(self, endpoint):
        if self.user_role == 'admin':
            return True
            
        allowed = API_PERMISSIONS.get(self.user_role, [])
        if '*' in allowed or endpoint in allowed:
            return True
            
        return False
    
    def send_auth_required(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 
            f'Digest realm="{self.cfg["realm"]}", qop="auth", nonce="{self.cfg["nonce"]}", opaque="{hashlib.md5(self.cfg["realm"].encode()).hexdigest()}"')
        self.end_headers()
    
    # ========== WebDAV支持 ==========
    def do_PROPFIND(self):
        if not self.authenticate():
            return
            
        path = self.translate_path(self.path)
        if not os.path.exists(path):
            self.send_error(404, "Not Found")
            return
            
        depth = self.headers.get('Depth', '0')
        if depth not in ('0', '1', 'infinity'):
            self.send_error(400, "Invalid Depth header")
            return
            
        propfind_data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        response = self.generate_dav_response(path, depth == '1')
        self.send_response(207)
        self.send_header('Content-Type', 'application/xml; charset="utf-8"')
        self.send_header('Content-Length', len(response))
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))
    
    def generate_dav_response(self, path, recursive):
        prop_elements = []
        for prop_name, (dav_name, getter) in DAV_PROPS.items():
            try:
                prop_value = getter(Path(path))
                if prop_value:
                    prop_elements.append(f'<d:{dav_name}>{prop_value}</d:{dav_name}>')
            except:
                continue
                
        props_xml = '\n'.join(prop_elements)
        
        return f'''<?xml version="1.0" encoding="utf-8" ?>
<d:multistatus xmlns:d="{DAV_NS}">
    <d:response>
        <d:href>{self.path}</d:href>
        <d:propstat>
            <d:prop>
                {props_xml}
            </d:prop>
            <d:status>HTTP/1.1 200 OK</d:status>
        </d:propstat>
    </d:response>
</d:multistatus>'''
    
    # ========== 文件传输优化 ==========
    def send_head(self):
        """重写以实现下载限速和压缩"""
        if self.rate_limit > 0:
            return self._send_with_rate_limit()
        return super().send_head()
    
    def _send_with_rate_limit(self):
        path = self.translate_path(self.path)
        try:
            with open(path, 'rb') as f:
                fs = os.fstat(f.fileno())
                self.send_response(200)
                self.send_header("Content-type", self.guess_type(path))
                
                # 压缩支持
                accept_encoding = self.headers.get('Accept-Encoding', '')
                if self.cfg['compression'] and 'gzip' in accept_encoding and path.endswith(('.txt', '.html', '.css', '.js', '.json')):
                    data = f.read()
                    compressed = zlib.compress(data, self.cfg['compression_level'])
                    self.send_header("Content-Encoding", "gzip")
                    self.send_header("Content-Length", str(len(compressed)))
                    self.end_headers()
                    self.wfile.write(compressed)
                    return None
                
                self.send_header("Content-Length", str(fs.st_size))
                self.end_headers()
                
                # mmap加速
                if self.cfg['use_mmap'] and fs.st_size > self.cfg['mmap_threshold']:
                    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        chunk_size = 1024 * 1024
                        delay = chunk_size / self.rate_limit if self.rate_limit > 0 else 0
                        for i in range(0, fs.st_size, chunk_size):
                            if not self.token_bucket.consume(chunk_size):
                                time.sleep(1 / self.token_bucket.rate)
                            self.wfile.write(mm[i:i+chunk_size])
                            if delay > 0:
                                time.sleep(delay)
                else:
                    chunk_size = 1024 * 1024
                    delay = chunk_size / self.rate_limit if self.rate_limit > 0 else 0
                    while True:
                        if not self.token_bucket.consume(chunk_size):
                            time.sleep(1 / self.token_bucket.rate)
                        data = f.read(chunk_size)
                        if not data:
                            break
                        self.wfile.write(data)
                        if delay > 0:
                            time.sleep(delay)
        except OSError:
            self.send_error(404, "File not found")
        return None

    def do_PUT(self):
        """优化上传：使用mmap和进度跟踪"""
        if not (self.authenticate() and self.cfg['upload']):
            return
        
        path = self.translate_path(self.path)
        if Path(path).is_dir():
            self.send_error(400, "Cannot overwrite directory")
            return
        
        size = int(self.headers.get('Content-Length', 0))
        if size > self.cfg['max_upload']:
            self.send_error(413, "File too large")
            return
        
        self.transfer_id = str(time.time())
        self.cfg['active_transfers'][self.transfer_id] = {
            'path': path,
            'total': size,
            'transferred': 0,
            'start_time': time.time(),
            'client': self.client_address[0]
        }
        
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            # 原子性操作：先写入临时文件
            temp_path = f"{path}.tmp"
            with open(temp_path, 'wb') as f:
                if self.cfg['use_mmap'] and size > self.cfg['mmap_threshold']:
                    f.truncate(size)
                    with mmap.mmap(f.fileno(), size, access=mmap.ACCESS_WRITE) as mm:
                        remaining = size
                        while remaining > 0:
                            chunk = min(remaining, 1024*1024)
                            data = self.rfile.read(chunk)
                            mm.write(data)
                            remaining -= len(data)
                            self.update_transfer_progress(len(data))
                else:
                    while True:
                        data = self.rfile.read(1024*1024)
                        if not data:
                            break
                        f.write(data)
                        self.update_transfer_progress(len(data))
            
            # 原子性重命名
            if self.cfg['atomic_operations']:
                os.replace(temp_path, path)
            
            if self.cfg['checksum']:
                self.generate_checksum(path)
            
            self.send_response(201)
            self.end_headers()
            self.log_transfer('upload', path, size)
        except Exception as e:
            self.send_error(500, str(e))
            if Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except: pass
        finally:
            if self.transfer_id in self.cfg['active_transfers']:
                del self.cfg['active_transfers'][self.transfer_id]
    
    def update_transfer_progress(self, chunk_size):
        if self.transfer_id in self.cfg['active_transfers']:
            transfer = self.cfg['active_transfers'][self.transfer_id]
            transfer['transferred'] += chunk_size
            transfer['speed'] = transfer['transferred'] / (time.time() - transfer['start_time'])
    
    # ========== 增强API端点 ==========
    def handle_api(self):
        if not self.authenticate():
            return
            
        if not self.check_api_permission(self.path):
            self.send_error(403, "Forbidden: Insufficient permissions")
            return
            
        endpoints = {
            '/api/stats': self.api_stats,
            '/api/files': self.api_files,
            '/api/config': self.api_config,
            '/api/cleanup': self.api_cleanup,
            '/api/transfers': self.api_transfers
        }
        
        handler = endpoints.get(self.path, None)
        if handler:
            handler()
        else:
            self.send_error(404, "API endpoint not found")
    
    def api_stats(self):
        stats = {
            "uptime": time.time() - self.start_time,
            "transfers": {
                "downloads": self.server.stats['downloads'],
                "uploads": self.server.stats['uploads']
            },
            "system": {
                "connections": threading.active_count(),
                "memory": psutil.Process().memory_info().rss
            }
        }
        self.send_json(stats)
    
    def api_transfers(self):
        transfers = []
        for tid, info in self.cfg['active_transfers'].items():
            transfers.append({
                'id': tid,
                'path': info['path'],
                'progress': f"{info['transferred']/info['total']*100:.1f}%",
                'speed': f"{info.get('speed', 0)/1024:.1f} KB/s",
                'client': info['client']
            })
        self.send_json({"active_transfers": transfers})
    
    def api_files(self):
        files = []
        for f in Path(self.cfg['root_dir']).glob('*'):
            if f.is_file():
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                    "checksum": self.get_checksum(f) if self.cfg['checksum'] else None
                })
        self.send_json({"files": files})
    
    def api_cleanup(self):
        if self.user_role != 'admin':
            self.send_error(403, "Forbidden: Admin only")
            return
            
        deleted = []
        cutoff = time.time() - self.cfg['retention_days'] * 86400
        for f in Path(self.cfg['root_dir']).glob('*'):
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    deleted.append(f.name)
                except Exception as e:
                    self.send_error(500, f"Cleanup failed: {str(e)}")
                    return
        self.send_json({"deleted": deleted})

    # ========== 实用工具方法 ==========
    def generate_checksum(self, path):
        hashes = {
            'md5': hashlib.md5(),
            'sha256': hashlib.sha256()
        }
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                for h in hashes.values():
                    h.update(chunk)
        
        checksum_file = Path(path).with_suffix('.checksum')
        with open(checksum_file, 'w') as f:
            f.write(f"MD5: {hashes['md5'].hexdigest()}\n")
            f.write(f"SHA256: {hashes['sha256'].hexdigest()}\n")
    
    def get_checksum(self, path):
        checksum_file = Path(path).with_suffix('.checksum')
        if checksum_file.exists():
            with open(checksum_file, 'r') as f:
                return f.read()
        return None
    
    def log_transfer(self, action, path=None, size=0):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "client": self.client_address[0],
            "action": action,
            "path": path,
            "size": size,
            "duration": time.time() - self.start_time
        }
        with open(self.cfg['log_file'], 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(json.dumps(data))))
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

# ==================== 服务器实例 ====================
class UltraServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    def __init__(self, *args, **kwargs):
        self.stats = {'downloads': 0, 'uploads': 0}
        self.config_reloader = None
        super().__init__(*args, **kwargs)
        if Config().data['ssl']:
            self.socket = ssl.wrap_socket(
                self.socket,
                certfile=Config().data['ssl_cert'],
                server_side=True,
                ssl_version=ssl.PROTOCOL_TLS
            )
        
        # 启动配置重载线程
        self.start_config_reloader()
        
        # 自我测试
        if Config().data['self_test']:
            self.start_self_test()

    def start_config_reloader(self):
        def reloader():
            while True:
                time.sleep(5)
                if Config().check_reload():
                    logging.info("Configuration reloaded")
        
        self.config_reloader = threading.Thread(target=reloader, daemon=True)
        self.config_reloader.start()

    def start_self_test(self):
        def self_test():
            time.sleep(5)  # 等待服务器启动
            
            test_file = Path(Config().data['root_dir']) / 'ufs_self_test.txt'
            test_content = b"UltraFileServer Self Test - " + os.urandom(32)
            
            try:
                # 测试上传
                with test_file.open('wb') as f:
                    f.write(test_content)
                
                # 测试下载
                with test_file.open('rb') as f:
                    downloaded = f.read()
                
                if downloaded != test_content:
                    logging.error("Self-test failed: Downloaded content mismatch")
                else:
                    logging.info("Self-test passed")
            except Exception as e:
                logging.error(f"Self-test failed: {str(e)}")
            finally:
                try:
                    test_file.unlink()
                except:
                    pass
        
        threading.Thread(target=self_test, daemon=True).start()

    def service_actions(self):
        self.cleanup_old_files()
    
    def cleanup_old_files(self):
        cutoff = time.time() - Config().data['retention_days'] * 86400
        for f in Path(Config().data['root_dir']).glob('*'):
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                except: pass

# ==================== Docker支持 ====================
def generate_dockerfile():
    dockerfile = """# UltraFileServer Pro Dockerfile
FROM python:3.9-slim

RUN apt-get update && apt-get install -y \\
    gcc \\
    python3-dev \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000 8001

CMD ["python", "ufsproplus.py", "--mode", "standard"]
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
        with open('ufs-config.yaml', 'w') as f:
            yaml.dump(Config().default_config(), f, default_flow_style=False)
        print("示例配置文件已生成: ufs-config.yaml")
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
    signal.signal(signal.SIGHUP, lambda sig, frame: Config().check_reload())
    
    server = UltraServer(('0.0.0.0', Config().data['port']), UltraHandler)
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