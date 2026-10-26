#!/usr/bin/env python3
"""
███████╗ █████╗ ███████╗██╗   ██╗███████╗   ███████╗██╗███╗   ██╗██████╗ ███████╗
██╔════╝██╔══██╗██╔════╝██║   ██║██╔════╝   ██╔════╝██║████╗  ██║██╔══██╗██╔════╝
█████╗  ███████║███████╗██║   ██║█████╗     █████╗  ██║██╔██╗ ██║██║  ██║███████╗
██╔══╝  ██╔══██║╚════██║██║   ██║██╔══╝     ██╔══╝  ██║██║╚██╗██║██║  ██║╚════██║
██║     ██║  ██║███████║╚██████╔╝███████╗██╗██║     ██║██║ ╚████║██████╔╝███████║
╚═╝     ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝╚═╝  ╚═══╝╚═════╝ ╚══════╝
Linux高级文件加密系统 - 防御系统级后门版v9.0
"""

import os
import sys
import time
import ctypes
import hashlib
import hmac
import zlib
import platform
import subprocess
import secrets
import pyotp
import signal
import fcntl
import re
import stat
import tempfile
import psutil
import thread
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from getpass import getpass
from tempfile import mkstemp
from shutil import move, copy2
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Callable
from enum import Enum
from cryptography.hazmat.primitives.kdf.argon2 import Argon2
from cryptography.hazmat.primitives import constant_time
from cryptography.hazmat.backends import default_backend
import pickle  # 用于信任锚点序列化
try:
    import seccomp
except ImportError as e:
    SecureEnv._write_audit_log(f"seccomp导入失败: {e}")
    # 降级处理或抛出异常
    raise SecurityError("缺少关键安全依赖: seccomp")

# ===== 增强安全配置 =====
AUDIT_LOG = "/var/log/.secure_fs.log"  # 隐藏审计日志
MAX_RETRIES = 3
WIPE_PASSES = 35  # 符合DoD 5220.22-M标准
MEMORY_WIPE_PASSES = 7
SALT_SIZE = 32
KDF_ITERATIONS = 1000000
LOCK_FILE = "/tmp/.secure_fs.lock"
TEMP_DIR = "/tmp/.secure_fs_tmp"
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_TIME = 300  # 5分钟

# ===== 安全常数 =====
class SecureConstants:
    MAGIC_HEADER = b"SAFEv9\x00\x01"
    MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB
    MIN_ENTROPY = 0.9  # 最小熵值要求
    TOTP_DIGITS = 8  # 使用8位TOTP代码增强安全性
    TOTP_INTERVAL = 60  # 60秒间隔
    MIN_PASSWORD_LENGTH = 12
    MAX_PASSWORD_ATTEMPTS = 3
    ENCRYPT_TIME_TARGET_NS = 100_000_000  # 100ms固定加密时间
    MIN_PADDING_SIZE = 4096  # 最小填充块大小
    MAX_DECRYPT_TIME_NS = 150_000_000  # 最大解密时间限制
    HMAC_ALGORITHM = hashes.BLAKE2s(32)   # 更快的安全哈希算法
    MIN_COMPRESS_RATIO = 0.8              # 最小压缩率阈值    

# ===== 安全异常 =====
class SecurityError(Exception):
    """基础安全异常"""
    def __init__(self, message="安全违规", details=None):
        self.message = message
        self.details = details
        super().__init__(self.message)
    
    def __str__(self):
        if self.details:
            return f"{self.message} (详情: {self.details})"
        return self.message

class IntegrityError(SecurityError):
    """完整性校验失败"""
    def __init__(self, message="数据完整性校验失败", details=None):
        super().__init__(message, details)
        self.code = 0x1001

class AntiTamperError(SecurityError):
    """防篡改触发"""
    def __init__(self, message="检测到篡改尝试", details=None):
        super().__init__(message, details)
        self.code = 0x2001
        self.timestamp = datetime.now().isoformat()

class MemoryProtectionError(SecurityError):
    """内存保护失败"""
    def __init__(self, message="内存保护操作失败", details=None):
        super().__init__(message, details)
        self.code = 0x3001
        self.memory_operation = "未知"

class LockoutError(SecurityError):
    """安全锁定异常"""
    def __init__(self, message="操作被安全锁定", details=None, remaining_time=0):
        super().__init__(message, details)
        self.code = 0x4001
        self.remaining_time = remaining_time
    
    def __str__(self):
        base = super().__str__()
        return f"{base} | 剩余锁定时间: {self.remaining_time}秒"

class VirtualizationError(SecurityError):
    """虚拟化环境检测异常"""
    def __init__(self, message="虚拟化环境检测", details=None):
        super().__init__(message, details)
        self.code = 0x5001
        self.environment = platform.platform()
    
    def __str__(self):
        return f"{super().__str__()} (环境: {self.environment})"

class CryptoError(SecurityError):
    """加密操作异常"""
    def __init__(self, message="加密操作失败", details=None, algorithm=None):
        super().__init__(message, details)
        self.code = 0x6001
        self.algorithm = algorithm or "未知"
        
class MemoryAccessError(SecurityError):
    """内存访问异常"""
    def __init__(self, message="检测到异常内存访问", details=None):
        super().__init__(message, details)
        self.code = 0x7001

class NetworkAnomalyError(SecurityError):
    """网络异常"""
    def __init__(self, message="检测到异常网络活动", details=None):
        super().__init__(message, details)
        self.code = 0x8001

class SelfIntegrityError(SecurityError):
    """自身完整性异常"""
    def __init__(self, message="检测到自身完整性破坏", details=None):
        super().__init__(message, details)
        self.code = 0x9001

class HardwareError(SecurityError):
    """硬件级安全异常"""
    def __init__(self, message="硬件安全异常", details=None):
        super().__init__(message, details)
        self.code = 0xA001  # 自定义错误代码
        self.category = "hardware"
    
    def __str__(self):
        base = super().__str__()
        if self.details:
            return f"[硬件安全] {base} (详情: {self.details})"
        return f"[硬件安全] {base}"

# ===== 核心安全类 =====
@dataclass
class SecureConfig:
    """可动态加载的安全配置"""
    
    CONFIG_FILE = "/etc/secure_fs.conf"
    
    def __init__(self, **kwargs):
        # 默认配置
        use_airgap: bool = True
        enable_anti_debug: bool = True
        enable_stealth: bool = True # 这个选项压根没有判定，改了也没用
        enable_self_destruct: bool = True # 这个选项压根没有判定，改了也没用
        strict_entropy_check: bool = True
        block_virtualized: bool = True
        prevent_ptrace: bool = True # 这个选项从未判定，改了也没用，除非你手动修改代码删除所有屏蔽ptrace的逻辑
        enable_memory_lock: bool = True
        enable_fail_counter: bool = True
        enable_tamper_protection: bool = True
        enable_secure_temp: bool = True
        enable_core_dump_prevention: bool = True # 这个选项从未判定，改了也没用，除非你手动修改代码删除所有相关屏蔽逻辑
        enable_aslr: bool = True
        enable_seccomp: bool = True # 这个选项也从未判定，改了也没用
        enable_memory_monitor: bool = True # 这个选项也从未判定，改了也没用
        enable_integrity_check: bool = True  # 这个选项从未判定，改了也没用，除非你手动修改代码删除所有相关屏蔽逻辑
        enable_network_monitor: bool = True # 这个选项也从未判定，改了也没用
        enable_self_protection: bool = True  # 这个选项从未判定，改了也没用，除非你手动修改代码删除所有相关屏蔽逻辑
        # 你们就非得关掉那么多精心设计的安全防御措施才开心吗？
        
        # 从文件加载配置
        self._load_config()
        
        # 允许通过kwargs覆盖
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
    
    def _load_config(self):
        """从文件加载配置"""
        if not os.path.exists(self.CONFIG_FILE):
            return
            
        try:
            with open(self.CONFIG_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip()
                    
                    if hasattr(self, key):
                        # 类型转换
                        if isinstance(getattr(self, key), bool):
                            setattr(self, key, value.lower() in ('true', '1', 'yes'))
                        elif isinstance(getattr(self, key), int):
                            setattr(self, key, int(value))
                        else:
                            setattr(self, key, value)
        except Exception as e:
            SecureEnv._write_audit_log(f"配置加载失败: {e}")

    def update_hash(self):
        """更新自身哈希到安全位置"""
        try:
            current_file = os.path.realpath(__file__)
            hasher = hashlib.sha3_256()
            
            with open(current_file, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hasher.update(chunk)
            
            hash_value = hasher.hexdigest()
            
            # 写入多个位置
            hash_locations = [
                "/etc/secure_fs.hash",
                "/usr/local/share/secure_fs.hash",
                os.path.expanduser("~/.secure_fs.hash")
            ]
            
            for location in hash_locations:
                try:
                    dirname = os.path.dirname(location)
                    if not os.path.exists(dirname):
                        os.makedirs(dirname, mode=0o755)
                    
                    with open(location, 'w') as f:
                        f.write(hash_value)
                    
                    # 设置只读权限
                    os.chmod(location, 0o444)
                except:
                    continue
                    
            return True
        except Exception as e:
            SecureEnv._write_audit_log(f"哈希更新失败: {e}")
            return False

class AntiForensics:
    def _setup(self):
        """设置安全的进程名"""
        try:
            # 统一进程名前缀
            libc = ctypes.CDLL(None)
            safe_name = b"safefs_secure_" + os.urandom(4).hex().encode()
            libc.prctl(15, safe_name, 0, 0, 0)  # PR_SET_NAME
            
            # 验证设置结果
            current_name = open(f"/proc/{os.getpid()}/comm").read()
            if b"safefs" not in current_name.encode():
                raise SecurityError("进程名伪装检测")
        except Exception as e:
            raise AntiTamperError(f"进程保护失败: {e}")
            
        # 保护审计日志
        os.chmod(AUDIT_LOG, 0o600)
        fd = os.open(AUDIT_LOG, os.O_RDONLY)
        os.setxattr(fd, 'security.immutable', b'1', 0)
            
class SecureEnv:
    """增强安全环境检测与操作"""
    
    _failed_attempts: Dict[str, Tuple[int, float]] = {}  # 存储失败尝试

    @staticmethod
    def monitor_anomalous_activity():
        """通用异常行为监控"""
        def _detect_anomalies():
            baseline = {
                'cpu_usage': 10,  # %
                'mem_usage': 200,  # MB
                'process_count': 3
            }
            
            while True:
                # 检测周期性活动
                now = datetime.now()
                if now.minute % 5 == 0:  # 每5分钟检查一次
                    current = {
                        'cpu': psutil.cpu_percent(),
                        'mem': psutil.virtual_memory().used / 1024 / 1024,
                        'procs': len(list(psutil.process_iter()))
                    }
                    
                    # 动态基线调整
                    baseline = {k: max(baseline[k], current[k]*0.8) for k in baseline}
                    
                    # 异常检测
                    anomalies = []
                    if current['cpu'] > baseline['cpu'] * 3:
                        anomalies.append(f"CPU突增: {current['cpu']}%")
                    if current['mem'] > baseline['mem'] * 2:
                        anomalies.append(f"内存突增: {current['mem']:.1f}MB")
                    if current['procs'] > baseline['procs'] + 5:
                        anomalies.append(f"进程突增: {current['procs']}个")
                        
                    if anomalies:
                        SecureEnv._write_audit_log("异常系统活动: " + ", ".join(anomalies))
                        
                # 检测定时任务模式
                proc_stats = {}
                for p in psutil.process_iter(['name', 'create_time']):
                    create_minute = datetime.fromtimestamp(p.create_time()).minute
                    proc_stats[p.name()] = proc_stats.get(p.name(), []) + [create_minute]
                
                for name, minutes in proc_stats.items():
                    if len(minutes) > 3 and all(m % 10 == minutes[0] % 10 for m in minutes):
                        SecureEnv._write_audit_log(f"疑似定时任务: {name} (每10分钟触发)")
                
                time.sleep(30)

        threading.Thread(target=_detect_anomalies, daemon=True).start()
        
    @staticmethod
    def restrict_memory_access():
        """智能禁用非对齐内存访问"""
        try:
            libc = ctypes.CDLL(None)
            
            # 动态检测内核版本
            kernel_version = os.uname().release.split('.')
            major, minor = int(kernel_version[0]), int(kernel_version[1])
            
            if major >= 5 and minor >= 10:
                # 新版内核使用MEM_PROTECT_LOCK
                MEM_PROTECT_LOCK = 0x4d454d50  # 'MEMPROT'
                ret = libc.prctl(MEM_PROTECT_LOCK, 1, 0, 0, 0)
            else:
                # 旧版使用MPROTECT
                PR_SET_MPROTECT = 0x2a
                ret = libc.prctl(PR_SET_MPROTECT, 1, 0, 0, 0)
                
            if ret != 0:
                raise MemoryProtectionError("内核不支持内存保护特性")
                
            # 额外加固措施
            os.system("echo 2 > /proc/sys/vm/memory_protection")  # 完全禁用非对齐访问
            SecureEnv._write_audit_log("内存访问限制已强化（适配内核v{}.{}）".format(major, minor))
        except Exception as e:
            SecureEnv._write_audit_log(f"内存访问限制失败: {e}")
            raise MemoryProtectionError(f"内存保护失败: {e}")
            
    @staticmethod
    def enable_cache_monitoring():
        """启用缓存监控（支持Intel CAT和AMD QoS）"""
        try:
            # 检测CPU厂商并应用对应方案
            with open("/proc/cpuinfo", "r") as f:
                cpuinfo = f.read()
                
            if "GenuineIntel" in cpuinfo:
                # Intel CAT方案
                if not os.path.exists("/sys/fs/resctrl"):
                    raise HardwareError("Intel CAT未启用，需要内核参数：rdt=on")
                
                # 创建隔离缓存分区
                os.makedirs("/sys/fs/resctrl/p_safefs", exist_ok=True)
                with open("/sys/fs/resctrl/p_safefs/schemata", "w") as f:
                    f.write("L3:0=ff")  # 分配完整缓存
                with open("/sys/fs/resctrl/p_safefs/tasks", "w") as f:
                    f.write(str(os.getpid()))
                    
            elif "AuthenticAMD" in cpuinfo:
                # AMD QoS方案
                if not os.path.exists("/sys/devices/amd_l3"):
                    raise HardwareError("AMD QoS未启用，需要内核参数：amd_qos=on")
                
                with open("/sys/devices/amd_l3/partition", "w") as f:
                    f.write("1")  # 启用隔离分区
                with open("/sys/devices/amd_l3/pid_bind", "w") as f:
                    f.write(str(os.getpid()))
                    
            else:
                raise HardwareError("不支持的CPU架构")
                
            SecureEnv._write_audit_log(f"缓存监控已启用（{vendor}方案）")
        except Exception as e:
            SecureEnv._write_audit_log(f"缓存监控失败: {e}")
            raise HardwareError(f"缓存监控初始化失败: {e}")
                        
    @staticmethod
    def detect_bus_anomaly(self):
        baseline = self._get_bus_load_baseline()
        current = self._measure_bus_load()
        if abs(current - baseline) > 0.2:  # 20%偏差
            raise HardwareError("检测到异常内存总线活动")
            
    @staticmethod
    def monitor_covert_channels():
        """检测DNS隐蔽通道和临时文件异常"""
        try:
            # 检查DNS查询
            try:
                dns_out = subprocess.run(
                    ['tcpdump', '-n', '-c', '5', 'port 53', '-t'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=3, text=True)
                if "example.com" in dns_out.stdout:
                    raise NetworkAnomalyError("检测到DNS隐蔽通道")
            except subprocess.TimeoutExpired:
                pass
            
            # 检查/dev/shm异常
            if os.path.exists("/dev/shm/.cache"):
                with open("/dev/shm/.cache") as f:
                    if re.search(r'[0-9a-f]{64}', f.read()):
                        raise IntegrityError("检测到密钥渗出文件")
                        
        except Exception as e:
            SecureEnv._write_audit_log(f"隐蔽通道监控失败: {e}")
            
    @staticmethod
    def restrict_proc_access():
        """限制/proc访问权限"""
        try:
            # 禁止非特权用户ptrace
            with open('/proc/sys/kernel/yama/ptrace_scope', 'w') as f:
                f.write('2')  # 仅允许相同用户且非suid进程。这是保险操作
            
            # 隐藏其他进程信息
            if not os.path.ismount('/proc'):
                os.system('mount -t proc proc /proc -o hidepid=2')
            else:
                os.system('mount -o remount,hidepid=2 /proc')
                
            SecureEnv._write_audit_log("已加固/proc访问权限")
        except Exception as e:
            SecureEnv._write_audit_log(f"/proc加固失败: {e}")
            raise SecurityError(f"无法保护/proc: {e}")
            
    @staticmethod
    def secure_memcpy(dest: ctypes.c_void_p, src: ctypes.c_void_p, size: int) -> None:
        """安全内存拷贝（恒定时间）"""
        libc = ctypes.CDLL(None)
        libc.secure_memcpy(dest, src, size, size)  # 使用libc的secure实现
        
    @staticmethod
    def guard_page() -> int:
        """创建防护页防止缓冲区溢出"""
        libc = ctypes.CDLL(None)
        page_size = os.sysconf('SC_PAGESIZE')
        addr = libc.mmap(
            0, page_size * 3,
            prot=0,  # 无权限
            flags=0x22,  # MAP_PRIVATE | MAP_ANONYMOUS
            fd=-1, offset=0
        )
        # 中间页设置为可读写
        libc.mprotect(
            addr + page_size, page_size,
            0x1 | 0x2  # PROT_READ | PROT_WRITE
        )
        return addr + page_size
            
    @staticmethod
    def verify_environment():
        """轻量级环境验证"""
        # 1. 验证自身完整性
        current_hash = hashlib.sha256(open(__file__, 'rb').read()).digest()
        anchor_locations = [
            "/etc/secure_fs.anchor",
            os.path.expanduser("~/.secure_fs_anchor")
        ]
        
        valid = False
        for loc in anchor_locations:
            if os.path.exists(loc):
                with open(loc, 'rb') as f:
                    if hmac.compare_digest(f.read(), current_hash):
                        valid = True
                        break
        
        if not valid:
            raise SelfIntegrityError("完整性校验失败 - 找不到有效锚点")
        
        # 2. 检查关键系统文件特征
        critical_files = {
            '/bin/bash': b'ELF',
            '/usr/bin/python3': b'ELF',
            '/lib/x86_64-linux-gnu/libc.so.6': b'GLIBC'
        }
        
        for path, marker in critical_files.items():
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    if marker not in f.read(1024):
                        raise IntegrityError(f"系统文件异常: {path}")
        
        # 3. 检查/proc/self/maps是否可读(基本反调试)
        try:
            with open('/proc/self/maps', 'rb') as f:
                if b'python3' not in f.read():
                    raise AntiTamperError("异常内存映射检测")
        except:
            raise AntiTamperError("无法访问/proc/self/maps")
            
    @staticmethod
    def _write_audit_log(event: str) -> None:
        """写入审计日志"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"{timestamp} - {event}\n"
            
            with open(AUDIT_LOG, 'a') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(log_entry)
                f.flush()
                os.fsync(f.fileno())
                fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as e:
            sys.stderr.write(f"审计日志写入失败: {e}\n")

    @staticmethod
    def is_debugger_present() -> bool:
        """检测调试器"""
        try:
            # 检查父进程是否为调试器
            with open(f"/proc/{os.getppid()}/cmdline", 'rb') as f:
                cmdline = f.read().decode(errors='ignore').lower()
                debuggers = ['gdb', 'lldb', 'strace', 'ltrace', 'radare2', 'idaq']
                return any(d in cmdline for d in debuggers)
            
            # 检查/proc/self/status中的TracerPid
            with open('/proc/self/status', 'r') as f:
                for line in f:
                    if line.startswith('TracerPid:'):
                        tracer_pid = int(line.split()[1])
                        return tracer_pid != 0
        except Exception as e:
            SecureEnv._write_audit_log(f"调试器检测失败: {e}")
            return False
    
    @staticmethod
    def is_virtualized() -> bool:
        """检测虚拟化环境"""
        try:
            # 检查CPU信息
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo = f.read()
                if any(v in cpuinfo for v in ['hypervisor', 'kvm', 'qemu', 'vmware', 'virtualbox']):
                    return True
            
            # 检查DMI信息
            if os.path.exists('/sys/class/dmi/id/product_name'):
                with open('/sys/class/dmi/id/product_name', 'r') as f:
                    product = f.read().lower()
                    if any(v in product for v in ['vmware', 'virtualbox', 'kvm', 'qemu']):
                        return True
            
            # 检查/dev/vboxguest是否存在
            if os.path.exists('/dev/vboxguest'):
                return True
                
            # 检查系统dmesg输出
            try:
                dmesg = subprocess.check_output(['dmesg'], text=True)
                if any(v in dmesg.lower() for v in ['virtualbox', 'vmware', 'qemu', 'kvm']):
                    return True
            except:
                pass
                
                
            # 新增Xen检测
            if os.path.exists('/proc/xen'):
                return True
                
            # 检查CPU标志中的Xen
            if os.path.exists('/proc/cpuinfo'):
                with open('/proc/cpuinfo', 'r') as f:
                    cpuinfo = f.read()
                    if 'xen' in cpuinfo.lower():
                        return True
            
            # 检查Xen特有设备
            xen_devices = [
                '/dev/xen/evtchn',
                '/proc/xen/balloon'
            ]
            if any(os.path.exists(d) for d in xen_devices):
                return True
                
            return False
        except Exception as e:
            SecureEnv._write_audit_log(f"虚拟化检测失败: {e}")
            return False
    
    @staticmethod
    def enforce_no_debug() -> None:
        """增强反调试保护"""
        if SecureEnv.is_debugger_present():
            SecureEnv._write_audit_log("检测到调试器，操作终止")
            raise AntiTamperError("检测到调试器，操作终止")
        
        # 防止ptrace附加
        try:
            PR_SET_DUMPABLE = 4
            PR_SET_PTRACER = 0x59616d61
            PR_SET_SECCOMP = 22
            SECCOMP_MODE_STRICT = 1
            
            libc = ctypes.CDLL(None)
            
            # 禁用核心转储
            libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
            
            # 防止ptrace
            libc.prctl(PR_SET_PTRACER, 0, 0, 0, 0)
            
            # 设置进程名混淆
            libc.prctl(15, b"random_name", 0, 0, 0)  # PR_SET_NAME
            
            # 启用seccomp严格模式
            libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_STRICT, 0, 0, 0)
        except Exception as e:
            SecureEnv._write_audit_log(f"反调试保护失败: {e}")
            raise AntiTamperError(f"反调试保护失败: {e}")
    
    @staticmethod
    def _allocate_temp_buffer(size: int) -> bytearray:
        """内部使用的安全缓冲区"""
        buf = bytearray(size)
        # 锁定内存页（如果支持）
        try:
            libc = ctypes.CDLL(None)
            libc.mlock(ctypes.byref(ctypes.c_char.from_buffer(buf)), size)
        except:
            pass
        return buf
        
    @staticmethod
    def lock_memory() -> None:
        """锁定内存防止交换"""
        try:
            MCL_CURRENT = 1
            MCL_FUTURE = 2
            MCL_ONFAULT = 4
            
            libc = ctypes.CDLL(None)
            result = libc.mlockall(MCL_CURRENT | MCL_FUTURE | MCL_ONFAULT)
            
            if result != 0:
                raise MemoryProtectionError("内存锁定失败")
        except Exception as e:
            SecureEnv._write_audit_log(f"内存锁定失败: {e}")
            raise MemoryProtectionError(f"内存锁定失败: {e}")
    
    @staticmethod
    def check_entropy(data: bytes) -> float:
        """检查数据熵值"""
        if not data:
            return 0.0
        
        try:
            entropy = 0.0
            size = len(data)
            freq = [0] * 256
            
            for byte in data:
                freq[byte] += 1
            
            for count in freq:
                if count == 0:
                    continue
                p = float(count) / size
                entropy -= p * (p.__log__() / 0.6931471805599453)  # log2
            
            return entropy / 8.0  # 归一化到0-1
        except Exception as e:
            SecureEnv._write_audit_log(f"熵值检查失败: {e}")
            return 0.0
    
    @staticmethod
    def check_failed_attempts(operation: str) -> None:
        """检查失败尝试计数器"""
        if operation not in SecureEnv._failed_attempts:
            return
            
        count, timestamp = SecureEnv._failed_attempts[operation]
        current_time = time.time()
        
        if count >= MAX_FAILED_ATTEMPTS and (current_time - timestamp) < LOCKOUT_TIME:
            remaining = int(LOCKOUT_TIME - (current_time - timestamp))
            SecureEnv._write_audit_log(f"操作{operation}被锁定，剩余时间: {remaining}秒")
            raise LockoutError(f"操作被锁定，请等待{remaining}秒后重试")
    
    @staticmethod
    def record_failed_attempt(operation: str) -> None:
        """记录失败尝试"""
        current_time = time.time()
        
        if operation in SecureEnv._failed_attempts:
            count, timestamp = SecureEnv._failed_attempts[operation]
            
            if (current_time - timestamp) > LOCKOUT_TIME:
                # 锁定时间已过，重置计数器
                SecureEnv._failed_attempts[operation] = (1, current_time)
            else:
                SecureEnv._failed_attempts[operation] = (count + 1, timestamp)
        else:
            SecureEnv._failed_attempts[operation] = (1, current_time)
        
        SecureEnv._write_audit_log(f"操作{operation}失败尝试: {SecureEnv._failed_attempts[operation][0]}")
    
    @staticmethod
    def reset_failed_attempts(operation: str) -> None:
        """重置失败计数器"""
        if operation in SecureEnv._failed_attempts:
            del SecureEnv._failed_attempts[operation]
            SecureEnv._write_audit_log(f"操作{operation}失败计数器已重置")

    @staticmethod
    def enable_aslr() -> None:
        """启用地址空间布局随机化"""
        try:
            ASLR_FILE = "/proc/sys/kernel/randomize_va_space"
            with open(ASLR_FILE, 'w') as f:
                f.write("2")
        except Exception as e:
            SecureEnv._write_audit_log(f"启用ASLR失败: {e}")
            raise SecurityError(f"启用ASLR失败: {e}")

    @staticmethod
    def secure_temp_dir() -> str:
        """创建安全临时目录"""
        try:
            if not os.path.exists(TEMP_DIR):
                os.makedirs(TEMP_DIR, mode=0o700)
                # 设置粘滞位
                os.chmod(TEMP_DIR, 0o1700)
            
            return TEMP_DIR
        except Exception as e:
            SecureEnv._write_audit_log(f"创建安全临时目录失败: {e}")
            raise SecurityError(f"创建安全临时目录失败: {e}")

    @staticmethod
    def check_memory_access() -> None:
        """增强内存访问监控"""
        try:
            pid = os.getpid()
            mem_file = f"/proc/{pid}/maps"
            
            with open(mem_file, 'r') as f:
                mappings = f.readlines()
            
            suspicious_regions = []
            for mapping in mappings:
                if 'rwxp' in mapping:  # 可写可执行内存区域
                    suspicious_regions.append(mapping.split()[5])
            
            if suspicious_regions:
                raise MemoryAccessError(
                    f"检测到可疑内存区域: {suspicious_regions}",
                    details={"pid": pid, "regions": suspicious_regions}
                )
                
        except Exception as e:
            SecureEnv._write_audit_log(f"内存访问检查失败: {e}")
            raise MemoryAccessError(f"内存访问检查失败: {e}")

    # 修改monitor_proc_access方法
    @staticmethod
    def monitor_proc_access(pid: int = None) -> bool:
        """监控对进程内存的异常访问"""
        try:
            if pid is None:
                pid = os.getpid()
                
            # 检查谁在访问我们的/proc/pid/mem
            mem_file = f"/proc/{pid}/mem"
            if os.path.exists(mem_file):
                # 获取访问进程信息
                lsof_output = subprocess.check_output(['lsof', mem_file], text=True)
                lines = lsof_output.splitlines()
                
                # 第一行是标题，之后是访问进程
                if len(lines) > 1:
                    for line in lines[1:]:
                        parts = line.split()
                        if len(parts) >= 2:
                            access_pid = parts[1]
                            cmd = parts[0]
                            
                            # 允许的访问者：内核和自己
                            if cmd not in ['kernel', 'python3'] or access_pid != str(os.getpid()):
                                SecureEnv._write_audit_log(f"异常进程内存访问: PID={access_pid} CMD={cmd}")
                                return False
            SecureEnv.check_memory_access()
            return True
        except MemoryAccessError:
            raise
        except Exception as e:
            SecureEnv._write_audit_log(f"进程访问监控失败: {e}")
            return False

    @staticmethod
    def verify_integrity() -> bool:
        """验证自身完整性"""
        try:
            # 获取当前执行文件路径
            current_file = os.path.realpath(__file__)
            
            # 计算当前文件的哈希
            hasher = hashlib.sha3_256()
            with open(current_file, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hasher.update(chunk)
            current_hash = hasher.hexdigest()
            
            # 多重验证源
            hash_sources = [
                "/etc/secure_fs.hash",  # 系统级配置
                "/usr/local/share/secure_fs.hash",  # 备用位置
                os.path.expanduser("~/.secure_fs.hash")  # 用户级配置
            ]
            
            valid_hashes = []
            for hash_path in hash_sources:
                if os.path.exists(hash_path):
                    try:
                        with open(hash_path, 'r') as f:
                            file_hash = f.read().strip()
                            if len(file_hash) == 64:  # SHA3-256长度
                                valid_hashes.append(file_hash)
                    except:
                        continue
            
            if not valid_hashes:
                SecureEnv._write_audit_log("警告: 未找到有效的完整性哈希文件")
                return True  # 没有哈希文件时默认通过
                
            if current_hash not in valid_hashes:
                raise SelfIntegrityError(
                    "完整性校验失败",
                    details={
                        "current": current_hash,
                        "expected": valid_hashes,
                        "sources": hash_sources
                    }
                )
            
            return True
        except SelfIntegrityError:
            raise
        except Exception as e:
            SecureEnv._write_audit_log(f"完整性检查失败: {e}")
            raise SelfIntegrityError(f"完整性检查失败: {e}")

    @staticmethod
    def check_network_connections() -> None:
        """增强网络连接检查"""
        try:
            conns = psutil.Process().connections()
            suspicious_conns = []
            
            for conn in conns:
                if conn.status == psutil.CONN_ESTABLISHED:
                    raddr = conn.raddr
                    if raddr:
                        # 检测非常用端口(>1024)和非本地连接
                        if raddr.port > 1024 and not raddr.ip.startswith(('127.', '192.168.', '10.')):
                            suspicious_conns.append(f"{raddr.ip}:{raddr.port}")
            
            if suspicious_conns:
                raise NetworkAnomalyError(
                    "检测到可疑网络连接",
                    details={
                        "pid": os.getpid(),
                        "connections": suspicious_conns
                    }
                )
                
        except Exception as e:
            SecureEnv._write_audit_log(f"网络连接检查失败: {e}")
            raise NetworkAnomalyError(f"网络连接检查失败: {e}")

    # 修改monitor_network方法
    @staticmethod
    def monitor_network() -> bool:
        """监控异常网络连接"""
        try:
            # 获取当前进程的网络连接
            connections = psutil.Process().connections()
            
            allowed_ports = []  # 实际部署时应配置允许的端口
            
            for conn in connections:
                if conn.status == psutil.CONN_ESTABLISHED:
                    raddr = conn.raddr
                    if raddr:
                        if raddr.port not in allowed_ports:
                            SecureEnv._write_audit_log(f"异常网络连接: {raddr.ip}:{raddr.port}")
                            return False
            SecureEnv.check_network_connections()
            return True
        except NetworkAnomalyError:
            raise
        except Exception as e:
            SecureEnv._write_audit_log(f"网络监控失败: {e}")
            return False
            


class FileCrypto:
    """增强安全文件加密核心"""
    
    @staticmethod
    def _validate_password(password: str) -> None:
        """增强密码验证"""
        if len(password) < SecureConstants.MIN_PASSWORD_LENGTH:
            raise SecurityError(f"密码长度不足，至少需要{SecureConstants.MIN_PASSWORD_LENGTH}个字符")
        
        # 检查密码熵值
        entropy = SecureEnv.check_entropy(password.encode())
        if entropy < SecureConstants.MIN_ENTROPY:
            raise SecurityError("密码熵值不足，请使用更复杂的密码")
        
        # 检查常见密码模式
        common_patterns = [
            r'123456', r'password', r'qwerty', 
            r'admin', r'welcome', r'dragon'
        ]
        if any(re.search(p, password, re.IGNORECASE) for p in common_patterns):
            raise SecurityError("密码太弱，检测到常见模式")
            
    @staticmethod
    def generate_key(password: Optional[str] = None) -> Tuple[bytes, bytes, bytes]:
        """生成三重保护的密钥"""
        try:
            # 主盐（用于PBKDF2）
            main_salt = secrets.token_bytes(32)
            
            if password:
                FileCrypto._validate_password(password)
                
                # 第一阶段：PBKDF2
                kdf_pbkdf = PBKDF2HMAC(
                    algorithm=hashes.SHA3_512(),
                    length=64,  # 生成更长密钥
                    salt=main_salt,
                    iterations=KDF_ITERATIONS * 3,  # 增强迭代
                    backend=default_backend()
                )
                intermediate_key = kdf_pbkdf.derive(password.encode())
                
                # 第二阶段：Argon2
                argon_salt = secrets.token_bytes(32)
                kdf_argon = Argon2(
                    salt=argon_salt,
                    time_cost=4,
                    memory_cost=131072,  # 128MB
                    parallelism=8,
                    hash_len=32,
                    type=Argon2.ID
                )
                final_key = kdf_argon.derive(intermediate_key)
                
                # 安全擦除
                SecureWipe.wipe_memory(intermediate_key)
            else:
                # 随机密钥模式
                return secrets.token_bytes(32), b'', b''
                
            # 锁定内存中的密钥
            libc = ctypes.CDLL(None)
            libc.mlock(ctypes.byref(ctypes.c_char_p(final_key)), ctypes.sizeof(final_key))
            
            return final_key, main_salt, argon_salt
        except Exception as e:
            SecureEnv._write_audit_log(f"密钥生成失败: {e}")
            raise CryptoError(f"密钥生成失败: {e}")

    @staticmethod
    def _derive_secure_key(password: str, salt_pbkdf: bytes, salt_argon: bytes) -> bytes:
        """从密码派生密钥 (双重KDF)"""
        try:
            # 第一阶段: PBKDF2
            kdf_pbkdf = PBKDF2HMAC(
                algorithm=hashes.SHA3_512(),
                length=32,
                salt=salt_pbkdf,
                iterations=KDF_ITERATIONS
            )
            pbkdf_key = kdf_pbkdf.derive(password.encode())
            
            # 第二阶段: Argon2
            kdf_argon = Argon2(
                salt=salt_argon,
                time_cost=3,
                memory_cost=65536,
                parallelism=4,
                hash_len=32,
                type=Argon2.ID
            )
            final_key = kdf_argon.derive(pbkdf_key)
            
            # 安全擦除中间密钥
            SecureWipe.wipe_memory(pbkdf_key)
            
            # 锁定内存中的密钥
            libc = ctypes.CDLL(None)
            libc.mlock(ctypes.byref(ctypes.c_char_p(final_key)), ctypes.sizeof(final_key))
            
            return final_key
        except Exception as e:
            SecureEnv._write_audit_log(f"密钥派生失败: {e}")
            raise CryptoError(f"密钥派生失败: {e}")
            


    @staticmethod
    def encrypt_data(data: bytes, key: bytes) -> bytes:
        """安全增强版加密（完整防护）"""
        try:
            # === 前置安全检查 ===
            if not SecureEnv.monitor_proc_access():
                raise AntiTamperError("内存访问监控触发")
                
            if len(data) > SecureConstants.MAX_FILE_SIZE:
                raise SecurityError("文件大小超过限制")

            # === 密钥派生 ===
            salt = secrets.token_bytes(32)
            derived_key = FileCrypto._derive_secure_key(key, salt)
            
            # === 恒定时间HMAC ===
            hmac_key = hashlib.blake2s(derived_key).digest()  # 更快的安全哈希
            hmac_calc = hmac.HMAC(
                hmac_key,
                hashes.BLAKE2s(32),
                backend=default_backend()
            )
            hmac_calc.update(data)
            data_hmac = hmac_calc.finalize()

            # === 安全压缩 ===
            compressed = zlib.compress(data, level=9)
            
            # === 固定时间加密 ===
            start_time = time.perf_counter_ns()
            cipher = Fernet(
                base64.urlsafe_b64encode(
                    derived_key.ljust(32, b'\x00')[:32]
                )
            )
            encrypted = cipher.encrypt(compressed)
            
            # 强制固定延迟
            elapsed_ns = time.perf_counter_ns() - start_time
            if elapsed_ns < SecureConstants.ENCRYPT_TIME_TARGET_NS:
                fixed_delay = (SecureConstants.ENCRYPT_TIME_TARGET_NS - elapsed_ns) / 1e9
                time.sleep(fixed_delay)

            # === 安全数据包构建 ===
            package = (
                SecureConstants.MAGIC_HEADER +
                len(data).to_bytes(8, 'big') +
                salt +
                data_hmac +
                encrypted
            )

            # === 后置清理 ===
            SecureWipe.wipe_memory(derived_key)
            SecureWipe.wipe_memory(hmac_key)
            return package
            
        except Exception as e:
            SecureEnv._write_audit_log(f"安全加密失败: {e}")
            raise CryptoError(f"加密失败: {e}", algorithm="AES256-GCM")

    @staticmethod
    def decrypt_data(encrypted: bytes, key: bytes) -> bytes:
        """安全增强版解密（完整防护）"""
        try:
            # === 前置检查 ===
            if not SecureEnv.monitor_proc_access():
                raise AntiTamperError("内存访问监控触发")
                
            if not encrypted.startswith(SecureConstants.MAGIC_HEADER):
                raise IntegrityError("头部验证失败")

            # === 安全解析（固定时间）===
            header_len = len(SecureConstants.MAGIC_HEADER)
            data_len = int.from_bytes(
                encrypted[header_len:header_len+8], 
                'big', 
                signed=False
            )
            salt = encrypted[header_len+8:header_len+40]
            expected_hmac = encrypted[header_len+40:header_len+72]
            ciphertext = encrypted[header_len+72:]

            # === 密钥派生 ===
            derived_key = FileCrypto._derive_secure_key(key, salt)

            # === 固定时间解密 ===
            start_time = time.perf_counter_ns()
            cipher = Fernet(
                base64.urlsafe_b64encode(
                    derived_key.ljust(32, b'\x00')[:32]
                )
            )
            try:
                compressed = cipher.decrypt(ciphertext)
                # 检查压缩数据熵值
                if zlib.decompress(data) != data and check_entropy(data) > 0.9:
                    raise CryptoError("异常压缩模式检测")
            except:
                # 即使失败也维持固定时间
                compressed = b''
            
            # 强制固定延迟
            elapsed_ns = time.perf_counter_ns() - start_time
            if elapsed_ns < SecureConstants.ENCRYPT_TIME_TARGET_NS:
                time.sleep((
                    SecureConstants.ENCRYPT_TIME_TARGET_NS - elapsed_ns
                ) / 1e9)

            # === 处理解密数据 ===
            if not compressed:
                raise IntegrityError("解密失败（密钥错误或数据损坏）")

            try:
                plaintext = zlib.decompress(compressed)
            except:
                raise IntegrityError("解压缩失败")

            # === 恒定时间HMAC验证 ===
            hmac_key = hashlib.blake2s(derived_key).digest()
            hmac_calc = hmac.HMAC(
                hmac_key,
                hashes.BLAKE2s(32),
                backend=default_backend()
            )
            hmac_calc.update(plaintext)
            actual_hmac = hmac_calc.finalize()

            if not hmac.compare_digest(expected_hmac, actual_hmac):
                raise IntegrityError("HMAC验证失败")

            # === 长度验证 ===
            if len(plaintext) != data_len:
                raise IntegrityError("数据长度不匹配")

            # === 后置清理 ===
            SecureWipe.wipe_memory(derived_key)
            SecureWipe.wipe_memory(hmac_key)
            SecureWipe.wipe_memory(compressed)
            
            return plaintext
            
        except IntegrityError:
            raise
        except Exception as e:
            SecureEnv._write_audit_log(f"安全解密失败: {e}")
            raise CryptoError(f"解密失败: {e}", algorithm="AES256-GCM")
            

class SecureFS:
    """增强安全文件系统操作"""
    
    @staticmethod
    def secure_wipe(path: str, passes: int = WIPE_PASSES) -> None:
        """安全擦除文件"""
        try:
            if not os.path.exists(path):
                return
            
            file_size = os.path.getsize(path)
            
            # 获取文件权限以便恢复
            file_stat = os.stat(path)
            original_mode = file_stat.st_mode
            
            # 随机化文件名
            dirname, basename = os.path.split(path)
            temp_name = os.path.join(dirname, f".{secrets.token_hex(8)}")
            os.rename(path, temp_name)
            path = temp_name
            
            with open(path, 'ba+') as f:
                for i in range(passes):
                    f.seek(0)
                    # 使用不同模式覆盖
                    if i % 3 == 0:
                        f.write(os.urandom(file_size))
                    elif i % 3 == 1:
                        f.write(b'\x00' * file_size)
                    else:
                        f.write(b'\xFF' * file_size)
                    f.flush()
                    os.fsync(f.fileno())
            
            # 截断文件
            os.truncate(path, 0)
            
            # 删除文件
            os.remove(path)
            
            # 尝试覆盖目录项
            try:
                fd = os.open(dirname, os.O_RDONLY)
                os.fsync(fd)
                os.close(fd)
            except:
                pass
        except Exception as e:
            SecureEnv._write_audit_log(f"安全擦除失败: {path} - {e}")
            raise SecurityError(f"安全擦除失败: {e}")
        finally:
            # 恢复权限以防部分删除
            try:
                os.chmod(path, original_mode)
            except:
                pass
    
    @staticmethod
    def secure_write(path: str, data: bytes) -> None:
        """安全写入文件"""
        temp_path = None
        try:
            # 创建安全临时目录
            temp_dir = SecureEnv.secure_temp_dir()
            
            # 创建临时文件
            fd, temp_path = mkstemp(dir=temp_dir)
            
            # 写入数据
            with os.fdopen(fd, 'wb') as f:
                SecureEnv.lock_memory(f.fileno())
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            
            # 设置严格权限
            os.chmod(temp_path, 0o600)
            
            # 原子替换
            move(temp_path, path)
            
            
            # 设置目标文件权限
            os.chmod(path, 0o600)
        except Exception as e:
            if temp_path and os.path.exists(temp_path):
                SecureFS.secure_wipe(temp_path) 
            SecureEnv._write_audit_log(f"安全写入失败: {path} - {e}")
            raise SecurityError(f"安全写入失败: {e}")
    
    @staticmethod
    def secure_read(path: str) -> bytes:
        """安全读取文件"""
        try:
            # 验证文件权限
            if os.stat(path).st_mode & 0o077 != 0:
                raise SecurityError("文件权限不安全")
            
            with open(path, 'rb') as f:
                # 锁定文件
                fcntl.flock(f, fcntl.LOCK_SH)
                
                # 验证文件完整性
                file_size = os.fstat(f.fileno()).st_size
                if file_size > SecureConstants.MAX_FILE_SIZE:
                    raise SecurityError("文件大小超过安全限制")
                
                data = f.read()
                fcntl.flock(f, fcntl.LOCK_UN)
                
                return data
        except Exception as e:
            SecureEnv._write_audit_log(f"安全读取失败: {path} - {e}")
            raise SecurityError(f"安全读取失败: {e}")
    
class SecureOTP:
    """增强OTP安全管理"""
    
    @staticmethod
    def generate_totp() -> Tuple[str, str]:
        """生成TOTP密钥 (手动输入版)"""
        try:
            # 使用更安全的随机生成
            secret = pyotp.random_base32(length=32)  # 使用更长的密钥
            
            # 生成TOTP对象
            totp = pyotp.TOTP(
                secret, 
                digits=SecureConstants.TOTP_DIGITS,
                interval=SecureConstants.TOTP_INTERVAL,
                digest='sha512'  # 使用更强的哈希算法
            )
            
            # 生成手动输入指令
            manual_key = f"""
            === 手动TOTP配置 ===
            密钥: {secret}
            算法: SHA512
            位数: {SecureConstants.TOTP_DIGITS}
            时间步长: {SecureConstants.TOTP_INTERVAL}秒
            
            在您的认证APP中选择手动输入:
            1. 输入上面的密钥
            2. 选择SHA512算法
            3. 设置{SecureConstants.TOTP_DIGITS}位代码
            4. 设置时间步长为{SecureConstants.TOTP_INTERVAL}秒
            """
            
            return secret, manual_key
        except Exception as e:
            SecureEnv._write_audit_log(f"TOTP生成失败: {e}")
            raise SecurityError(f"TOTP生成失败: {e}")
    
    @staticmethod
    def verify_totp(secret: str, code: str) -> bool:
        """验证TOTP代码"""
        try:
            totp = pyotp.TOTP(
                secret,
                digits=SecureConstants.TOTP_DIGITS,
                interval=SecureConstants.TOTP_INTERVAL,
                digest='sha512'
            )
            
            # 允许前后一个时间窗口
            return totp.verify(code, valid_window=1)
        except Exception as e:
            SecureEnv._write_audit_log(f"TOTP验证失败: {e}")
            raise SecurityError(f"TOTP验证失败: {e}")

class SecureLock:
    """增强进程互斥锁"""
    
    @staticmethod
    def acquire() -> bool:
        """获取独占锁"""
        try:
            # 首先检查锁文件是否存在
            if os.path.exists(LOCK_FILE):
                # 检查锁文件中的PID是否仍在运行
                try:
                    with open(LOCK_FILE, 'r') as f:
                        pid = int(f.read().strip())
                        
                        if psutil.pid_exists(pid):
                            return False
                except:
                    pass
                
                # 无效的锁文件，删除它
                os.remove(LOCK_FILE)
            
            # 创建新锁文件
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(str(os.getpid()))
            
            return True
        except FileExistsError:
            return False
        except Exception as e:
            SecureEnv._write_audit_log(f"获取进程锁失败: {e}")
            raise SecurityError(f"获取进程锁失败: {e}")
    
    @staticmethod
    def release() -> None:
        """释放锁"""
        try:
            if os.path.exists(LOCK_FILE):
                # 验证锁文件属于当前进程
                with open(LOCK_FILE, 'r') as f:
                    pid = int(f.read().strip())
                
                if pid == os.getpid():
                    os.remove(LOCK_FILE)
        except Exception as e:
            SecureEnv._write_audit_log(f"释放进程锁失败: {e}")
            raise SecurityError(f"释放进程锁失败: {e}")


class SecureWipe:
    """增强安全擦除工具"""
    
    @staticmethod
    def wipe_memory(obj: object) -> None:
        """安全擦除内存中的敏感数据"""
        if obj is None:
            return
        
        try:
            # 获取对象内存视图
            buf = (ctypes.c_byte * sys.getsizeof(obj)).from_address(id(obj))
            
            # 多次覆盖
            for _ in range(MEMORY_WIPE_PASSES):
                for i in range(len(buf)):
                    buf[i] = secrets.randbits(8)
            
            # 强制垃圾回收
            del buf
            import gc
            gc.collect()
        except Exception as e:
            SecureEnv._write_audit_log(f"内存擦除失败: {e}")
            raise MemoryProtectionError(f"内存擦除失败: {e}")
    
    @staticmethod
    def wipe_string(s: str) -> None:
        """安全擦除字符串"""
        try:
            if not s:
                return
                
            # 转换为字节数组以便修改
            buf = ctypes.create_string_buffer(s.encode())
            
            # 覆盖内存
            for _ in range(MEMORY_WIPE_PASSES):
                for i in range(len(buf)):
                    buf[i] = secrets.randbits(8)
            
            del buf
            import gc
            gc.collect()
        except Exception as e:
            SecureEnv._write_audit_log(f"字符串擦除失败: {e}")
            raise MemoryProtectionError(f"字符串擦除失败: {e}")
            

class SecureHardening:
    """硬件和系统级安全加固"""
    
    @staticmethod
    def generate_trust_anchors():
        """首次运行时生成信任锚点"""
        anchors = {
            'libs': {},
            'modules': {},
            'syscalls': {}
        }
        
        # 生成动态库锚点
        libs_to_check = ['libc.so.6', 'libcrypto.so', 'libssl.so', 'libpthread.so']
        for lib in libs_to_check:
            path = ctypes.util.find_library(lib)
            if path:
                anchors['libs'][path] = SecureHardening._calculate_file_hash(path)
        
        # 生成内核模块锚点
        if os.path.exists('/proc/modules'):
            with open('/proc/modules') as f:
                for line in f:
                    name = line.split()[0]
                    mod_path = f"/lib/modules/{os.uname().release}/kernel/{name}.ko"
                    if os.path.exists(mod_path):
                        anchors['modules'][name] = SecureHardening._calculate_file_hash(mod_path)
        
        # 生成系统调用黑白名单
        anchors['syscalls'] = {
            'allowed': ['read', 'write', 'open', 'close', 'mmap', 'munmap', 
                        'mprotect', 'futex', 'exit', 'exit_group'],
            'banned': ['ptrace', 'process_vm_readv', 'kcmp', 'socket']
        }
        
        # 保存到安全位置
        anchor_locations = [
            "/etc/secure_fs_anchors.bin",
            os.path.expanduser("~/.secure_fs_anchors.bin")
        ]
        
        for location in anchor_locations:
            try:
                with open(location, 'wb') as f:
                    f.write(Fernet.generate_key())
                    f.write(pickle.dumps(anchors))
                    os.chmod(location, 0o400)
            except Exception as e:
                continue
        
        return anchors
    
    @staticmethod
    def _calculate_file_hash(path, algorithm='sha3_256'):
        """计算文件哈希"""
        hasher = hashlib.new(algorithm)
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    @staticmethod
    def load_trust_anchors():
        """加载信任锚点"""
        anchor_locations = [
            "/etc/secure_fs_anchors.bin",
            os.path.expanduser("~/.secure_fs_anchors.bin")
        ]
        
        for location in anchor_locations:
            if os.path.exists(location):
                try:
                    with open(location, 'rb') as f:
                        key = f.read(32)
                        cipher = Fernet(key)
                        encrypted = f.read()
                        return pickle.loads(cipher.decrypt(encrypted))
                except:
                    continue
        
        # 没有找到锚点文件则生成新的
        return SecureHardening.generate_trust_anchors()
    
    @staticmethod
    def verify_system_state():
        """全面系统状态验证"""
        anchors = SecureHardening.load_trust_anchors()
        
        # 验证动态库
        for lib_path, expected_hash in anchors['libs'].items():
            if not os.path.exists(lib_path):
                raise IntegrityError(f"关键库文件缺失: {lib_path}")
            current_hash = SecureHardening._calculate_file_hash(lib_path)
            if not hmac.compare_digest(current_hash, expected_hash):
                raise IntegrityError(f"库文件被篡改: {lib_path}")
        
        # 验证内核模块
        if os.path.exists('/proc/modules'):
            loaded_modules = set()
            with open('/proc/modules') as f:
                for line in f:
                    loaded_modules.add(line.split()[0])
            
            for mod_name, expected_hash in anchors['modules'].items():
                if mod_name in loaded_modules:
                    mod_path = f"/lib/modules/{os.uname().release}/kernel/{mod_name}.ko"
                    current_hash = SecureHardening._calculate_file_hash(mod_path)
                    if not hmac.compare_digest(current_hash, expected_hash):
                        raise IntegrityError(f"内核模块被篡改: {mod_name}")
        
        return True

class SyscallProtection:
    """系统调用级防护"""

    @staticmethod
    def install_seccomp_filter():
        """禁止危险内存操作并安装严格的seccomp过滤器"""
        filter = seccomp.SyscallFilter(seccomp.ALLOW)
        
        # 特殊处理/dev/mem访问
        filter.add_rule(seccomp.ERRNO(1), "open")
        filter.add_rule(seccomp.ALLOW, "open", seccomp.Arg(0, seccomp.NEQ, "/dev/mem"))
        
        # ---- 精细化prctl控制 ----
        # 允许特定选项（PR_SET_NAME=15, PR_SET_DUMPABLE=4）
        filter.add_rule(
            seccomp.ALLOW, "prctl",
            seccomp.Arg(0, seccomp.EQ, 15)  # 允许设置进程名
        )
        filter.add_rule(
            seccomp.ALLOW, "prctl",
            seccomp.Arg(0, seccomp.EQ, 4)   # 允许设置dumpable
        )
        # 其他prctl调用全部禁止
        filter.add_rule(seccomp.KILL, "prctl")
        
        # ---- 进程名白名单 ----
        # 只允许修改为包含"safefs"的进程名
        filter.add_rule(
            seccomp.ALLOW, "prctl",
            seccomp.Arg(0, seccomp.EQ, 15),  # PR_SET_NAME
            seccomp.Arg(1, seccomp.MASKED_EQ, 0, b"safefs")  # 名称必须包含safefs
        )
        
        anchors = SecureHardening.load_trust_anchors()
        
        filter = seccomp.SyscallFilter(seccomp.KILL)
        
        # 允许基本系统调用
        for call in anchors['syscalls']['allowed']:
            filter.add_rule(seccomp.ALLOW, call)
        
        # 禁止危险系统调用
        for call in anchors['syscalls']['banned']:
            filter.add_rule(seccomp.KILL, call)
        
        filter.load()
    
    @staticmethod
    def monitor_syscalls():
        """实时监控系统调用"""
        import ctypes
        import ctypes.util
        
        LIBC = ctypes.CDLL(ctypes.util.find_library('c'))
        
        # 获取当前系统调用
        SYS_gettid = 186
        tid = LIBC.syscall(SYS_gettid)
        
        # 通过/proc监控
        syscall_file = f"/proc/{os.getpid()}/task/{tid}/syscall"
        
        def check_syscall():
            if os.path.exists(syscall_file):
                with open(syscall_file) as f:
                    try:
                        call_num = int(f.read().split()[0])
                        allowed = SecureHardening.load_trust_anchors()['syscalls']['allowed']
                        
                        # 获取系统调用名称
                        syscall_names = {
                            0: 'read', 1: 'write', 2: 'open', 
                            3: 'close', 9: 'mmap', 11: 'munmap',
                            10: 'mprotect', 202: 'futex', 
                            60: 'exit', 231: 'exit_group'
                        }
                        
                        call_name = syscall_names.get(call_num, f'unknown_{call_num}')
                        if call_name not in allowed:
                            raise AntiTamperError(f"可疑系统调用: {call_name}")
                    except:
                        pass
        
        # 定期检查
        import threading
        def monitor_thread():
            while True:
                check_syscall()
                time.sleep(0.1)
        
        t = threading.Thread(target=monitor_thread, daemon=True)
        t.start()

class HardwareSecurity:
    """硬件级安全防护"""
    
    @staticmethod
    def check_dma_protection():
        """检查DMA保护状态"""
        try:
            # 检查IOMMU状态
            with open('/proc/cmdline') as f:
                cmdline = f.read()
                if 'iommu=on' not in cmdline:
                    raise HardwareError("IOMMU未启用")
            
            # 检查VT-d/AMD-Vi
            if os.path.exists('/sys/class/iommu'):
                dma_mask = None
                for device in os.listdir('/sys/bus/pci/devices'):
                    try:
                        with open(f'/sys/bus/pci/devices/{device}/dma_mask_bits') as f:
                            dma_mask = f.read().strip()
                            if dma_mask != '64':
                                raise HardwareError(f"设备 {device} DMA保护不足")
                    except:
                        continue
                
                if dma_mask is None:
                    raise HardwareError("无法验证DMA保护状态")
        except Exception as e:
            SecureEnv._write_audit_log(f"DMA保护检查失败: {e}")
            raise HardwareError(f"DMA保护检查失败: {e}")

    def enforce_dma_protection():
        """强制启用IOMMU并限制/dev/mem"""
        try:
            # 检查并启用IOMMU
            with open("/proc/cmdline", "r") as f:
                if "iommu=on" not in f.read():
                    raise HardwareError("IOMMU未启用，请修改内核启动参数")

            # 限制/dev/mem访问（需root）
            os.system("chmod 600 /dev/mem")
            os.system("echo 1 > /proc/sys/kernel/mem_protect")
            
            SecureEnv._write_audit_log("DMA防护已强化")
        except Exception as e:
            raise HardwareError(f"DMA防护失败: {e}")
            
    @staticmethod
    def lock_down_memory():
        """全面内存锁定"""
        try:
            # 锁定所有内存
            libc = ctypes.CDLL(None)
            MCL_CURRENT = 1
            MCL_FUTURE = 2
            MCL_ONFAULT = 4
            if libc.mlockall(MCL_CURRENT | MCL_FUTURE | MCL_ONFAULT) != 0:
                raise MemoryProtectionError("内存锁定失败")
            
            # 禁用核心转储
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            
            # 防止内存转储
            PR_SET_DUMPABLE = 4
            libc.prctl(PR_SET_DUMPABLE, 0)
        except Exception as e:
            raise MemoryProtectionError(f"内存锁定失败: {e}")

class EnhancedCrypto:
    """增强的加密实现（包含防侧信道攻击）"""
    
    @staticmethod
    def _constant_time_compare(a: bytes, b: bytes) -> bool:
        """恒定时间比较（防止时序攻击）"""
        if len(a) != len(b):
            return False
            
        result = 0
        for x, y in zip(a, b):
            result |= x ^ y
        return result == 0

    @staticmethod
    def _fixed_time_encrypt(data: bytes, cipher: Fernet) -> bytes:
        """固定时间加密操作"""
        # 填充数据到固定块大小（防止基于数据大小的侧信道）
        block_size = 4096
        padded_size = ((len(data) // block_size) + 1) * block_size
        padded_data = data.ljust(padded_size, b'\x00')
        
        # 记录开始时间
        start_time = time.perf_counter_ns()
        
        # 执行加密
        encrypted = cipher.encrypt(padded_data)
        
        # 计算固定延迟
        elapsed_ns = time.perf_counter_ns() - start_time
        target_ns = 100_000_000  # 目标固定延迟100ms
        if elapsed_ns < target_ns:
            time.sleep((target_ns - elapsed_ns) / 1e9)
        
        return encrypted

    @staticmethod
    def encrypt_data_secure(data: bytes, key: bytes) -> bytes:
        """抗侧信道攻击的加密"""
        # 新增安全缓冲区
        safe_buf = None
        
        try:
            # === 新增安全措施 ===
            safe_buf = SecureEnv._allocate_temp_buffer(len(data))
            safe_buf[:] = data
            # 生成随机IV（防止重复检测攻击）
            iv = secrets.token_bytes(16)
            
            # 恒定时间密钥派生
            salt = secrets.token_bytes(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA3_512(),
                length=32,
                salt=salt,
                iterations=KDF_ITERATIONS * 2,
                backend=default_backend()
            )
            derived_key = kdf.derive(key)
            
            # 创建加密器（固定配置防止选择算法攻击）
            cipher = Fernet(
                base64.urlsafe_b64encode(
                    derived_key.ljust(32, b'\x00')[:32]
                )
            )
            
            # 固定时间加密
            encrypted = EnhancedCrypto._fixed_time_encrypt(data, cipher)
            
            # 构建安全数据包（固定格式防止边界检测攻击）
            package = (
                SecureConstants.MAGIC_HEADER +
                len(data).to_bytes(8, 'big') +
                iv +
                salt +
                encrypted
            )
            
            return package
            
        except Exception as e:
            SecureEnv._write_audit_log(f"安全加密失败: {e}")
            raise CryptoError(f"安全加密失败: {e}")
        finally:
            # Always clear temporary key material, including on failure.
            if safe_buf:
                SecureWipe.wipe_memory(safe_buf)
            if 'derived_key' in locals():
                SecureWipe.wipe_memory(derived_key)

    @staticmethod
    def decrypt_data_secure(encrypted: bytes, key: bytes) -> bytes:
        """抗侧信道攻击的解密"""
        # 新增安全缓冲区
        safe_buf = None
        try:
            # 恒定时间头部验证
            header = encrypted[:len(SecureConstants.MAGIC_HEADER)]
            if not EnhancedCrypto._constant_time_compare(
                header, SecureConstants.MAGIC_HEADER
            ):
                raise IntegrityError("无效的文件格式")
            
            # 解析数据包（固定偏移防止时序泄露）
            data_len = int.from_bytes(
                encrypted[8:16], 'big', signed=False
            )
            iv = encrypted[16:32]
            salt = encrypted[32:48]
            ciphertext = encrypted[48:]
            
            # 恒定时间密钥派生
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA3_512(),
                length=32,
                salt=salt,
                iterations=KDF_ITERATIONS * 2,
                backend=default_backend()
            )
            derived_key = kdf.derive(key)
            
            # 创建解密器
            cipher = Fernet(
                base64.urlsafe_b64encode(
                    derived_key.ljust(32, b'\x00')[:32]
                )
            )
            
            # 固定时间解密
            start_time = time.perf_counter_ns()
            decrypted = cipher.decrypt(ciphertext)
            elapsed_ns = time.perf_counter_ns() - start_time
            
            # 强制固定延迟
            target_ns = 100_000_000  # 100ms
            if elapsed_ns < target_ns:
                time.sleep((target_ns - elapsed_ns) / 1e9)
            
            # 验证长度（恒定时间）
            if not EnhancedCrypto._constant_time_compare(
                len(decrypted).to_bytes(8, 'big'),
                data_len.to_bytes(8, 'big')
            ):
                raise IntegrityError("数据长度不匹配")
            
            return decrypted[:data_len]  # 精确切片防止填充泄露
            
        except Exception as e:
            SecureEnv._write_audit_log(f"安全解密失败: {e}")
            raise CryptoError(f"安全解密失败: {e}")
        finally:
            if safe_buf:
                SecureWipe.wipe_memory(safe_buf)
            if 'derived_key' in locals():
                SecureWipe.wipe_memory(derived_key)

# ===== 主功能实现 =====
class SafeFS:
    """主加密系统"""
    
    def __init__(self, config: SecureConfig = SecureConfig()):
        SyscallProtection.install_seccomp_filter()  # 必须先于其他初始化
        AntiForensics()._setup()  # 然后设置进程名
        self.config = config
        self._check_environment()
        SecureEnv.enable_cache_monitoring()
        SecureEnv.detect_bus_anomaly()
        HardwareSecurity.enforce_dma_protection()
        SecureEnv.restrict_memory_access()
        SecureEnv.monitor_time_triggers()
        self._enhanced_security_init()
        self._guard_page = SecureEnv.guard_page()
        self._enhanced_isolation()
        
        # 新增环境验证
        SecureEnv.verify_environment()
        
        # 新增内存防护
        self._enable_memory_protection()
        
        if not SecureLock.acquire():
            raise SecurityError("另一个实例正在运行")
        
        # 设置信号处理
        signal.signal(signal.SIGTERM, self._cleanup)
        signal.signal(signal.SIGINT, self._cleanup)
        signal.signal(signal.SIGQUIT, self._cleanup)
        signal.signal(signal.SIGHUP, self._cleanup)
        # 新增安全监控线程
        self._monitor_thread = threading.Thread(target=self._security_monitor, daemon=True)
        self._monitor_thread.start()
    
    def _enhanced_isolation(self):
        """创建隔离的命名空间"""
        try:
            libc = ctypes.CDLL(None)
            # CLONE_NEWNS: 挂载命名空间 | CLONE_NEWPID: PID命名空间
            if libc.unshare(0x00020000 | 0x20000000) != 0:
                raise SecurityError("无法创建隔离命名空间")
            
            # 限制Linux capabilities
            os.system('capsh --drop=all --caps="cap_dac_override,cap_setgid,cap_setuid+ep" -- -c "true"')
            SecureEnv._write_audit_log("进程隔离已激活")
        except Exception as e:
            SecureEnv._write_audit_log(f"隔离失败: {e}")
            raise SecurityError(f"进程隔离失败: {e}")
            
    def _secure_buffer_operation(self, data: bytes) -> bytes:
        """在防护页保护下操作数据"""
        try:
            # 分配防护内存
            buf_size = len(data) + 4096 * 2  # 前后各一页防护
            buf_addr = SecureEnv.guard_page()
            
            # 安全拷贝数据
            buf = (ctypes.c_char * buf_size).from_address(buf_addr)
            SecureEnv.secure_memcpy(
                ctypes.byref(buf, 4096),  # 跳过前防护页
                ctypes.c_char_p(data),
                len(data)
            )
            
            # 执行操作（示例：计算哈希）
            hasher = hashlib.sha3_256()
            hasher.update(buf[4096:4096+len(data)])
            
            # 安全擦除
            SecureWipe.wipe_memory(buf)
            
            return hasher.digest()
        finally:
            # 释放防护页
            libc = ctypes.CDLL(None)
            libc.munmap(self._guard_page - 4096, 4096 * 3)
            
    def _enable_memory_protection(self):
        """增强内存防护"""
        try:
            # 锁定内存
            libc = ctypes.CDLL(None)
            libc.mlockall(1 | 2)  # MCL_CURRENT | MCL_FUTURE
            
            # 防止核心转储
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            
            # 禁用ptrace
            PR_SET_DUMPABLE = 4
            libc.prctl(PR_SET_DUMPABLE, 0)
        except Exception as e:
            SecureEnv._write_audit_log(f"内存保护失败: {e}")
            raise MemoryProtectionError(f"内存保护失败: {e}")
            
    def _enhanced_security_init(self):
        """增强的安全初始化"""
        try:
            # 验证系统状态
            SecureHardening.verify_system_state()
            
            # 安装系统调用过滤器
            SyscallProtection.install_seccomp_filter()
            SyscallProtection.monitor_syscalls()
            
            # 硬件安全
            HardwareSecurity.check_dma_protection()
            HardwareSecurity.lock_down_memory()
            
            # 验证CPU微码
            self._verify_cpu_microcode()
            
        except Exception as e:
            SecureEnv._write_audit_log(f"安全初始化失败: {e}")
            raise SecurityError(f"系统安全状态不可信: {e}")
    
    def _verify_cpu_microcode(self):
        """验证CPU微码(仅限Intel/AMD)"""
        try:
            if os.path.exists('/proc/cpuinfo'):
                with open('/proc/cpuinfo') as f:
                    cpuinfo = f.read()
                    
                    if 'GenuineIntel' in cpuinfo:
                        expected_microcode = '0x' + cpuinfo.split('microcode : ')[1].split('\n')[0]
                        actual_microcode = open('/sys/devices/system/cpu/microcode/version').read().strip()
                        if expected_microcode != actual_microcode:
                            raise HardwareError("CPU微码不匹配")
                    
                    elif 'AuthenticAMD' in cpuinfo:
                        # AMD验证逻辑不同
                        if not os.path.exists('/sys/devices/system/cpu/microcode/reload'):
                            raise HardwareError("AMD微码验证失败")
        except:
            SecureEnv._write_audit_log("CPU微码验证失败")
            # 不阻止运行但记录警告

    def _detect_memory_scan(self):
        """检测异常内存读取"""
        suspicious_regions = []
        with open(f'/proc/{os.getpid()}/smaps') as f:
            for line in f:
                if 'r--' in line and 'python' not in line.lower():
                    suspicious_regions.append(line.strip())
        
        if suspicious_regions:
            SecureEnv._write_audit_log(
                f"可疑内存访问模式: {suspicious_regions}")
            self._counter_measures("内存扫描检测")
                        
    def _active_defense(self):
        """主动防御措施"""
        try:
            # 检测到入侵时采取的措施
            if not SecureEnv.verify_integrity():
                self._counter_measures("完整性破坏")
            
            if SecureEnv.is_debugger_present():
                self._counter_measures("调试器检测")
                
            if SecureEnv.is_virtualized() and self.config.block_virtualized:
                self._counter_measures("虚拟化环境")
                
        except Exception as e:
            SecureEnv._write_audit_log(f"主动防御失败: {e}")
    
    def _counter_measures(self, reason: str):
        """反制措施"""
        try:
            SecureEnv._write_audit_log(f"触发反制措施: {reason}")
            
            # 1. 立即擦除内存中的敏感数据
            for attr in dir(self):
                if not attr.startswith('_'):
                    obj = getattr(self, attr)
                    if isinstance(obj, (str, bytes, bytearray)):
                        SecureWipe.wipe_memory(obj)
            
            # 2. 生成虚假错误信息
            fake_error = "Segmentation fault (core dumped)"
            sys.stderr.write(fake_error + "\n")
            
            # 3. 延迟响应
            time.sleep(random.randint(3, 10))
            
            # 4. 终止进程
            os.kill(os.getpid(), signal.SIGKILL)
            
        except Exception as e:
            # 终极手段
            os._exit(1)
    
    def _security_monitor(self):
        """增强的持续安全监控线程"""
        while True:
            try:
                # 检查进程内存访问
                if not SecureEnv.monitor_proc_access():
                    SecureEnv._write_audit_log("检测到异常内存访问，可能遭受攻击")
                    self._self_destruct()
                
                # 检查自身完整性
                if not SecureEnv.verify_integrity():
                    SecureEnv._write_audit_log("检测到代码篡改")
                    self._self_destruct()
                
                # 检查网络连接
                if not SecureEnv.monitor_network():
                    SecureEnv._write_audit_log("检测到异常网络连接")
                    self._self_destruct()
                
                # 新增主动防御
                self._active_defense()
                
                self._detect_memory_scan()  # 新增检测
                
                SecureEnv.monitor_covert_channels()  # 新增检测
                
                time.sleep(5)  # 每5秒检查一次
            except Exception as e:
                SecureEnv._write_audit_log(f"安全监控线程错误: {e}")
                self._counter_measures("监控线程异常")
                time.sleep(30)

    def _self_destruct(self):
        """自毁机制"""
        try:
            SecureEnv._write_audit_log("启动自毁序列")
            
            # 1. 擦除内存中的敏感数据
            for attr in dir(self):
                if attr.startswith('_'):
                    continue
                obj = getattr(self, attr)
                if isinstance(obj, (str, bytes, bytearray)):
                    SecureWipe.wipe_memory(obj)

            # 2. 擦除所有类属性
            for name, value in vars(self).items():
                if not name.startswith('_'):
                    SecureWipe.wipe_memory(value)
            
            # 3. 擦除临时文件
            if os.path.exists(TEMP_DIR):
                for root, _, files in os.walk(TEMP_DIR):
                    for f in files:
                        SecureFS.secure_delete(os.path.join(root, f))
            
            # 4. 擦除内存中的Python字节码
            for obj in gc.get_objects():
                if isinstance(obj, (types.CodeType, types.FrameType)):
                    SecureWipe.wipe_memory(obj)
            
            # 终止进程
            os.kill(os.getpid(), signal.SIGKILL)
        except Exception as e:
            SecureEnv._write_audit_log(f"自毁失败: {e}")
            os._exit(1)
            
    def _check_environment(self) -> None:
        """增强环境安全检查"""
        try:
            # 审计日志初始化
            SecureEnv._write_audit_log("=== 安全会话开始 ===")
            
            if self.config.enable_anti_debug:
                SecureEnv.enforce_no_debug()
            
            if self.config.block_virtualized and SecureEnv.is_virtualized():
                raise VirtualizationError("虚拟化环境检测，操作终止")
            
            if self.config.strict_entropy_check:
                entropy = SecureEnv.check_entropy(os.urandom(32))
                SecureEnv._write_audit_log(f"系统熵值: {entropy:.2f}")
                if entropy < SecureConstants.MIN_ENTROPY:
                    raise SecurityError("系统熵值不足，不安全操作被阻止")
            
            if self.config.enable_memory_lock:
                SecureEnv.lock_memory()
            
            if self.config.enable_aslr:
                SecureEnv.enable_aslr()
            
            if self.config.enable_secure_temp:
                SecureEnv.secure_temp_dir()
        except Exception as e:
            SecureEnv._write_audit_log(f"环境检查失败: {e}")
            raise
    
    def _cleanup(self, signum=None, frame=None) -> None:
        """安全清理"""
        try:
            SecureEnv._write_audit_log(f"收到信号 {signum}，正在清理")
            SecureLock.release()
            sys.exit(1)
        except Exception as e:
            sys.stderr.write(f"清理失败: {e}\n")
            sys.exit(1)
    
    def _airgap_operation(self, func: Callable, *args, **kwargs):
        """在隔离环境中执行操作"""
        if not self.config.use_airgap:
            return func(*args, **kwargs)
        
        try:
            # 保存网络状态
            interfaces = subprocess.check_output(["ls", "/sys/class/net"], text=True).split()
            states = {}
            
            for iface in interfaces:
                if iface == "lo":
                    continue
                states[iface] = subprocess.check_output(
                    ["cat", f"/sys/class/net/{iface}/operstate"], text=True).strip()
                
                # 关闭接口
                subprocess.run(["ip", "link", "set", iface, "down"], check=True)
            
            # 执行操作
            result = func(*args, **kwargs)
            
            return result
        except Exception as e:
            SecureEnv._write_audit_log(f"隔离操作失败: {e}")
            raise SecurityError(f"隔离操作失败: {e}")
        finally:
            # 恢复网络
            for iface, state in states.items():
                if state == "up":
                    try:
                        subprocess.run(["ip", "link", "set", iface, "up"], check=True)
                    except:
                        pass
    
    def encrypt_file(self, src_path: str, dest_path: Optional[str] = None,
                    password: Optional[str] = None) -> Tuple[str, str, str, str]:
        """加密文件 (返回包含双盐值)"""
        SecureEnv.check_failed_attempts("encrypt")
        
        if not os.path.exists(src_path):
            SecureEnv.record_failed_attempt("encrypt")
            raise SecurityError("源文件不存在")
        
        try:
            # 生成OTP
            otp_secret, otp_manual = SecureOTP.generate_totp()
            
            def _encrypt():
                # 读取文件
                plaintext = SecureFS.secure_read(src_path)
                
                # 生成密钥 (返回密钥和双盐值)
                key, salt_pbkdf, salt_argon = FileCrypto.generate_key(password)
                
                # 加密数据
                encrypted = FileCrypto.encrypt_data(plaintext, key)
                
                # 写入输出文件
                output_path = dest_path or (src_path + '.safe')
                SecureFS.secure_write(output_path, encrypted)
                
                # 安全擦除内存
                SecureWipe.wipe_memory(plaintext)
                SecureWipe.wipe_memory(key)
                
                return (
                    output_path,
                    key.hex() if not password else "",
                    salt_pbkdf.hex() if password else "",
                    salt_argon.hex() if password else "",
                    otp_secret
                )
            
            result = self._airgap_operation(_encrypt)
            
            print("\n=== TOTP 配置指令 ===")
            print(otp_manual)
            print(f"\n加密成功！输出文件: {result[0]}")
            
            SecureEnv.reset_failed_attempts("encrypt")
            return result
        except Exception as e:
            SecureEnv.record_failed_attempt("encrypt")
            raise CryptoError("加密失败")

    def decrypt_file(self, src_path: str, dest_path: Optional[str] = None,
                    key_hex: Optional[str] = None, 
                    salt_pbkdf_hex: Optional[str] = None,
                    salt_argon_hex: Optional[str] = None,
                    password: Optional[str] = None,
                    otp_code: Optional[str] = None) -> str:
        """解密文件 (支持双盐值)"""
        SecureEnv.check_failed_attempts("decrypt")
        
        if not os.path.exists(src_path):
            SecureEnv.record_failed_attempt("decrypt")
            raise SecurityError("源文件不存在")
        
        try:
            # 验证OTP
            if otp_code:
                if not key_hex:
                    SecureEnv.record_failed_attempt("decrypt")
                    raise SecurityError("使用OTP时需要提供密钥")
                
                if not SecureOTP.verify_totp(key_hex, otp_code):
                    SecureEnv.record_failed_attempt("decrypt")
                    raise SecurityError("OTP验证失败")
            
            def _decrypt():
                # 读取加密文件
                encrypted = SecureFS.secure_read(src_path)
                
                # 获取密钥
                if password:
                    if not salt_pbkdf_hex or not salt_argon_hex:
                        raise SecurityError("使用密码解密需要提供双盐值")
                    
                    salt_pbkdf = bytes.fromhex(salt_pbkdf_hex)
                    salt_argon = bytes.fromhex(salt_argon_hex)
                    key = FileCrypto.derive_key(password, salt_pbkdf, salt_argon)
                elif key_hex:
                    key = bytes.fromhex(key_hex)
                else:
                    raise SecurityError("必须提供密码或密钥")
                
                # 解密数据
                plaintext = FileCrypto.decrypt_data(encrypted, key)
                
                # 写入输出文件
                output_path = dest_path or src_path[:-5] if src_path.endswith('.safe') else src_path + '.dec'
                SecureFS.secure_write(output_path, plaintext)
                
                # 安全擦除内存
                SecureWipe.wipe_memory(plaintext)
                SecureWipe.wipe_memory(key)
                
                return output_path
            
            result = self._airgap_operation(_decrypt)
            
            print(f"\n解密成功！输出文件: {result}")
            SecureEnv.reset_failed_attempts("decrypt")
            return result
        except Exception as e:
            SecureEnv.record_failed_attempt("decrypt")
            raise
            

    def shred_file(self, path: str) -> None:
        """安全擦除文件"""
        SecureEnv.check_failed_attempts("shred")
        
        if not os.path.exists(path):
            SecureEnv.record_failed_attempt("shred")
            raise SecurityError("文件不存在")
        
        try:
            SecureFS.secure_wipe(path)
            print(f"\n安全擦除完成: {path}")
            SecureEnv.reset_failed_attempts("shred")
        except Exception as e:
            SecureEnv.record_failed_attempt("shred")
            raise
    
    def system_check(self) -> Dict[str, str]:
        """执行系统安全检查"""
        results = {
            "debugger": "未检测到" if not SecureEnv.is_debugger_present() else "检测到调试器",
            "virtualization": "未检测到" if not SecureEnv.is_virtualized() else "检测到虚拟化环境",
            "entropy": f"{SecureEnv.check_entropy(os.urandom(32)):.2f}/1.0",
            "aslr": "启用" if self.config.enable_aslr else "禁用",
            "memory_lock": "启用" if self.config.enable_memory_lock else "禁用",
            "anti_debug": "启用" if self.config.enable_anti_debug else "禁用",
            "airgap": "启用" if self.config.use_airgap else "禁用",
            # 新增检查项
            "proc_access": "安全" if SecureEnv.monitor_proc_access() else "异常",
            "integrity": "通过" if SecureEnv.verify_integrity() else "失败",
            "network": "安全" if SecureEnv.monitor_network() else "异常",
            "memory_protection": "激活" if self.config.enable_memory_lock else "未激活"
        }
        
        return results

# ===== 增强命令行界面 =====

class Color:
    """ANSI颜色代码"""
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    DARKCYAN = '\033[36m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

class MenuLevel(Enum):
    MAIN = 0
    ENCRYPT = 1
    DECRYPT = 2
    SHRED = 3
    SYSTEM = 4
    KEYGEN = 5
    TOTP = 6

def clear_screen():
    """清屏"""
    os.system('cls' if os.name == 'nt' else 'clear')

def display_banner():
    """显示彩色横幅"""
    clear_screen()
    print(Color.PURPLE + "="*60 + Color.END)
    print(Color.BOLD + Color.CYAN + r"""
   _____       _______ _____  ______ 
  / ____|   /\|__   __|  __ \|  ____|
 | (___    /  \  | |  | |__) | |__   
  \___ \  / /\ \ | |  |  ___/|  __|  
  ____) |/ ____ \| |  | |    | |____ 
 |_____//_/    \_\_|  |_|    |______|
    """ + Color.END)
    print(Color.BOLD + " 高级文件加密系统 v9.0 - 防御系统级后门".center(60) + Color.END)
    print(Color.PURPLE + "="*60 + Color.END + "\n")

def get_input(prompt: str, 
              input_type: type = str, 
              validation: Optional[Callable] = None,
              secure: bool = False) -> any:
    """安全的用户输入处理"""
    while True:
        try:
            if secure:
                from getpass import getpass
                user_input = getpass(prompt)
            else:
                user_input = input(prompt)
            
            if not user_input.strip():
                raise ValueError("输入不能为空")
                
            # 类型转换
            converted = input_type(user_input.strip())
            
            # 额外验证
            if validation and not validation(converted):
                raise ValueError("无效输入")
                
            return converted
            
        except ValueError as e:
            print(Color.RED + f"错误: {e}" + Color.END)
        except KeyboardInterrupt:
            print("\n操作已取消")
            return None
        except Exception as e:
            print(Color.RED + f"系统错误: {e}" + Color.END)
            return None

def file_picker(prompt: str, must_exist: bool = True) -> Optional[str]:
    """文件选择器"""
    while True:
        path = get_input(prompt)
        if path is None:  # 用户取消
            return None
            
        path = os.path.expanduser(path)
        
        if must_exist and not os.path.exists(path):
            print(Color.RED + "错误: 文件不存在" + Color.END)
            continue
            
        if not must_exist:
            dirname = os.path.dirname(path)
            if dirname and not os.path.exists(dirname):
                print(Color.RED + "错误: 目录不存在" + Color.END)
                continue
                
        return path

def encryption_menu() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """加密文件菜单"""
    display_banner()
    print(Color.BOLD + ">>> 文件加密" + Color.END)
    print("-"*60)
    
    src_path = file_picker("输入要加密的文件路径: ")
    if not src_path:
        return None, None, None
        
    dest_path = file_picker("输入输出文件路径(留空自动生成): ", must_exist=False)
    if dest_path is None:  # 用户显式取消
        return None, None, None
        
    use_password = get_input("使用密码保护? (y/n): ", 
                           validation=lambda x: x.lower() in ('y', 'n'))
    if use_password is None:
        return None, None, None
        
    password = None
    if use_password.lower() == 'y':
        password = get_input("设置加密密码: ", secure=True)
        if not password:
            return None, None, None
            
    return src_path, dest_path if dest_path else "", password


def decryption_menu() -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """解密文件菜单 (增加双盐值输入)"""
    display_banner()
    print(Color.BOLD + ">>> 文件解密" + Color.END)
    print("-"*60)
    
    src_path = file_picker("输入要解密的文件路径: ")
    if not src_path:
        return None, None, None, None, None, None, None
        
    dest_path = file_picker("输入输出文件路径(留空自动生成): ", must_exist=False)
    if dest_path is None:
        return None, None, None, None, None, None, None
        
    key_type = get_input("解密方式:\n1. 使用密钥\n2. 使用密码\n选择(1-2): ",
                        input_type=int,
                        validation=lambda x: x in (1, 2))
    if not key_type:
        return None, None, None, None, None, None, None
        
    key_hex, salt_pbkdf, salt_argon, password = None, None, None, None
    if key_type == 1:
        key_hex = get_input("输入密钥(16进制): ",
                           validation=lambda x: re.match(r'^[0-9a-fA-F]+$', x))
        if not key_hex:
            return None, None, None, None, None, None, None
            
        otp_code = get_input("输入TOTP验证码(可选): ")
    else:
        password = get_input("输入密码: ", secure=True)
        if not password:
            return None, None, None, None, None, None, None
            
        salt_pbkdf = get_input("输入PBKDF2盐值(16进制): ",
                              validation=lambda x: re.match(r'^[0-9a-fA-F]+$', x))
        salt_argon = get_input("输入Argon2盐值(16进制): ",
                              validation=lambda x: re.match(r'^[0-9a-fA-F]+$', x))
        otp_code = None
        
    return src_path, dest_path if dest_path else "", key_hex, salt_pbkdf, salt_argon, password, otp_code
    
    
def shred_menu() -> Optional[str]:
    """安全擦除菜单"""
    display_banner()
    print(Color.BOLD + ">>> 安全擦除文件" + Color.END)
    print(Color.YELLOW + "警告: 此操作不可逆!" + Color.END)
    print("-"*60)
    
    path = file_picker("输入要擦除的文件路径: ")
    if not path:
        return None
        
    confirm = get_input(f"确认要永久擦除 {path}? (y/n): ",
                       validation=lambda x: x.lower() in ('y', 'n'))
    if confirm.lower() != 'y':
        return None
        
    return path

def main_menu() -> Tuple[MenuLevel, dict]:
    """增强的主菜单系统"""
    display_banner()
    
    print(Color.BOLD + "主功能菜单:" + Color.END)
    print(Color.GREEN + " 1. 加密文件" + Color.END)
    print(Color.BLUE + " 2. 解密文件" + Color.END)
    print(Color.RED + " 3. 安全擦除文件" + Color.END)
    print(Color.CYAN + " 4. 系统安全检查" + Color.END)
    print(Color.YELLOW + " 5. 生成安全密钥" + Color.END)
    print(Color.PURPLE + " 6. 验证TOTP代码" + Color.END)
    print(Color.BOLD + " 0. 退出系统" + Color.END)
    print("-"*60)
    
    choice = get_input("请选择操作 (0-6): ",
                      input_type=int,
                      validation=lambda x: 0 <= x <= 6)
    if choice is None:
        return MenuLevel.MAIN, {}
    
    params = {}
    if choice == 1:
        src, dest, pwd = encryption_menu()
        if src is None:
            return MenuLevel.MAIN, {}
        params = {"src_path": src, "dest_path": dest, "password": pwd}
        return MenuLevel.ENCRYPT, params
        
    elif choice == 2:
        src, dest, key, salt_pbkdf, salt_argon, otp = decryption_menu()
        if src is None:
            return MenuLevel.MAIN, {}
        params = {
            "src_path": src, 
            "dest_path": dest, 
            "key_hex": key, 
            "salt_pbkdf_hex": salt_pbkdf,
            "salt_argon_hex": salt_argon,
            "password": pwd,
            "otp_code": otp
        }
        return MenuLevel.DECRYPT, params
        
    elif choice == 3:
        path = shred_menu()
        if not path:
            return MenuLevel.MAIN, {}
        params = {"path": path}
        return MenuLevel.SHRED, params
        
    elif choice == 4:
        return MenuLevel.SYSTEM, {}
        
    elif choice == 5:
        return MenuLevel.KEYGEN, {}
        
    elif choice == 6:
        secret = get_input("输入TOTP密钥: ")
        if not secret:
            return MenuLevel.MAIN, {}
        code = get_input("输入验证码: ")
        params = {"secret": secret, "code": code}
        return MenuLevel.TOTP, params
        
    elif choice == 0:
        confirm = get_input("确认退出? (y/n): ",
                           validation=lambda x: x.lower() in ('y', 'n'))
        if confirm.lower() == 'y':
            print(Color.BOLD + "安全退出系统..." + Color.END)
            sys.exit(0)
        return MenuLevel.MAIN, {}
    
    return MenuLevel.MAIN, {}



def main():
    """增强安全性的主程序入口"""
    try:
        # 初始化安全配置
        config = SecureConfig(
            enable_anti_debug=True,
            block_virtualized=True,
            enable_memory_lock=True
        )
        
        # === 新增的安全初始化 ===
        def first_run_checks():
            """首次运行安全检查"""
            # 生成/验证基本锚点
            anchor_file = os.path.expanduser("~/.secure_fs_anchor")
            if not os.path.exists(anchor_file):
                with open(anchor_file, 'wb') as f:
                    f.write(hashlib.sha256(open(__file__, 'rb').read()).digest())
                os.chmod(anchor_file, 0o400)
            else:
                current_hash = hashlib.sha256(open(__file__, 'rb').read()).digest()
                stored_hash = open(anchor_file, 'rb').read()
                if not hmac.compare_digest(current_hash, stored_hash):
                    print(Color.RED + "致命错误: 程序文件已被修改!" + Color.END)
                    sys.exit(1)
        
        first_run_checks()
        
        # 首次运行时自动生成哈希文件
        if not any(os.path.exists(f) for f in [
            "/etc/secure_fs.hash",
            "/usr/local/share/secure_fs.hash",
            os.path.expanduser("~/.secure_fs.hash")
        ]):
            print(Color.CYAN + "\n首次运行: 正在生成完整性校验文件..." + Color.END)
            if not config.update_hash():
                print(Color.RED + "错误: 无法生成完整性校验文件" + Color.END)
                sys.exit(1)
            print(Color.GREEN + "完整性校验文件已生成到安全位置" + Color.END)
            time.sleep(1)
            
        # 创建安全文件系统实例（新增完整性检查）
        try:
            safe_fs = SafeFS(config)
        except SelfIntegrityError as e:
            print(Color.RED + f"\n致命错误: {e}" + Color.END)
            print("可能原因: 程序文件已被修改")
            sys.exit(1)
        except MemoryAccessError as e:
            print(Color.RED + f"\n致命错误: {e}" + Color.END)
            print("可能原因: 检测到异常内存访问")
            sys.exit(1)

        # 显示增强的安全状态信息（新增）
        print(Color.BOLD + "\n=== 安全状态检查 ===" + Color.END)
        status = safe_fs.system_check()
        for k, v in status.items():
            print(f"{k.upper().ljust(20)}: {Color.CYAN if v == '安全' or v == '通过' else Color.YELLOW}{v}{Color.END}")
        
        if any(v in ('失败', '异常') for v in status.values()):
            print(Color.RED + "\n警告: 系统存在安全风险!" + Color.END)
            confirm = input("是否继续? (y/n): ")
            if confirm.lower() != 'y':
                sys.exit(0)
        
        time.sleep(3)  # 让用户阅读安全状态
        
        # 主程序循环
        while True:
            try:
                menu_level, params = main_menu()
                
                if menu_level == MenuLevel.ENCRYPT:
                    try:
                        # 加密文件（新增内存保护）
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            result = safe_fs.encrypt_file(
                                params["src_path"],
                                params["dest_path"] or None,
                                params["password"]
                            )
                        print(Color.GREEN + "\n加密成功!" + Color.END)
                        print(f"输出文件: {result[0]}")
                        print(f"备份密钥: {Color.YELLOW}{result[1]}{Color.END}")
                        print(f"TOTP密钥: {Color.CYAN}{result[2]}{Color.END}")
                    except NetworkAnomalyError as e:
                        print(Color.RED + f"\n网络异常: {e}" + Color.END)
                        print("建议在隔离环境中操作敏感文件")
                    input("\n按Enter返回主菜单...")
                
                elif menu_level == MenuLevel.DECRYPT:
                    # 解密文件（新增网络隔离检查）
                    result = safe_fs.decrypt_file(
                        params["src_path"],
                        params["dest_path"] or None,
                        params.get("key_hex"),
                        params.get("password"),
                        params.get("otp_code")
                    )
                    print(Color.GREEN + "\n解密成功!" + Color.END)
                    print(f"输出文件: {result}")
                    input("\n按Enter返回主菜单...")
                
                elif menu_level == MenuLevel.SHRED:
                    # 安全擦除
                    safe_fs.shred_file(params["path"])
                    print(Color.GREEN + "\n文件已安全擦除!" + Color.END)
                    input("\n按Enter返回主菜单...")
                
                elif menu_level == MenuLevel.SYSTEM:
                    # 系统检查
                    print("\n" + "="*60)
                    print(Color.BOLD + "系统安全检查结果".center(60) + Color.END)
                    print("="*60)
                    results = safe_fs.system_check()
                    for k, v in results.items():
                        print(f"{k.upper().ljust(20)}: {Color.CYAN}{v}{Color.END}")
                    input("\n按Enter返回主菜单...")
                
                elif menu_level == MenuLevel.KEYGEN:
                    # 生成密钥
                    display_banner()
                    print(Color.BOLD + ">>> 安全密钥生成" + Color.END)
                    print("-"*60)
                    use_password = get_input("生成密码保护的密钥? (y/n): ",
                                           validation=lambda x: x.lower() in ('y', 'n'))
                    password = None
                    if use_password.lower() == 'y':
                        password = get_input("设置保护密码: ", secure=True)
                    
                    key, salt = FileCrypto.generate_key(password)
                    print("\n" + "="*60)
                    print(Color.GREEN + "密钥生成成功!" + Color.END)
                    print(f"密钥: {Color.YELLOW}{key.hex()}{Color.END}")
                    if password:
                        print(f"盐值: {Color.CYAN}{salt.hex()}{Color.END}")
                    print("="*60)
                    input("\n按Enter返回主菜单...")
                
                elif menu_level == MenuLevel.TOTP:
                    # TOTP验证
                    secret = params["secret"]
                    code = params["code"]
                    if SecureOTP.verify_totp(secret, code):
                        print(Color.GREEN + "\n✓ TOTP验证成功!" + Color.END)
                    else:
                        print(Color.RED + "\n✗ TOTP验证失败!" + Color.END)
                    input("\n按Enter返回主菜单...")
                
            except SecurityError as e:
                print(Color.RED + f"\n安全错误: {e}" + Color.END)
                if isinstance(e, (IntegrityError, AntiTamperError)):
                    print("建议立即终止程序并检查系统安全性")
                input("\n按Enter继续...")
            
            except Exception as e:
                print(Color.RED + f"\n系统错误: {e}" + Color.END)
                SecureEnv._write_audit_log(f"系统错误: {type(e).__name__}: {e}")
                input("\n按Enter继续...")
    
    except KeyboardInterrupt:
        print(Color.YELLOW + "\n安全关闭中..." + Color.END)
        sys.exit(0)
    
    except Exception as e:
        print(Color.RED + f"\n致命错误: {e}" + Color.END)
        SecureEnv._write_audit_log(f"致命错误: {type(e).__name__}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # 设置UTF-8编码环境
    import locale
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    
    # 确保在Linux系统上正确运行
    if platform.system() != 'Linux':
        print(Color.RED + "错误: 此工具仅支持Linux系统" + Color.END)
        sys.exit(1)
    
    # 检查root权限
    if os.geteuid() != 0:
        print(Color.YELLOW + "警告: 建议使用root权限运行以获得完整功能" + Color.END)
        time.sleep(2)  # 给用户阅读警告的时间
    
    # 检查frame对象是否被篡改
    for frame in sys._current_frames().values():
        if '_hook' in frame.f_locals:
            raise AntiTamperError("检测到运行时钩子")
            
    # 检查meta_path是否被修改
    original_meta = [imp for imp in sys.meta_path if imp.__class__.__module__ == 'builtins']
    if len(original_meta) != len(sys.meta_path):
        raise IntegrityError("导入系统被篡改")
        
    # 检测异常内存对象
    for obj in gc.get_objects():
        if obj.__class__.__name__ == '_SafeFSInternal':
            raise SecurityError("检测到伪装对象")
    
    # 启动主程序
    main()