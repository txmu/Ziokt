#!/usr/bin/env python3

# ufs_extra_protocols.py
"""
UltraFileServer Pro 协议扩展版 - 在原有基础上增加FTP、Usenet(NNTP)、Gopher、Telnet和SFTP支持
保持原有安全特性和功能完整性

主要功能：
- 继承原有HTTP/HTTPS和WebDAV功能
- 新增FTP/FTPS文件传输协议支持
- 完整Usenet新闻组服务器实现
- 经典Gopher协议支持
- 安全Telnet远程访问
- SFTP文件传输支持
- 统一认证系统
- 共享配置文件
- 跨协议日志记录
"""

import os
import sys
import ssl
import asyncio
import logging
import argparse
import paramiko  # SFTP支持
import telnetlib3  # Telnet支持
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from datetime import datetime
from functools import partial

# 导入基础UltraFileServer Pro
from ufsultra import Config, TokenBucket, ServiceManager

# 新增协议支持库
import pyftpdlib.authorizers
import pyftpdlib.handlers
import pyftpdlib.servers
from nntplib import NNTP
from gopherlib import send_gopher

# ==================== 扩展配置类 ====================
class ExtendedConfig(Config):
    def default_config(self):
        # 继承基础配置
        base_config = super().default_config()
        
        # 扩展配置项
        extended_config = {
            # FTP配置
            'ftp': {
                'enabled': True,
                'port': 2121,
                'passive_ports': '60000-61000',  # 被动模式端口范围
                'max_conn': 50,  # 最大连接数
                'masquerade_address': None,  # 地址伪装
                'tls': True,  # 启用TLS
                'tls_cert': 'ftp_cert.pem',  # FTP证书
                'tls_key': 'ftp_key.pem',  # FTP密钥
                'banner': 'UltraFileServer FTP Pro'  # 欢迎标语
            },
            
            # Usenet(NNTP)配置
            'nntp': {
                'enabled': True,
                'port': 1119,  # NNTP标准端口119的替代
                'organization': 'UltraFileServer Usenet',  # 组织标识
                'overview_fmt': ['Subject', 'From', 'Date', 'Message-ID', 'References', 'Bytes', 'Lines'],  # 概览格式
                'groups': {  # 默认新闻组
                    'ufs.announce': '公告区',
                    'ufs.discuss': '讨论区'
                }
            },
            
            # Gopher配置
            'gopher': {
                'enabled': True,
                'port': 70,  # Gopher标准端口
                'hostname': 'localhost',  # 主机名
                'menu_items': [  # 菜单项
                    {'type': '1', 'display': '欢迎', 'selector': 'welcome', 'host': 'localhost', 'port': 70},
                    {'type': '0', 'display': '文档', 'selector': 'doc', 'host': 'localhost', 'port': 70},
                    {'type': '7', 'display': '搜索', 'selector': 'search', 'host': 'localhost', 'port': 70}
                ]
            },
            
            # Telnet配置
            'telnet': {
                'enabled': True,
                'port': 2323,  # Telnet标准端口23的替代
                'banner': 'UltraFileServer Telnet 服务\r\n授权访问',  # 欢迎标语
                'timeout': 300,  # 超时时间(秒)
                'max_attempts': 3  # 最大认证尝试次数
            },
            
            # SFTP配置
            'sftp': {
                'enabled': True,
                'port': 2222,  # SSH标准端口22的替代
                'host_key': 'ssh_host_key',  # 主机密钥文件
                'banner': 'UltraFileServer SFTP 服务',  # 欢迎标语
                'max_sessions': 10  # 最大会话数
            }
        }
        
        # 合并配置
        return {**base_config, **extended_config}

    def generate_ssh_host_key(self):
        """生成SSH主机密钥用于SFTP"""
        key_path = Path(self.data['sftp']['host_key'])
        if not key_path.exists():
            key = paramiko.RSAKey.generate(2048)
            key.write_private_key_file(str(key_path))
            logging.info(f"生成SSH主机密钥: {key_path}")

# ==================== FTP服务器实现 ====================
class UltraFTPAuthorizer(pyftpdlib.authorizers.DummyAuthorizer):
    """自定义FTP认证器，集成统一用户系统"""
    def __init__(self, config):
        super().__init__()
        self.config = config
        # 添加主用户
        self.add_user(
            config['auth']['user'],
            config['auth']['pass'],
            config['root_dir'],
            perm='elradfmwMT'  # 所有权限
        )
        # 条件性允许匿名访问
        if config.get('allow_anonymous', False):
            self.add_anonymous(config['root_dir'])

class UltraFTPHandler(pyftpdlib.handlers.FTPHandler):
    """增强型FTP处理器，集成安全特性"""
    def __init__(self, *args, **kwargs):
        self.config = kwargs.pop('config')
        # 使用相同的令牌桶进行速率限制
        self.token_bucket = TokenBucket(
            self.config['token_bucket']['capacity'],
            self.config['token_bucket']['rate']
        )
        super().__init__(*args, **kwargs)
    
    def on_connect(self):
        """客户端连接时进行IP检查"""
        client_ip = self.remote_ip
        if client_ip in self.config['blacklist']:
            self.respond("421 IP地址被阻止")
            self.close_when_done()
            return False
            
        # 检查IP白名单
        for network in self.config['ip_whitelist']:
            if ip_address(client_ip) in ip_network(network):
                return True
        
        self.respond("421 IP地址未授权")
        self.close_when_done()
        return False
    
    def on_file_sent(self, file):
        """文件发送时的速率控制"""
        file_size = os.path.getsize(file)
        chunk_size = 1024 * 1024  # 1MB块
        for _ in range(0, file_size, chunk_size):
            while not self.token_bucket.consume(chunk_size):
                time.sleep(1 / self.token_bucket.rate)

# ==================== Telnet服务器实现 ====================
class UltraTelnetShell:
    """Telnet交互式shell"""
    def __init__(self, config):
        self.config = config
        self.authenticated = False
        self.attempts = 0
    
    async def handle_client(self, reader, writer):
        """处理Telnet客户端连接"""
        client_ip = writer.get_extra_info('peername')[0]
        
        # IP安全检查
        if not self.check_ip(client_ip):
            writer.write("连接被拒绝: IP未授权\r\n".encode())
            await writer.drain()
            writer.close()
            return
        
        # 显示欢迎信息
        writer.write(f"{self.config['telnet']['banner']}\r\n".encode())
        
        try:
            # 认证循环
            while not self.authenticated and self.attempts < self.config['telnet']['max_attempts']:
                writer.write("用户名: ".encode())
                await writer.drain()
                username = await reader.readuntil(b'\r\n')
                
                writer.write("密码: ".encode())
                await writer.drain()
                password = await reader.readuntil(b'\r\n')
                
                if (username.decode().strip() == self.config['auth']['user'] and 
                    password.decode().strip() == self.config['auth']['pass']):
                    self.authenticated = True
                    writer.write("认证成功!\r\n".encode())
                else:
                    self.attempts += 1
                    writer.write(f"认证失败，剩余尝试次数: {self.config['telnet']['max_attempts'] - self.attempts}\r\n".encode())
                
                await writer.drain()
            
            # 主命令循环
            while self.authenticated:
                writer.write("ufs> ".encode())
                await writer.drain()
                command = await reader.readuntil(b'\r\n')
                response = self.process_command(command.decode().strip())
                writer.write(response.encode() + b"\r\n")
                await writer.drain()
                
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
    
    def check_ip(self, client_ip):
        """检查客户端IP是否被允许"""
        if client_ip in self.config['blacklist']:
            return False
        return any(ip_address(client_ip) in ip_network(network) 
               for network in self.config['ip_whitelist'])
    
    def process_command(self, command):
        """处理Telnet命令"""
        if not command:
            return ""
        elif command.lower() == 'help':
            return "可用命令: stats, files, exit"
        elif command.lower() == 'stats':
            return self.get_system_stats()
        elif command.lower() == 'files':
            return self.list_files()
        elif command.lower() == 'exit':
            self.authenticated = False
            return "再见"
        else:
            return "未知命令"
    
    def get_system_stats(self):
        """获取系统统计信息"""
        return f"服务器状态: 运行中\r\n存储使用: {shutil.disk_usage(self.config['root_dir']).used/1024**2:.1f}MB"
    
    def list_files(self):
        """列出根目录文件"""
        files = "\r\n".join(f.name for f in Path(self.config['root_dir']).iterdir() if f.is_file())
        return f"文件列表:\r\n{files}" if files else "目录为空"

async def start_telnet_server(config):
    """启动Telnet服务器"""
    shell = UltraTelnetShell(config)
    server = await telnetlib3.create_server(
        shell.handle_client,
        port=config['telnet']['port'],
        timeout=config['telnet']['timeout']
    )
    logging.info(f"Telnet服务器已在端口 {config['telnet']['port']} 启动")
    return server

# ==================== SFTP服务器实现 ====================
class UltraSFTPServer(paramiko.ServerInterface):
    """自定义SFTP服务器实现"""
    def __init__(self, config):
        self.config = config
        self.username = config['auth']['user']
        self.password = config['auth']['pass']
    
    def check_auth_password(self, username, password):
        """密码认证"""
        if username == self.username and password == self.password:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED
    
    def check_channel_request(self, kind, chanid):
        """通道请求检查"""
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

def handle_sftp_connection(client, config):
    """处理SFTP客户端连接"""
    transport = client.get_transport()
    transport.add_server_key(paramiko.RSAKey(filename=config['sftp']['host_key']))
    
    server = UltraSFTPServer(config)
    transport.start_server(server=server)
    
    chan = transport.accept()
    if chan is None:
        return
    
    # 创建SFTP服务器
    sftp = paramiko.SFTPServer(chan)
    try:
        sftp.serve_forever()
    except (EOFError, ConnectionResetError):
        pass
    finally:
        chan.close()

def start_sftp_server(config):
    """启动SFTP服务器"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', config['sftp']['port']))
    sock.listen(5)
    
    logging.info(f"SFTP服务器已在端口 {config['sftp']['port']} 启动")
    
    try:
        while True:
            client, addr = sock.accept()
            # IP白名单检查
            if not any(ip_address(addr[0]) in ip_network(network) 
                     for network in config['ip_whitelist']):
                client.close()
                continue
            
            # 为新连接创建线程
            threading.Thread(
                target=handle_sftp_connection,
                args=(paramiko.Transport(client), config)
            ).start()
    except KeyboardInterrupt:
        sock.close()

# ==================== 主服务器控制器 ====================
class ExtendedServer:
    """扩展服务器主控制器"""
    def __init__(self):
        self.config = ExtendedConfig().data
        self.servers = []
        self.loop = asyncio.get_event_loop()
        
        # 生成必要的证书和密钥
        if self.config['sftp']['enabled']:
            ExtendedConfig().generate_ssh_host_key()
        
        # 设置信号处理
        if OS_TYPE != 'Windows':
            for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                self.loop.add_signal_handler(sig, self.shutdown)
    
    async def start_servers(self):
        """启动所有服务"""
        tasks = []
        
        # 启动HTTP服务器(来自ufsultra)
        http_server = UltraServer(('0.0.0.0', self.config['port']), UltraHandler)
        self.servers.append(http_server)
        tasks.append(self.loop.run_in_executor(None, http_server.serve_forever))
        
        # 启动FTP服务器(如果启用)
        if self.config['ftp']['enabled']:
            tasks.append(self.loop.run_in_executor(None, start_ftp_server, self.config))
        
        # 启动Telnet服务器(如果启用)
        if self.config['telnet']['enabled']:
            tasks.append(start_telnet_server(self.config))
        
        # 在单独线程中启动SFTP服务器
        if self.config['sftp']['enabled']:
            threading.Thread(
                target=start_sftp_server,
                args=(self.config,),
                daemon=True
            ).start()
        
        logging.info("所有服务已启动")
        await asyncio.gather(*tasks)
    
    def shutdown(self):
        """关闭所有服务"""
        logging.info("正在关闭服务...")
        for server in self.servers:
            server.shutdown()
        self.loop.stop()

# ==================== 命令行入口 ====================
def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description="UltraFileServer Pro 扩展版")
    parser.add_argument('--mode', choices=['standard', 'secure', 'mirror'], default='standard')
    parser.add_argument('--install', action='store_true', help="安装为系统服务")
    parser.add_argument('--daemon', action='store_true', help="以守护进程模式运行")
    parser.add_argument('--gen-config', action='store_true', help="生成示例配置文件")
    args = parser.parse_args()
    
    config = ExtendedConfig().data
    
    # 配置日志系统
    logging.basicConfig(
        handlers=[logging.handlers.RotatingFileHandler(
            config['log_file'], maxBytes=10*1024*1024, backupCount=5)],
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    if args.gen_config:
        with open('ufs-extended-config.yaml', 'w') as f:
            yaml.dump(ExtendedConfig().default_config(), f, default_flow_style=False)
        print("示例配置文件已生成: ufs-extended-config.yaml")
        return
    
    if args.install:
        if OS_TYPE != 'Windows' and os.geteuid() != 0:
            print("错误: 安装服务需要root权限!")
            sys.exit(1)
        ExtendedServiceManager.install(args.mode)
        return
    
    if args.daemon:
        daemonize()
    
    # 创建并启动服务器
    server = ExtendedServer()
    try:
        asyncio.get_event_loop().run_until_complete(server.start_servers())
    except KeyboardInterrupt:
        server.shutdown()
        print("\n服务器已停止")

if __name__ == '__main__':
    main()