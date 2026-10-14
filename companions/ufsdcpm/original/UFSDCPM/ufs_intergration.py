# ufs_integration.py
"""
UFS与内存池(DCPM)和活板(HuoBan)的集成扩展模块

主要功能：
1. 提供内存池文件缓存加速功能
2. 实现活板消息系统与文件服务器的通知集成
3. 扩展API接口
4. 增强的安全权限控制系统
"""

from dcpm_poolmemory import SharedMemoryPool, parse_permissions
from dcpm_huoban import ExtendedHuoBanMessageBoard, SecureUser
from ufsultra import UltraHandler, Config
import threading
import json
from pathlib import Path

# 初始化集成组件
class UFSIntegration:
    def __init__(self):
        self.cfg = Config().data
        self.memory_pool = SharedMemoryPool(
            capacity=self.cfg.get('memory_pool_size', 1024*1024*1024),  # 默认1GB
            is_multithread=True
        )
        self.message_board = ExtendedHuoBanMessageBoard()
        self._setup_admin_user()
        self.file_cache = {}
        self.cache_lock = threading.Lock()
        
    def _setup_admin_user(self):
        """使用UFS配置创建默认管理员用户"""
        admin_user = SecureUser(
            self.cfg['auth']['user'],
            self.cfg['auth']['pass']
        )
        admin_user.is_admin = True
        self.message_board.users[admin_user.name] = admin_user

# ==================== 内存池加速功能 ====================
class MemoryCachedHandler(UltraHandler):
    """支持内存池缓存的文件处理器"""
    
    def __init__(self, *args, **kwargs):
        self.integration = UFSIntegration()
        super().__init__(*args, **kwargs)
    
    def send_head(self):
        """重写send_head方法，加入内存缓存逻辑"""
        path = self.translate_path(self.path)
        
        # 检查内存缓存
        with self.integration.cache_lock:
            if path in self.integration.file_cache:
                seg = self.integration.file_cache[path]
                if self._validate_cache(seg, path):
                    return self._send_from_memory(seg)
        
        # 无缓存或缓存失效，走正常流程
        return super().send_head()
    
    def _validate_cache(self, segment, file_path):
        """验证缓存是否有效"""
        file_stat = Path(file_path).stat()
        return (segment.metadata['mtime'] == file_stat.st_mtime and 
                segment.metadata['size'] == file_stat.st_size)
    
    def _send_from_memory(self, segment):
        """从内存池发送文件内容"""
        self.send_response(200)
        self.send_header("Content-type", self.guess_type(segment.metadata['path']))
        self.send_header("Content-Length", str(segment.metadata['size']))
        self.end_headers()
        
        # 使用内存池数据
        self.wfile.write(segment.memory.read(0, segment.metadata['size']))
        return None

# ==================== 消息通知集成 ====================
class NotificationMixin:
    """文件操作消息通知功能"""
    
    def post_notification(self, user, action, path, details=None):
        """发送文件操作通知到消息板"""
        msg = f"文件{action}: {path}"
        if details:
            msg += f" | 详情: {details}"
        self.integration.message_board.post_message(
            user, msg
        )
    
    def handle_api_notify(self):
        """API消息通知端点"""
        if not self.authenticate():
            return
            
        user = self.integration.message_board.users.get(self.cfg['auth']['user'])
        if not user:
            self.send_error(403, "用户未注册")
            return
            
        content_length = int(self.headers.get('Content-Length', 0))
        data = json.loads(self.rfile.read(content_length))
        
        self.post_notification(
            user,
            data.get('action', 'unknown'),
            data.get('path', ''),
            data.get('details')
        )
        
        self.send_json({"status": "通知已发送"})

# ==================== 扩展API ====================
class ExtendedAPIHandler(UltraHandler, NotificationMixin):
    """扩展的API处理器"""
    
    API_ENDPOINTS = {
        '/api/memory/status': 'api_memory_status',
        '/api/memory/cache': 'api_memory_cache',
        '/api/notify': 'handle_api_notify',
        '/api/messages': 'api_get_messages'
    }
    
    def handle_api(self):
        """扩展API路由"""
        endpoint = self.path.split('?')[0]
        if endpoint in self.API_ENDPOINTS:
            handler = getattr(self, self.API_ENDPOINTS[endpoint])
            handler()
        else:
            super().handle_api()
    
    def api_memory_status(self):
        """获取内存池状态"""
        usage = self.integration.memory_pool.get_usage()
        self.send_json({
            "total": self.integration.memory_pool.capacity,
            "used": int(self.integration.memory_pool.capacity * usage),
            "usage_percent": round(usage * 100, 2)
        })
    
    def api_memory_cache(self):
        """内存缓存管理API"""
        if not self.authenticate():
            return
            
        if self.command == 'GET':
            with self.integration.cache_lock:
                self.send_json({
                    "cached_files": list(self.integration.file_cache.keys()),
                    "total_size": sum(
                        seg.metadata['size'] for seg in self.integration.file_cache.values()
                    )
                })
                
        elif self.command == 'POST':
            # 添加文件到缓存
            content_length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(content_length))
            file_path = data.get('path')
            
            if not file_path:
                self.send_error(400, "需要提供path参数")
                return
                
            self._cache_file(file_path)
            self.send_json({"status": f"{file_path} 已缓存"})
            
        elif self.command == 'DELETE':
            # 清除缓存
            with self.integration.cache_lock:
                self.integration.file_cache.clear()
                self.send_json({"status": "缓存已清空"})
    
    def _cache_file(self, file_path):
        """将文件缓存到内存池"""
        path = Path(file_path)
        if not path.exists():
            self.send_error(404, "文件不存在")
            return
            
        stat = path.stat()
        seg = self.integration.memory_pool.allocate(stat.st_size)
        
        with open(file_path, 'rb') as f:
            seg.memory.write(0, f.read())
        
        seg.metadata = {
            'path': file_path,
            'size': stat.st_size,
            'mtime': stat.st_mtime
        }
        
        with self.integration.cache_lock:
            self.integration.file_cache[file_path] = seg
    
    def api_get_messages(self):
        """获取消息板消息"""
        if not self.authenticate():
            return
            
        user = self.integration.message_board.users.get(self.cfg['auth']['user'])
        if not user:
            self.send_error(403, "用户未注册")
            return
            
        messages = self.integration.message_board.view_messages()
        self.send_json({
            "messages": [
                {"user": user, "text": text, "time": str(time)} 
                for user, text, time in messages
            ]
        })

# ==================== 安全增强 ====================
class SecureMemoryAccess:
    """安全内存访问控制"""
    
    PERMISSION_MAP = {
        'read': 'r',
        'write': 'w',
        'execute': 'x',
        'share': 's',
        'admin': 'rwxsuep'
    }
    
    def check_memory_access(self, segment, user, action):
        """检查内存段访问权限"""
        if not segment.owner or segment.owner == user.name:
            return True
            
        if segment.domain and user in segment.domain.users:
            perm_str = segment.permissions.get(user.name, '')
            required_perm = self.PERMISSION_MAP.get(action, '')
            return required_perm in perm_str
            
        return False

# ==================== 服务器集成 ====================
class IntegratedUltraServer(UltraServer):
    """集成所有功能的服务器"""
    
    def __init__(self, *args, **kwargs):
        self.integration = UFSIntegration()
        super().__init__(*args, **kwargs)
        
    def finish_request(self, request, client_address):
        """使用集成的请求处理器"""
        handler = ExtendedAPIHandler(
            request, client_address, self,
            integration=self.integration
        )
        handler.handle()

# ==================== 使用示例 ====================
if __name__ == '__main__':
    # 初始化配置
    cfg = Config().data
    
    # 启动集成服务器
    server = IntegratedUltraServer(('0.0.0.0', cfg['port']), ExtendedAPIHandler)
    print(f"集成服务器已启动 | 端口: {cfg['port']}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        print("\n服务器已关闭")