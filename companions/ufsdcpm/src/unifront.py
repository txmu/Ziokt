#!/usr/bin/env python3
"""
Decentralized Unified File and Package Management System (DUFPMS)
统一前端脚本 (Unifront) - 综合所有功能
- 异步和多线程化
- 引用现有模块，避免重复造轮子
- 提供一个简单的 Web 界面
"""

import asyncio
import argparse
import threading
import aiohttp
from aiohttp import web
import aiohttp_jinja2
import jinja2
from dcpm_cli import main as dcpm_main
from dcpm_ufs_integration import IntegratedSystem
from ufs_extra_protocols import ExtendedServer
from ufs_integration import UFSIntegration
from ufsultra import UltraServer, UltraHandler

# 全局变量
ufs_integration = None
ufs_extra_server = None
integrated_system = None
web_app = None

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="统一前端脚本 (Unifront)")
    subparsers = parser.add_subparsers(dest='command', required=True)

    # DCPM 命令
    dcpm_parser = subparsers.add_parser('dcpm', help='DCPM 包管理器')
    dcpm_parser.add_argument("-p", "--publish", metavar="PACKAGE", help="发布软件包到网络")
    dcpm_parser.add_argument("-d", "--download", metavar="PACKAGE_ID", help="从网络下载软件包")
    dcpm_parser.add_argument("-i", "--install", metavar="PACKAGE", help="安装本地软件包")
    dcpm_parser.add_argument("-r", "--remove", metavar="PACKAGE", help="卸载本地软件包")
    dcpm_parser.add_argument("--tls-cert", help="TLS证书文件路径")
    dcpm_parser.add_argument("--tls-key", help="TLS密钥文件路径")
    dcpm_parser.add_argument(
        "--dep-mode",
        choices=["none", "suggest", "auto"],
        default="none",
        help="依赖解决模式: none - 不解决依赖; suggest - 输出依赖解决建议; auto - 自动解决依赖",
    )
    dcpm_parser.add_argument("--fork", metavar="PACKAGE_ID", help="为指定软件包创建新的分支或版本")
    dcpm_parser.add_argument("--branch", metavar="PACKAGE_ID", help="为指定软件包创建新的分支")
    dcpm_parser.add_argument("--revert", metavar="PACKAGE_ID", help="恢复指定软件包到上一个版本")

    # UFS 命令
    ufs_parser = subparsers.add_parser('ufs', help='UFS 文件服务器')
    ufs_parser.add_argument('action', choices=['start', 'stop', 'status'], help='UFS 服务操作')
    ufs_parser.add_argument('--config', help='UFS 配置文件路径')

    # UFS 集成命令
    ufs_integrate_parser = subparsers.add_parser('ufs-integrate', help='UFS 集成功能')
    ufs_integrate_parser.add_argument('action', choices=['start', 'stop', 'status'], help='UFS 集成服务操作')

    # UFS 扩展命令
    ufs_extend_parser = subparsers.add_parser('ufs-extend', help='UFS 扩展功能')
    ufs_extend_parser.add_argument('action', choices=['start', 'stop', 'status'], help='UFS 扩展服务操作')

    # Web 界面命令
    web_parser = subparsers.add_parser('web', help='Web 界面')
    web_parser.add_argument('action', choices=['start', 'stop', 'status'], help='Web 服务操作')

    return parser.parse_args()


async def start_dcpm(args):
    """启动 DCPM 服务"""
    await dcpm_main(args)


def start_ufs_server(config_path):
    """启动 UFS 文件服务器"""
    global ufs_integration
    ufs_integration = UFSIntegration()
    server = UltraServer(('0.0.0.0', ufs_integration.cfg['port']), UltraHandler)
    print(f"UFS 文件服务器已启动 | 端口: {ufs_integration.cfg['port']}")
    server.serve_forever()


def start_ufs_extra_server():
    """启动 UFS 扩展服务器"""
    global ufs_extra_server
    ufs_extra_server = ExtendedServer()
    asyncio.run(ufs_extra_server.start_servers())


def start_integrated_system(config_path):
    """启动整合系统"""
    global integrated_system
    integrated_system = IntegratedSystem(config_path)
    asyncio.run(integrated_system.start())


async def start_web_server():
    """启动 Web 服务器"""
    global web_app
    web_app = web.Application()
    aiohttp_jinja2.setup(web_app, loader=jinja2.FileSystemLoader('templates'))

    web_app.router.add_get('/', handle_index)
    web_app.router.add_post('/dcpm', handle_dcpm)
    web_app.router.add_post('/ufs', handle_ufs)
    web_app.router.add_post('/ufs-integrate', handle_ufs_integrate)
    web_app.router.add_post('/ufs-extend', handle_ufs_extend)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    print("Web 服务器已启动 | 端口: 8080")
    await site.start()


async def handle_index(request):
    """处理主页请求"""
    context = {}
    return aiohttp_jinja2.render_template('index.html', request, context)


async def handle_dcpm(request):
    """处理 DCPM 请求"""
    data = await request.post()
    args = argparse.Namespace(**data)
    await start_dcpm(args)
    return web.Response(text="DCPM 操作已完成")


async def handle_ufs(request):
    """处理 UFS 请求"""
    data = await request.post()
    action = data.get('action')
    config = data.get('config')
    if action == 'start':
        start_ufs_server(config)
    elif action == 'stop':
        stop_ufs_server()
    elif action == 'status':
        return web.Response(text="UFS 文件服务器状态: 运行中" if ufs_integration else "UFS 文件服务器状态: 停止")
    return web.Response(text="UFS 操作已完成")


async def handle_ufs_integrate(request):
    """处理 UFS 集成请求"""
    data = await request.post()
    action = data.get('action')
    config = data.get('config')
    if action == 'start':
        start_integrated_system(config)
    elif action == 'stop':
        stop_integrated_system()
    elif action == 'status':
        return web.Response(text="UFS 集成服务状态: 运行中" if integrated_system else "UFS 集成服务状态: 停止")
    return web.Response(text="UFS 集成操作已完成")


async def handle_ufs_extend(request):
    """处理 UFS 扩展请求"""
    data = await request.post()
    action = data.get('action')
    if action == 'start':
        start_ufs_extra_server()
    elif action == 'stop':
        stop_ufs_extra_server()
    elif action == 'status':
        return web.Response(text="UFS 扩展服务状态: 运行中" if ufs_extra_server else "UFS 扩展服务状态: 停止")
    return web.Response(text="UFS 扩展操作已完成")


def stop_ufs_server():
    """停止 UFS 文件服务器"""
    global ufs_integration
    if ufs_integration:
        ufs_integration.server.shutdown()
        print("UFS 文件服务器已停止")


def stop_ufs_extra_server():
    """停止 UFS 扩展服务器"""
    global ufs_extra_server
    if ufs_extra_server:
        ufs_extra_server.shutdown()
        print("UFS 扩展服务器已停止")


def stop_integrated_system():
    """停止整合系统"""
    global integrated_system
    if integrated_system:
        asyncio.run(integrated_system.stop())
        print("整合系统已停止")


def stop_web_server():
    """停止 Web 服务器"""
    global web_app
    if web_app:
        asyncio.run(web_app.shutdown())
        print("Web 服务器已停止")


async def main():
    """主函数"""
    args = parse_args()

    if args.command == 'dcpm':
        # 启动 DCPM 服务
        await start_dcpm(args)
    elif args.command == 'ufs':
        # 管理 UFS 文件服务器
        if args.action == 'start':
            start_ufs_server(args.config)
        elif args.action == 'stop':
            stop_ufs_server()
        elif args.action == 'status':
            print("UFS 文件服务器状态: 运行中" if ufs_integration else "UFS 文件服务器状态: 停止")
    elif args.command == 'ufs-integrate':
        # 管理 UFS 集成服务
        if args.action == 'start':
            start_integrated_system(args.config)
        elif args.action == 'stop':
            stop_integrated_system()
        elif args.action == 'status':
            print("UFS 集成服务状态: 运行中" if integrated_system else "UFS 集成服务状态: 停止")
    elif args.command == 'ufs-extend':
        # 管理 UFS 扩展服务
        if args.action == 'start':
            start_ufs_extra_server()
        elif args.action == 'stop':
            stop_ufs_extra_server()
        elif args.action == 'status':
            print("UFS 扩展服务状态: 运行中" if ufs_extra_server else "UFS 扩展服务状态: 停止")
    elif args.command == 'web':
        # 管理 Web 服务
        if args.action == 'start':
            await start_web_server()
        elif args.action == 'stop':
            stop_web_server()
        elif args.action == 'status':
            print("Web 服务器状态: 运行中" if web_app else "Web 服务器状态: 停止")


