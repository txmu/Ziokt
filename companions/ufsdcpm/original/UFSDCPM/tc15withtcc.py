class TC15_CPU:
    """
    TC-15 CPU 模拟器 - 修复版
    一个完全图灵完备的8位CPU架构
    
    架构规范:
    - 8位数据总线
    - 16位地址总线(64KB内存空间)
    - 16个8位通用寄存器(R0-R15)
    - 1个程序计数器(PC)
    - 1个16位栈指针（SP）
    - 1个状态寄存器(FLAGS)
    - 很多条指令
    """
    
    def __init__(self, memory_size=65536, debug=False):
        # 寄存器
        self.registers = [0] * 16 # R0-R15
        self.reg_pairs = {  # 新增寄存器对定义
            'RR0': (0, 1),  # R0+R1组成16位RR0
            'RR2': (2, 3),  # R2+R3组成RR2
            'RR4': (4, 5),  # 最多支持8个16位寄存器对
            'RR6': (6, 7),  # 请自行管理寄存器对与寄存器的混合使用
            'RR8': (8, 9),
            'RR10': (10, 11),
            'RR12': (12, 13),
            'RR14': (14, 15)
}
        self.pc = 0      # 程序计数器
        self.sp = memory_size - 1 # 栈指针 (16位)初始化为内存顶部-1
        
        # 新FLAGS寄存器格式 (8位):
        # [ MODE(2位) | P(奇偶) | H(半进位) | I(中断使能) | T(陷阱) | O(溢出) | S(符号) | C(进位) | Z(零) ]
        # 模式定义:
        # 00 = 标准模式 (默认)
        # 01 = BCD运算模式
        # 10 = 调试模式
        # 11 = 保留
        self.flags = 0b00000000  # 初始所有标志位清零
        
        # 标志位掩码常量
        self.FLAG_Z = 0b00000001  # 零标志
        self.FLAG_C = 0b00000010  # 进位标志
        self.FLAG_S = 0b00000100  # 符号标志
        self.FLAG_O = 0b00001000  # 溢出标志
        self.FLAG_T = 0b00010000  # 陷阱标志
        self.FLAG_I = 0b00100000  # 中断使能
        self.FLAG_H = 0b01000000  # 半进位标志
        self.FLAG_P = 0b10000000  # 奇偶标志
        self.MODE_MASK = 0b11000000  # 模式位掩码
        
        # 内存
        self.memory = [0] * memory_size
        
        """完全不冲突的扩展指令空间（推荐使用）
        （1）0xE0-0xEF（最佳选择）：RET 无操作数，所有 0xEx 均无冲突。        
        （2）0x10-0x1F（已占用，但无冲突）：当前已用，可继续扩展（如 0x1E、0x1F 未被占用时）。      
        （3）0x20、0x30、0x40……0xF0（低 4 位=0）：这些操作码的基本指令解释无意义，可安全使用"""
        
        # 指令集 - 修复键值映射
        self.instructions = {
            0x0: self._halt,    # HALT
            0x1: self._load,    # LOAD
            0x2: self._store,   # STORE
            0x3: self._mov,     # MOV - 确保这个映射存在
            0x4: self._add,     # ADD
            0x5: self._sub,     # SUB
            0x6: self._and,     # AND
            0x7: self._or,      # OR
            0x8: self._xor,     # XOR
            0x9: self._not,     # NOT
            0xA: self._jmp,     # JMP
            0xB: self._jz,      # JZ
            0xC: self._jc,      # JC
            0xD: self._call,    # CALL
            0xE: self._ret,     # RET
            0xF: self._inc,     # INC
            # 新增指令 - 使用不同的编码方式
            0x10: self._swap,   # SWAP
            0x11: self._loadi,  # LOADI
            0x12: self._push,   # PUSH
            0x13: self._pop,    # POP
            0x14: self._loadx,    # LOADX Rd, [Ra] (任意Ra)
            0x15: self._storex,   # STOREX [Ra], Rs (任意Ra)
            0x16: self._movi,  # MOVI Rd, imm
            0x17: self._mov_mem,  # MOV_MEM
            0x18: self._shl,    # SHL
            0x19: self._shr,    # SHR
            0x1A: self._load16,    # LOAD16
            0x1B: self._reti,      # 新增中断返回指令RETI
            0x1C: self._set_mode,  # 设置模式SETMODE
            0x1D: self._set_flag,  # 设置标志位SETFLAG
            0x1E: self._clr_flag,  # 清除标志位
            0x1F: self._bcd_add,   # BCD加法BCDADD
            0x20: self._syscalls,  # 注册 SYSS 指令
            0x30: self._syscall,  # 注册 SYS 指令
            0xE0: self._movx,  # MOVX指令
            0xE1: self._parity,  #PARITY
            0xE2: self._jp,  # JP
            0xE3: self._jo,  # JO
            0xE4: self._js,  # JS
            0xE5: self._sex,  # SEX
           ## 0xE6: self._into,  # INTO（溢出中断指令，尚未实现）
        }
        
        # I/O设备映射
        self.io_devices = {
            0xFF00: {'type': 'stdout', 'buffer': []},      # 标准字符输出
            0xFF01: {'type': 'stdout_hex', 'buffer': []},  # 十六进制输出（注：buffer 必须为列表，存储 0-255 的整数字节）
            0xFF02: {'type': 'stdout_dec', 'buffer': []},  # 十进制输出
            0xFF03: {'type': 'keyboard', 'buffer': []},    # 键盘输入
            0xFF04: {'type': 'gpio', 'state': 0x00},      # 通用IO
            0xFF05: {'type': 'timer', 'value': 0},        # 计时器
            0xFF06: {'type': 'graphics', 'buffer': []},
            0xFF07: {'type': 'sound', 'registers': [0]*4}
        }
        
        # 中断向量表 (扩展功能)
        self.interrupt_vectors = {
            0x01: {'type': 'KEYBOARD', 'handler_addr': 0x1000},
            0x02: {'type': 'TIMER', 'handler_addr': 0x2000},
            0x80: {'type': 'TRAP', 'handler_addr': 0x8000}  # 新增调试陷阱
        }
        
        # 运行状态
        self.running = False
        self.debug = debug
    
    def reset(self):
        """重置CPU状态"""
        self.registers = [0] * 8
        self.pc = 0
        self.flags = 0
        self.running = False
    
    def load_program(self, program, start_address=0):
        """将程序加载到内存中"""
        for i, byte in enumerate(program):
            if start_address + i < len(self.memory):
                self.memory[start_address + i] = byte & 0xFF
    
    def fetch(self):
        """取指令"""
        if self.pc >= len(self.memory):
            self.running = False
            return 0
        opcode = self.memory[self.pc]
        self.pc += 1
        return opcode
    
    def fetch_byte(self):
        """取下一个字节（用于立即数）"""
        if self.pc >= len(self.memory):
            return 0
        byte = self.memory[self.pc]
        self.pc += 1
        return byte
        
    def fetch_16bit_operand(self):
        """获取16位操作数(用于立即数)"""
        low = self.fetch_byte()
        high = self.fetch_byte()
        return (high << 8) | low
    
    def decode_execute(self, opcode):
        """解码并执行指令，支持无限扩展指令 - 修复版"""
        # 首先检查是否是扩展指令（操作码在扩展指令集中）
        if opcode in self.instructions and opcode >= 0x10:
            # 扩展指令：整个opcode作为指令码
            instr = opcode
            operand = self.fetch_byte()  # 操作数在下一字节
            if self.debug:
                print(f"扩展指令: 0x{instr:X}, 操作数: 0x{operand:X}")
        else:
            # 基本指令：高4位是指令类型，低4位是操作数
            # 特殊处理RET
            if opcode == 0xE:  # 单字节RET
                self._ret(0)
                return
            instr = (opcode >> 4) & 0xF
            operand = opcode & 0xF
            if self.debug:
                print(f"基本指令: 0x{instr:X}, 操作数: 0x{operand:X}")
       # 特殊处理：STORE和LOAD指令使用不同的操作数格式
        if instr in [0x1, 0x2]:  # LOAD或STORE指令
            # 新格式：低3位是寄存器索引，bit3是地址寄存器选择
            reg = operand & 0x7
            addr_reg_sel = (operand >> 3) & 0x1
            # 使用R0或R1作为地址寄存器
            addr_reg = addr_reg_sel
            
            if self.debug:
                if instr == 0x1:
                    print(f"LOAD R{reg}, [R{addr_reg}]")
                else:
                    print(f"STORE [R{addr_reg}], R{reg}")
            
            if instr == 0x1:  # LOAD
                self._load((addr_reg << 3) | reg)
            else:  # STORE
                self._store((addr_reg << 3) | reg)
        # 动态检查指令是否存在
        elif instr in self.instructions:
            if self.debug:
                print(f"执行指令: {self.instructions[instr].__name__}")
            self.instructions[instr](operand)
        else:
            print(f"可用指令: {list(self.instructions.keys())}")
            raise ValueError(f"未知指令: 0x{instr:X} (原始字节: 0x{opcode:02X})")
        
    def run(self, start_address=0, max_cycles=10000):
        """运行程序"""
        self.pc = start_address
        self.running = True
        cycles = 0
        
        if self.debug:
            print(f"开始执行，PC={start_address}")
            print(f"初始寄存器状态: {self.registers}")
        
        while self.running and cycles < max_cycles:
            if self.debug:
                print(f"\n周期 {cycles}: PC={self.pc}")
            opcode = self.fetch()
            if self.debug:
                print(f"取指: 0x{opcode:02X}")
            self.decode_execute(opcode)
            cycles += 1
            
            if self.debug and cycles < 10:  # 只显示前几个周期的详细信息
                print(f"寄存器状态: {self.registers}")
            
        if cycles >= max_cycles:
            print(f"警告: 程序运行超过{max_cycles}个周期，可能陷入无限循环")
            
    def update_flags(self, result):
        """更新所有状态标志位"""
        result_byte = result & 0xFF
        
        # 标准标志位 (所有模式下都更新)
        new_flags = 0
        new_flags |= (1 if result_byte == 0 else 0) << 0  # Z
        new_flags |= (1 if (result_byte & 0x80) else 0) << 2  # S
        new_flags |= self.flags & self.FLAG_C  # 保留原有进位标志
        
        # 模式相关标志位
        current_mode = self.flags & self.MODE_MASK
        if current_mode == 0b00000000:  # 标准模式
            # 计算溢出标志 (有符号运算)
            new_flags |= (self.flags & self.FLAG_O)
            
            # 计算奇偶标志
            ones = bin(result_byte).count('1')
            new_flags |= (1 if ones % 2 == 0 else 0) << 7  # P
            
        elif current_mode == 0b01000000:  # BCD模式
            # 保留半进位标志
            new_flags |= (self.flags & self.FLAG_H)
            
        # 保持模式位和中断使能/陷阱标志不变
        new_flags |= (self.flags & (self.MODE_MASK | self.FLAG_I | self.FLAG_T))
        
        self.flags = new_flags
            
    # 指令实现
    def _halt(self, _):
        """停止执行"""
        if self.debug:
            print("HALT - 停止执行")
        self.running = False
    
            
    # 指令实现修复
    def _load(self, operand):
        """从内存加载到寄存器: LOAD Rdst, [Raddr]"""
        dst_reg = operand & 0x7  # 低3位是目标寄存器
        addr_reg = (operand >> 3) & 0x7  # 高3位是地址寄存器
        addr = self.registers[addr_reg]
        if addr < len(self.memory):
            self.registers[dst_reg] = self.memory[addr]
        self.update_flags(self.registers[dst_reg])
        if self.debug:
            print(f"LOAD R{dst_reg}, [R{addr_reg}] -> {self.registers[dst_reg]}")

    def _store(self, operand):
        """存储寄存器到内存: STORE [Raddr], Rsrc"""
        src_reg = operand & 0x7  # 低3位是源寄存器
        addr_reg = (operand >> 3) & 0x7  # 高3位是地址寄存器
        addr = self.registers[addr_reg]
        if addr < len(self.memory):
            self.memory[addr] = self.registers[src_reg]
        if self.debug:
            print(f"STORE [R{addr_reg}], R{src_reg} (值: {self.registers[src_reg]})")
    
   
    def _loadx(self, operand):
        """扩展加载指令：LOADX Rd, [Ra] 
        操作数格式：单字节编码
        - 高4位：地址寄存器Ra (0-7)
        - 低4位：目标寄存器Rd (0-7)
        """
        addr_reg = (operand >> 4) & 0x07  # 高4位：地址寄存器
        dst_reg = operand & 0x07          # 低4位：目标寄存器
        
        addr = self.registers[addr_reg]
        if addr < len(self.memory):
            self.registers[dst_reg] = self.memory[addr]
        else:
            self.registers[dst_reg] = 0  # 越界处理
        
        self.update_flags(self.registers[dst_reg])
        
        if self.debug:
            print(f"LOADX R{dst_reg}, [R{addr_reg}] (addr=0x{addr:04X}) -> {self.registers[dst_reg]}")
        
    def _storex(self, operand):
        """扩展存储指令：STOREX [Ra], Rs 
        操作数格式：单字节编码
        - 高4位：地址寄存器Ra (0-7)
        - 低4位：源寄存器Rs (0-7)
        """
        addr_reg = (operand >> 4) & 0x07  # 高4位：地址寄存器
        src_reg = operand & 0x07          # 低4位：源寄存器
        if addr_reg >= len(self.memory):  # 新增边界检查
            raise ValueError("内存地址越界")
        
        addr = self.registers[addr_reg]
        if addr < len(self.memory):
            self.memory[addr] = self.registers[src_reg]
        
        if self.debug:
            print(f"STOREX [R{addr_reg}], R{src_reg} (addr=0x{addr:04X}, value={self.registers[src_reg]})")
    
            
    def _mov(self, operand):
        """寄存器间移动: MOV Rdst, Rsrc"""
        src_reg = operand & 0x7  # 低3位是源寄存器
        dst_reg = (operand >> 3) & 0x7  # 高3位是目标寄存器
        old_value = self.registers[dst_reg]
        self.registers[dst_reg] = self.registers[src_reg]
        self.update_flags(self.registers[dst_reg])
        if self.debug:
            print(f"MOV R{dst_reg}, R{src_reg}: {old_value} -> {self.registers[dst_reg]}")

    def _movi(self, operand):
        """立即数移动: MOVI Rd, imm8
        操作数格式：
        - 第一个字节：目标寄存器编号 (低3位)
        - 第二个字节：立即数值
        """
        dst_reg = operand & 0x07  # 从操作数获取目标寄存器
        imm = self.fetch_byte()   # 获取下一个字节作为立即数
        self.registers[dst_reg] = imm
        self.update_flags(imm)
        
        if self.debug:
            print(f"MOVI R{dst_reg}, {imm} (0x{imm:02X})")
            
    def _mov_mem(self, operand):
        """内存移动指令: 
        MOV_MEM [Rd], Rs 或 MOV_MEM Rd, [Rs]
        操作数格式 (1字节):
        - bit7: 模式 (0=寄存器→内存, 1=内存→寄存器)
        - bit3-6: 寄存器Rd (目标)
        - bit0-2: 寄存器Rs (源)
        """
        mode = (operand >> 7) & 0x01 # 0:存储到内存, 1:从内存加载
        dst_reg = (operand >> 3) & 0x07
        src_reg = operand & 0x07
        
        if mode == 0:  # 存储到内存: [dst_reg] = src_reg。模式0: MOV_MEM [Rd], Rs (存储到内存)
            addr = self.registers[dst_reg]
            if addr >= len(self.memory) or addr < 0:
                raise MemoryError("内存写入越界")
            value = self.registers[src_reg]
            self.memory[addr] = value
        else:  # 从内存加载: dst_reg = [src_reg]。模式1: MOV_MEM Rd, [Rs] (从内存加载)
            addr = self.registers[src_reg]  # 使用src_reg的值作为地址
            if addr >= len(self.memory) or addr < 0:
                raise MemoryError("内存写入越界")
            self.registers[dst_reg] = self.memory[addr]          
            
        # 更新标志位（仅影响加载操作）
        if mode == 1:
            self.update_flags(self.registers[dst_reg])
        
    def _movx(self, operand):
        """扩展寄存器移动：支持R0-R15"""
        src_reg = operand & 0x0F  # 低4位为源寄存器
        dst_reg = (operand >> 4) & 0x0F  # 高4位为目标寄存器
        self.registers[dst_reg] = self.registers[src_reg]
        self.update_flags(self.registers[dst_reg])

    def _add(self, operand):
        """加法: ADD Rdst, Rsrc"""
        src_reg = operand & 0x7
        dst_reg = (operand >> 2) & 0x7
        old_value = self.registers[dst_reg]
        a = old_value
        b = self.registers[src_reg]
        result = a + b
        
       # 无符号进位
        carry = result > 0xFF
        # 有符号溢出(正+正=负 或 负+负=正)
        overflow = ((a ^ b) & 0x80 == 0) and ((a ^ result) & 0x80 != 0)
        
        if carry:
            self.flags |= self.FLAG_C
        else:
            self.flags &= ~self.FLAG_C
            
        if overflow:
            self.flags |= self.FLAG_O
        else:
            self.flags &= ~self.FLAG_O

        self.registers[dst_reg] = result & 0xFF
        self.update_flags(self.registers[dst_reg])
        if self.debug:
            print(f"ADD R{dst_reg}, R{src_reg}: {old_value} + {self.registers[src_reg]} = {self.registers[dst_reg]}")
            
            
    def _add16(self, operand):
        """16位加法: ADD16 RRa, RRb"""
        reg_pair_a = operand & 0x7  # 低3位指定目标寄存器对
        reg_pair_b = (operand >> 3) & 0x7  # 高3位指定源寄存器对
        
        # 获取16位值（小端序）
        a_low, a_high = self.reg_pairs[f'RR{reg_pair_a*2}']
        b_low, b_high = self.reg_pairs[f'RR{reg_pair_b*2}']
        val_a = (self.registers[a_high] << 8) | self.registers[a_low]
        val_b = (self.registers[b_high] << 8) | self.registers[b_low]
        
        result = val_a + val_b
        
        # 写回结果
        self.registers[a_low] = result & 0xFF
        self.registers[a_high] = (result >> 8) & 0xFF
        
        # 更新标志（仅用低8位，保持兼容）
        self.update_flags(self.registers[a_low])
    
    def _sub(self, operand):
        """减法: SUB Rdst, Rsrc"""
        src_reg = operand & 0x7
        dst_reg = (operand >> 2) & 0x7
        old_value = self.registers[dst_reg]
        result = self.registers[dst_reg] - self.registers[src_reg]
        
        # 设置借位标志 (bit 1)
        if result < 0:
            self.flags |= 0x02
        else:
            self.flags &= 0xFD
        
        self.registers[dst_reg] = result & 0xFF
        self.update_flags(self.registers[dst_reg])
        if self.debug:
            print(f"SUB R{dst_reg}, R{src_reg}: {old_value} - {self.registers[src_reg]} = {self.registers[dst_reg]}")
        
    def _and(self, operand):
        """按位与: AND Rdst, Rsrc"""
        src_reg = operand & 0x7
        dst_reg = (operand >> 2) & 0x7
        old_value = self.registers[dst_reg]
        self.registers[dst_reg] &= self.registers[src_reg]
        self.update_flags(self.registers[dst_reg])
        if self.debug:
            print(f"AND R{dst_reg}, R{src_reg}: {old_value} & {self.registers[src_reg]} = {self.registers[dst_reg]}")
    
    def _or(self, operand):
        """按位或: OR Rdst, Rsrc"""
        src_reg = operand & 0x7
        dst_reg = (operand >> 2) & 0x7
        old_value = self.registers[dst_reg]
        self.registers[dst_reg] |= self.registers[src_reg]
        self.update_flags(self.registers[dst_reg])
        if self.debug:
            print(f"OR R{dst_reg}, R{src_reg}: {old_value} | {self.registers[src_reg]} = {self.registers[dst_reg]}")
    
    def _xor(self, operand):
        """按位异或: XOR Rdst, Rsrc"""
        src_reg = operand & 0x7
        dst_reg = (operand >> 2) & 0x7
        old_value = self.registers[dst_reg]
        self.registers[dst_reg] ^= self.registers[src_reg]
        self.update_flags(self.registers[dst_reg])
        if self.debug:
            print(f"XOR R{dst_reg}, R{src_reg}: {old_value} ^ {self.registers[src_reg]} = {self.registers[dst_reg]}")
    
    def _not(self, operand):
        """按位取反: NOT Rx"""
        reg = operand & 0x7
        old_value = self.registers[reg]
        self.registers[reg] = ~self.registers[reg] & 0xFF
        self.update_flags(self.registers[reg])
        if self.debug:
            print(f"NOT R{reg}: ~{old_value} = {self.registers[reg]}")
    
    def _jmp(self, operand):
        """无条件跳转: JMP [Rx] 或 JMP 立即数"""
        if operand & 0x8:  # 最高位表示立即数模式
            # 立即数跳转：下一个字节是跳转地址
            addr = self.fetch_byte()
            old_pc = self.pc
            self.pc = addr
            if self.debug:
                print(f"JMP {addr}: PC {old_pc} -> {self.pc}")
        else:
            # 寄存器间接跳转
            addr_reg = operand & 0x7
            old_pc = self.pc
            self.pc = self.registers[addr_reg]
            if self.debug:
                print(f"JMP [R{addr_reg}]: PC {old_pc} -> {self.pc}")
        
    def _jz(self, operand):
        """为零跳转: JZ [Rx] 或 JZ 立即数"""
        if self.flags & 0x01:  # 检查零标志
            if operand & 0x8:  # 最高位表示立即数模式
                addr = self.fetch_byte()
                old_pc = self.pc
                self.pc = addr
                if self.debug:
                    print(f"JZ {addr} (taken): PC {old_pc} -> {self.pc}")
            else:
                addr_reg = operand & 0x7
                old_pc = self.pc
                self.pc = self.registers[addr_reg]
                if self.debug:
                    print(f"JZ [R{addr_reg}] (taken): PC {old_pc} -> {self.pc}")
        else:
            if operand & 0x8:
                self.fetch_byte()  # 跳过立即数
            if self.debug:
                print(f"JZ (not taken)")
                
    def _jc(self, operand):
        """进位跳转: JC [Rx] 或 JC 立即数"""
        if self.flags & 0x02:  # 检查进位标志
            if operand & 0x8:  # 最高位表示立即数模式
                addr = self.fetch_byte()
                old_pc = self.pc
                self.pc = addr
                if self.debug:
                    print(f"JC {addr} (taken): PC {old_pc} -> {self.pc}")
            else:
                addr_reg = operand & 0x7
                old_pc = self.pc
                self.pc = self.registers[addr_reg]
                if self.debug:
                    print(f"JC [R{addr_reg}] (taken): PC {old_pc} -> {self.pc}")
        else:
            if operand & 0x8:
                self.fetch_byte()  # 跳过立即数
            if self.debug:
                print(f"JC (not taken)")

    def _jp(self, operand):
        """奇偶跳转: JP [Rx]或JP立即数"""
        if self.flags & self.FLAG_P:  # 检查奇偶标志
            if operand & 0x8:  # 立即数模式
                addr = self.fetch_byte()
                self.pc = addr
            else:  # 寄存器间接跳转
                addr_reg = operand & 0x7
                self.pc = self.registers[addr_reg]
            
    def _jo(self, operand):
        """溢出跳转: JO [Rx]或JO立即数"""
        if self.flags & self.FLAG_O:
            if operand & 0x8:  # 立即数模式
                addr = self.fetch_byte()
                self.pc = addr
            else:  # 寄存器间接跳转
                addr_reg = operand & 0x7
                self.pc = self.registers[addr_reg]

    def _js(self, operand):
        """符号跳转: JS [Rx]或JS立即数(结果为负时跳转)"""
        if self.flags & self.FLAG_S:
            if operand & 0x8:  # 立即数模式
                addr = self.fetch_byte()
                self.pc = addr
            else:  # 寄存器间接跳转
                addr_reg = operand & 0x7
                self.pc = self.registers[addr_reg]
            
    def _sex(self, operand):
        """符号扩展: SEX Rx (将8位有符号数扩展为16位)"""
        reg = operand & 0x7
        value = self.registers[reg]
        self.registers[reg] = value if value < 0x80 else (value | 0xFF00)
    
    def _call(self, operand):
        """调用子程序: CALL [Rx]（带安全防护的16位栈指针版本）"""
        # 保存返回地址（16位小端序）
        return_addr = self.pc
        
        # 安全检查1：栈空间不足
        if self.sp < 2 or self.sp >= len(self.memory):  # 需要2字节空间
            self._trigger_fault(0xFD)  # 栈溢出错误码
            return
        
        # 压栈高字节（先压高地址字节，符合小端序内存布局）
        self.memory[self.sp] = (return_addr >> 8) & 0xFF  # 高字节
        self.sp -= 1
        
        # 压栈低字节
        self.memory[self.sp] = return_addr & 0xFF        # 低字节
        self.sp -= 1
        
        # 跳转到目标地址（寄存器间接寻址）
        addr_reg = operand & 0x7
        target_addr = self.registers[addr_reg]
        
        # 安全检查2：目标地址有效性
        if target_addr >= len(self.memory):
            self._trigger_fault(0xFC)  # 非法跳转地址
            return
        
        if self.debug:
            print(f"CALL [R{addr_reg}]: PC 0x{return_addr:04X} -> 0x{target_addr:04X}")
            print(f"  栈顶: [0x{self.sp+1:04X}]=0x{self.memory[self.sp+1]:02X}")
            print(f"       [0x{self.sp+2:04X}]=0x{self.memory[self.sp+2]:02X}")
        
        self.pc = target_addr
    
    def _ret(self, operand):
        """从子程序返回: RET（带安全防护的16位栈指针版本）"""
        # 安全检查1：栈下溢
        if self.sp >= len(self.memory) - 2:
            self._trigger_fault(0xFE)  # 栈下溢错误码
            return
        
        # 弹出返回地址（小端序）
        self.sp += 1
        low_byte = self.memory[self.sp]
        
        self.sp += 1
        high_byte = self.memory[self.sp]
        
        return_addr = (high_byte << 8) | low_byte
        
        # 安全检查2：返回地址有效性
        if return_addr >= len(self.memory):
            self._trigger_fault(0xFB)  # 非法返回地址
            return
        
        if self.debug:
            print(f"RET: 弹出地址 0x{return_addr:04X}")
            print(f"  从栈: [0x{self.sp-1:04X}]=0x{low_byte:02X}")
            print(f"       [0x{self.sp:04X}]=0x{high_byte:02X}")
        
        old_pc = self.pc
        self.pc = return_addr
        
        # 安全检查3：防止无限递归
        if return_addr == old_pc:
            self._trigger_fault(0xFA)  # 递归陷阱
            
    
    def _inc(self, operand):
        """寄存器自增: INC Rx"""
        reg = operand & 0x7
        old_value = self.registers[reg]
        self.registers[reg] = (self.registers[reg] + 1) & 0xFF
        self.update_flags(self.registers[reg])
        if self.debug:
            print(f"INC R{reg}: {old_value} -> {self.registers[reg]}")
    
    # 新增指令实现
    def _swap(self, operand):
        """寄存器交换: SWAP Rx, Ry"""
        reg1 = (operand >> 3) & 0x7
        reg2 = operand & 0x7
        old1, old2 = self.registers[reg1], self.registers[reg2]
        self.registers[reg1], self.registers[reg2] = self.registers[reg2], self.registers[reg1]
        if self.debug:
            print(f"SWAP R{reg1}, R{reg2}: {old1} <-> {old2}")
    
    def _loadi(self, operand):
        """立即数加载: LOADI Rx, 立即数"""
        reg = operand & 0x7
        immediate = self.fetch_byte()
        old_value = self.registers[reg]
        self.registers[reg] = immediate
        self.update_flags(self.registers[reg])
        if self.debug:
            print(f"LOADI R{reg}, {immediate}: {old_value} -> {immediate}")
    
    def _push(self, operand):
        """压栈: PUSH Rx"""
        reg = operand & 0x7
        self._push_to_stack(self.registers[reg])
        if self.debug:
            print(f"PUSH R{reg}: {self.registers[reg]} -> stack")
    
    def _pop(self, operand):
        """弹栈: POP Rx"""
        reg = operand & 0x7
        value = self._pop_from_stack()
        self.registers[reg] = value
        self.update_flags(value)
        if self.debug:
            print(f"POP R{reg}: {value}")
        
    def _shl(self, operand):
        """逻辑左移: SHL Rd, Rs
        操作数格式:
        - 高4位: 目标寄存器Rd (R0-R15)
        - 低4位: 源寄存器Rs (R0-R15)
        """
        dst_reg = ((operand >> 4) & 0xF) # 目标寄存器范围R0-R15
        src_reg = operand & 0xF               # 源寄存器范围R0-R15
        shift_count = self.registers[src_reg] & 0xF  # 限制移位次数0-15
        
        old_value = self.registers[dst_reg]
        result = (old_value << shift_count) & 0xFF
        
        # 设置进位标志 (bit 1) - 检查最高位移出位
        if (old_value << (shift_count - 1)) & 0x80:
            self.flags |= 0x02
        else:
            self.flags &= 0xFD
            
        self.registers[dst_reg] = result
        self.update_flags(result)
        
        if self.debug:
            print(f"SHL R{dst_reg}, R{src_reg} (count={shift_count}): {old_value} << {shift_count} = {result}")
    
    def _shr(self, operand):
        """逻辑右移: SHR Rd, Rs
        操作数格式:
        - 高4位: 目标寄存器Rd (R0-R15)
        - 低4位: 源寄存器Rs (R0-R15)
        """
        dst_reg = ((operand >> 4) & 0xF) # 目标寄存器范围R0-R15
        src_reg = operand & 0xF               # 源寄存器范围R0-R15
        shift_count = self.registers[src_reg] & 0xF  # 限制移位次数0-15
        
        old_value = self.registers[dst_reg]
        result = old_value >> shift_count
        
        # 设置进位标志 (bit 1) - 检查最低位移出位
        if (old_value >> (shift_count - 1)) & 0x01:
            self.flags |= 0x02
        else:
            self.flags &= 0xFD
            
        self.registers[dst_reg] = result
        self.update_flags(result)
        
        if self.debug:
            print(f"SHR R{dst_reg}, R{src_reg} (count={shift_count}): {old_value} >> {shift_count} = {result}")

    def _load16(self, operand):
        """加载16位立即数到寄存器对: LOAD16 Rhigh:Rlow, imm16"""
        # 操作数格式：高4位=高字节寄存器，低4位=低字节寄存器
        reg_high = (operand >> 4) & 0x07
        reg_low = operand & 0x07
        
        # 读取16位立即数（小端序）
        low_byte = self.fetch_byte()
        high_byte = self.fetch_byte()
        value = (high_byte << 8) | low_byte
        
        # 存入寄存器对
        self.registers[reg_high] = (value >> 8) & 0xFF
        self.registers[reg_low] = value & 0xFF
        
        if self.debug:
            print(f"LOAD16 R{reg_high}:R{reg_low}, 0x{value:04X} "
                  f"(R{reg_high}=0x{self.registers[reg_high]:02X}, "
                  f"R{reg_low}=0x{self.registers[reg_low]:02X})")

    # 新增系统调用指令
    def _syscalls(self, operand):
        func_code = operand & 0x0F
        if func_code == 0x01:  # 打印字符串
            addr = self.registers[0] << 8 | self.registers[1]
            while (char := self.memory[addr]) != 0:
                self.io_devices[0xFF00]['buffer'].append(chr(char))
                addr += 1
        elif func_code == 0x02:  # 读取输入
            addr = self.registers[2] << 8 | self.registers[3]
            for char in self.io_devices[0xFF03]['buffer']:
                self.memory[addr] = ord(char)
                addr += 1
            self.memory[addr] = 0  # 终止符

    def _syscall(self, operand):
            """系统调用/触发软件中断"""
            int_type = operand & 0xFF
            if self.debug:
                print(f"SYS 0x{int_type:X} -> 触发中断")
            self.handle_interrupt(int_type)

    def _set_mode(self, operand):
        """设置CPU模式: SETMODE [mode]"""
        mode = operand & 0b11
        self.flags = (self.flags & ~self.MODE_MASK) | (mode << 6)
        if self.debug:
            print(f"SETMODE {mode}: FLAGS=0b{self.flags:08b}")
    
    def _set_flag(self, operand):
        """设置标志位: SETFLAG [mask]"""
        mask = operand & 0xFF
        self.flags |= mask
        if self.debug:
            print(f"SETFLAG 0b{mask:08b}: FLAGS=0b{self.flags:08b}")
    
    def _clr_flag(self, operand):
        """清除标志位: CLRFLAG [mask]"""
        mask = operand & 0xFF
        self.flags &= ~mask
        if self.debug:
            print(f"CLRFLAG 0b{mask:08b}: FLAGS=0b{self.flags:08b}")
    
    def _bcd_add(self, operand):
        """BCD加法: BCDADD Rd, Rs"""
        if (self.flags & self.MODE_MASK) != 0b01000000:
            raise RuntimeError("BCD运算必须在BCD模式下执行")
            
        src = operand & 0x7
        dst = (operand >> 3) & 0x7
        result = self.registers[dst] + self.registers[src]
        
        # 设置半进位标志
        if (self.registers[dst] & 0xF) + (self.registers[src] & 0xF) > 0xF:
            self.flags |= self.FLAG_H
        else:
            self.flags &= ~self.FLAG_H
            
        # BCD调整
        if (result & 0xF) > 9 or (self.flags & self.FLAG_H):
            result += 6
        if result > 0x99:
            result += 0x60
            self.flags |= self.FLAG_C
        else:
            self.flags &= ~self.FLAG_C
            
        self.registers[dst] = result & 0xFF
        self.update_flags(self.registers[dst])

    # 使用查表法或位运算优化的指令PARITY
    def _parity(x):
        x ^= x >> 4
        x ^= x >> 2
        x ^= x >> 1
        return (~x) & 1
        
    def handle_interrupt(self, int_type):
        """
        完整的中断处理流程（整合版）
        参数:
            int_type: 中断类型号（必须已在interrupt_vectors中注册）
        """
        # === 第1步：中断条件校验 ===
        # 检查全局中断使能标志
        if not (self.flags & self.FLAG_I):
            if self.debug:
                print(f"中断{int_type}被屏蔽（FLAG_I=0）")
            return
        
        # 检查中断号是否合法
        if int_type not in self.interrupt_vectors:
            if self.debug:
                print(f"非法中断类型: 0x{int_type:X}")
            self._trigger_fault(0xFE)  # 触发非法中断错误
            return
        
        # 调试模式特殊处理（除非是陷阱中断）
        current_mode = self.flags & self.MODE_MASK
        if current_mode == 0b10000000 and not (int_type & 0x80):
            if self.debug:
                print(f"调试模式下收到中断: 0x{int_type:X}")
                # 继续处理而不是return
    
        # === 第2步：保存完整上下文 ===
        self._save_cpu_context()
        
        # === 第3步：设置新状态 ===
        # 自动禁用中断（模仿x86的CLI行为）
        self.flags &= ~self.FLAG_I  # 清除FLAG_I标志位
        
        # 清除陷阱标志（如果当前是陷阱中断）
        if int_type & 0x80:
            self.flags &= ~self.FLAG_T
        
        # === 第4步：跳转到中断处理程序 ===
        handler_addr = self.interrupt_vectors[int_type]['handler_addr']
        old_pc = self.pc
        self.pc = handler_addr
        
        if self.debug:
            print(
                f"处理中断0x{int_type:X} | "
                f"PC: 0x{old_pc:04X}→0x{self.pc:04X} | "
                f"FLAGS: 0b{self.flags:08b}"
            )
        
    def _push_to_stack(self, value):
        """将16位值压入栈（自动处理8位值扩展）"""
        # 检查栈边界（至少需要2字节空间）
        if self.sp < 0:
            self._trigger_fault(0xFF)  # 栈下溢错误
            return
        
        # 处理8位值自动扩展（符号扩展）
        if isinstance(value, int) and value <= 0xFF:
            value = value if value < 0x80 else (value | 0xFF00)  # 符号扩展
        
        # 写入内存（先高字节后低字节）
        self.memory[self.sp] = (value >> 8) & 0xFF  # 高字节
        self.sp = (self.sp - 1) % len(self.memory)
        self.memory[self.sp] = value & 0xFF         # 低字节
        
        # 更新栈指针（再减1，因为16位占2字节）
        self.sp = (self.sp - 1) % len(self.memory)
        
        if self.debug:
            print(f"PUSH16 [0x{self.sp+2:04X}] = 0x{value:04X}")
    
    def _pop_from_stack(self):
        """从栈中弹出16位值（自动处理8位收缩）"""
        # 检查栈边界
        if self.sp >= len(self.memory) - 2:
            self._trigger_fault(0xFE)  # 栈上溢错误
            return 0
        
        # 更新栈指针（先加1，因为16位占2字节）
        self.sp = (self.sp + 1) % len(self.memory)
        low = self.memory[self.sp]      # 低字节
        
        self.sp = (self.sp + 1) % len(self.memory)
        high = self.memory[self.sp]     # 高字节
        
        value = (high << 8) | low
        
        if self.debug:
            print(f"POP16  [0x{self.sp:04X}] = 0x{value:04X}")
        
        return value
    
    def _save_cpu_context(self):
        """保存完整CPU上下文到栈（16位版本）"""
        if self.debug:
            print(f"=== 开始保存上下文 ===\n保存前 SP=0x{self.sp:04X}")
            print(f"当前 PC=0x{self.pc:04X}, FLAGS=0b{self.flags:08b}")
        
        # 保存PC（16位）
        self._push_to_stack(self.pc)
        
        # 保存FLAGS（8位扩展为16位）
        self._push_to_stack(self.flags)
        
        # 保存通用寄存器（R0-R7，每个16位）
        for reg in range(7, -1, -1):
            self._push_to_stack(self.registers[reg])
        
        if self.debug:
            print(f"保存后 SP=0x{self.sp:04X}\n=== 上下文保存完成 ===")
    
    def _reti(self, _):
        """中断返回：恢复上下文（16位版本）"""
        if self.debug:
            print(f"=== 开始恢复上下文 ===\n恢复前 SP=0x{self.sp:04X}")
        
        # 恢复通用寄存器（R0-R7，每个16位）
        for reg in range(8):
            self.registers[reg] = self._pop_from_stack()
        
        # 恢复FLAGS（16位截断为8位）
        saved_flags = self._pop_from_stack() & 0xFF
        
        # 显式重新启用中断（保留其他标志位）
        self.flags = saved_flags | self.FLAG_I  # 按位或操作确保FLAG_I=1
        
        # 恢复PC（16位）
        self.pc = self._pop_from_stack()
        
        if self.debug:
            print(f"恢复后 SP=0x{self.sp:04X}")
            print(f"PC恢复为 0x{self.pc:04X}, FLAGS=0b{self.flags:08b}")
            print("=== 上下文恢复完成 ===")


        
    def _trigger_fault(self, code):
        """增强版故障处理，处理严重错误（如非法中断/栈溢出）"""
        self.running = False
        self.flags |= 0x08  # 设置错误标志
        fault_messages = {
            0xFA: "递归陷阱（PC未改变）",
            0xFB: "非法返回地址",
            0xFC: "非法跳转地址", 
            0xFD: "栈溢出",
            0xFE: "栈下溢",
            0xFF: "栈操作越界"
        }
        print(f"CPU故障！代码: 0x{code:02X} - {fault_messages.get(code, '未知错误')}")
        if self.debug:
            self._dump_cpu_state()
            
    def _dump_cpu_state(self):
        """调试用：打印CPU状态"""
        print("\n=== CPU状态转储 ===")
        print(f"PC: 0x{self.pc:04X} | FLAGS: 0b{self.flags:08b}")
        print("寄存器:")
        for i, val in enumerate(self.registers):
            print(f"R{i}: 0x{val:02X} ({val})", end=' | ')
        print("\n栈顶内容:")
        for addr in range(self.registers[7]+1, min(self.registers[7]+5, 0xFFFF)):
            print(f"[0x{addr:04X}]: 0x{self.memory[addr]:02X}")
        
    # 实现中断控制器
    def check_interrupts(self):
        if self.io_devices[0xFF03]['buffer']:  # 键盘中断
            self.handle_interrupt(0x01)
        elif self.io_devices[0xFF05]['value'] % 100 == 0:  # 定时器中断
            self.handle_interrupt(0x02)

    def read16(self, addr):
        """通过两次8位读取模拟16位访问"""
        return (self.memory[(addr + 1) % 0x10000] << 8) | self.memory[addr]
    
    def write16(self, addr, value):
        """通过两次8位写入模拟16位存储"""
        self.memory[addr] = value & 0xFF
        self.memory[(addr + 1) % 0x10000] = (value >> 8) & 0xFF
        
    # 添加DMA支持
    def read_mem(self, addr):
        """读取内存，将R0-R15映射到0xFFF0-0xFFFF"""
        if 0xFFF0 <= addr <= 0xFFFF:
            return self.registers[addr - 0xFFF0]  # R0-R15对应0xFFF0-0xFFFF
        return self.memory[addr]
    
    def write_mem(self, addr, value):
        """写入内存，寄存器映射区只允许写入有效寄存器"""
        if 0xFFF0 <= addr <= 0xFFFF:
            reg_idx = addr - 0xFFF0
            if reg_idx < 16:  # 只允许写入R0-R15
                self.registers[reg_idx] = value
            else:
                raise ValueError(f"无效寄存器地址: 0x{addr:04X}")
        else:
            self.memory[addr] = value
            
    # 简易16位内存访问方法，目前只允许单独调用
    def read_mem_16bit(self, addr):
        """读取16位数据(小端序)"""
        low = self.memory[addr]
        high = self.memory[(addr + 1) % len(self.memory)]
        return (high << 8) | low
    
    def write_mem_16bit(self, addr, value):
        """写入16位数据(小端序)"""
        self.memory[addr] = value & 0xFF
        self.memory[(addr + 1) % len(self.memory)] = (value >> 8) & 0xFF
    
    def dma_transfer(self, src, dest, length, allow_readonly=False, unsafe_direct=False):
        """       增强版DMA传输，支持寄存器只读访问和直接传输模式
        
        参数:
            src: 源地址 (16位)
            dest: 目标地址 (16位)
            length: 传输长度 (字节)
            allow_readonly: 是否允许从寄存器映射区读取 (默认False)
            unsafe_direct: 是否跳过所有安全检查 (默认False, 危险!)
        
        异常:
            MemoryError: 访问违规时抛出
        """
        # 寄存器映射区范围
        REG_MAP_START = 0xFFF0
        REG_MAP_END = 0xFFFF
        
        # —— 模式1: 直接传输（跳过所有检查） ——
        if unsafe_direct:
            if self.debug:
                print(f"[DMA 直接模式] src=0x{src:04X}, dest=0x{dest:04X}, len={length}")
                if val := locals().get('val'):
                    print(f"  数据块: {val:02X}...")
            for i in range(length):
                self.memory[dest + i] = self.memory[src + i]
            return
    
        # —— 模式2: 安全传输 ——
        # 检查源地址范围
        if (src <= REG_MAP_END and src + length > REG_MAP_START):
            if not (allow_readonly and dest < REG_MAP_START):
                raise MemoryError(
                    f"DMA禁止写入寄存器映射区 (0x{src:04X}-0x{src+length:04X})"
                )
        
        # 检查目标地址范围
        if (dest <= REG_MAP_END and dest + length > REG_MAP_START):
            raise MemoryError(
                f"DMA禁止修改寄存器映射区 (0x{dest:04X}-0x{dest+length:04X})"
            )
    
        # —— 实际传输逻辑 ——
        for i in range(length):
            current_src = src + i
            current_dest = dest + i
            
            # 情况1: 从寄存器映射区读取（如果允许）
            if REG_MAP_START <= current_src <= REG_MAP_END and allow_readonly:
                val = self.registers[current_src - REG_MAP_START]
                self.write_mem(current_dest, val)
                if self.debug:
                    print(f"[DMA 只读寄存器] R{current_src - REG_MAP_START} -> 0x{current_dest:04X}")
                    if val := locals().get('val'):
                        print(f"  数据块: {val:02X}...")
                    
            
            # 情况2: 普通内存传输
            else:
                val = self.read_mem(current_src)
                self.write_mem(current_dest, val)
                if self.debug:
                    print(f"[DMA] 传输 {length} 字节: 0x{src:04X} -> 0x{dest:04X}")
                    print(f"  数据块: {val:02X}...")
                
            
            
from enum import Enum, auto
import sys


class TokenType(Enum):
    # 词法标记类型
    KEYWORD = auto()
    IDENTIFIER = auto()
    NUMBER = auto()
    STRING = auto()
    OPERATOR = auto()
    PUNCTUATION = auto()
    EOF = auto()

class DataType(Enum):
    # 数据类型
    BYTE = auto()
    INT = auto()
    WORD = auto()
    BOOL = auto()
    PTR = auto()
    VOID = auto()
    ARRAY = auto()
    STRUCT = auto()

class Symbol:
    """符号表条目"""
    def __init__(self, name, type_, scope_level, address=None, size=1):
        self.name = name
        self.type = type_
        self.scope_level = scope_level
        self.address = address  # 内存地址或寄存器
        self.size = size        # 大小(字节)
        
    def __str__(self):
        return f"{self.name}: {self.type} @{self.address} (size={self.size})"

class TCCCompiler:
    """TCC编译器主类"""
    
    def __init__(self, debug=False):
        self.symbol_table = {}       # 符号表
        self.current_scope = 0       # 当前作用域层级
        self.next_address = 0x0100   # 下一个可用内存地址
        self.labels = {}             # 标签表
        self.debug = debug
        self.cpu = TC15_CPU(debug=debug)  # TC-15 CPU实例
        
        # 初始化内置函数和类型
        self._init_builtins()
    
    def _init_builtins(self):
        """初始化内置函数和类型"""
        # 内置类型
        self.add_symbol("byte", DataType.BYTE, is_type=True)
        self.add_symbol("int", DataType.INT, is_type=True)
        self.add_symbol("word", DataType.WORD, is_type=True)
        self.add_symbol("bool", DataType.BOOL, is_type=True)
        self.add_symbol("ptr", DataType.PTR, is_type=True)
        self.add_symbol("void", DataType.VOID, is_type=True)
        
        # 内置函数
        self.add_symbol("print", "func", address=0xFF00)
        self.add_symbol("input", "func", address=0xFF03)
    
    def add_symbol(self, name, type_, scope_level=None, address=None, size=1, is_type=False):
        """添加符号到符号表"""
        if scope_level is None:
            scope_level = self.current_scope
            
        if name in self.symbol_table:
            raise ValueError(f"符号 '{name}' 已定义")
            
        symbol = Symbol(name, type_, scope_level, address, size)
        self.symbol_table[name] = symbol
        
        if not is_type and address is None:
            # 分配内存
            symbol.address = self.next_address
            self.next_address += size
            
        if self.debug:
            print(f"添加符号: {symbol}")
            
        return symbol
    
    def compile(self, source_code):
        """编译源代码"""
        tokens = self.lex(source_code)
        ast = self.parse(tokens)
        code = self.generate_code(ast)
        return code
    
    def lex(self, source_code):
        """词法分析"""
        # 简化的词法分析实现
        tokens = []
        i = 0
        n = len(source_code)
        
        while i < n:
            c = source_code[i]
            
            # 跳过空白字符
            if c.isspace():
                i += 1
                continue
                
            # 标识符或关键字
            if c.isalpha() or c == '_':
                start = i
                while i < n and (source_code[i].isalnum() or source_code[i] == '_'):
                    i += 1
                ident = source_code[start:i]
                
                # 检查是否是关键字
                if ident in ['byte', 'int', 'word', 'bool', 'ptr', 'if', 'else', 
                            'while', 'for', 'return', 'struct', 'true', 'false']:
                    tokens.append((TokenType.KEYWORD, ident))
                else:
                    tokens.append((TokenType.IDENTIFIER, ident))
                continue
                
            # 数字
            if c.isdigit():
                start = i
                while i < n and source_code[i].isdigit():
                    i += 1
                num = source_code[start:i]
                tokens.append((TokenType.NUMBER, num))
                continue
                
            # 字符串
            if c == '"':
                start = i
                i += 1
                while i < n and source_code[i] != '"':
                    i += 1
                if i >= n:
                    raise SyntaxError("未闭合的字符串")
                str_lit = source_code[start+1:i]
                tokens.append((TokenType.STRING, str_lit))
                i += 1
                continue
                
            # 运算符
            if c in '+-*/%&|^<>!=~':
                # 处理复合运算符如 ==, !=, <=, >=
                if i+1 < n and source_code[i+1] in '=<>':
                    tokens.append((TokenType.OPERATOR, c + source_code[i+1]))
                    i += 2
                else:
                    tokens.append((TokenType.OPERATOR, c))
                    i += 1
                continue
                
            # 标点符号
            if c in '(){}[],;:.':
                tokens.append((TokenType.PUNCTUATION, c))
                i += 1
                continue
                
            raise SyntaxError(f"未知字符: '{c}'")
        
        tokens.append((TokenType.EOF, ""))
        return tokens
    
    def parse(self, tokens):
        """语法分析"""
        # 简化的语法分析实现
        ast = {'type': 'program', 'body': []}
        i = 0
        n = len(tokens)
        
        while i < n and tokens[i][0] != TokenType.EOF:
            token_type, token_val = tokens[i]
            
            # 变量声明
            if token_type == TokenType.KEYWORD and token_val in ['byte', 'int', 'word', 'bool', 'ptr']:
                decl = self._parse_declaration(tokens, i)
                ast['body'].append(decl)
                i = decl['end']
                continue
                
            # 函数定义
            if (token_type == TokenType.KEYWORD and token_val in ['byte', 'int', 'word', 'bool', 'ptr', 'void'] and 
                i+1 < n and tokens[i+1][0] == TokenType.IDENTIFIER and 
                i+2 < n and tokens[i+2][1] == '('):
                func = self._parse_function(tokens, i)
                ast['body'].append(func)
                i = func['end']
                continue
                
            # 结构体定义
            if token_type == TokenType.KEYWORD and token_val == 'struct':
                struct = self._parse_struct(tokens, i)
                ast['body'].append(struct)
                i = struct['end']
                continue
                
            # 表达式语句
            expr = self._parse_expression(tokens, i)
            ast['body'].append(expr)
            i = expr['end']
            
            # 分号
            if i < n and tokens[i][1] == ';':
                i += 1
        
        return ast
    
    def _parse_declaration(self, tokens, start):
        """解析变量声明"""
        i = start
        type_token, type_val = tokens[i]
        i += 1
        
        # 获取变量名
        if tokens[i][0] != TokenType.IDENTIFIER:
            raise SyntaxError("预期标识符")
        name = tokens[i][1]
        i += 1
        
        # 初始化表达式
        init = None
        if i < len(tokens) and tokens[i][1] == '=':
            i += 1
            init = self._parse_expression(tokens, i)
            i = init['end']
        
        # 数组声明
        array_size = None
        if i < len(tokens) and tokens[i][1] == '[':
            i += 1
            if tokens[i][0] != TokenType.NUMBER:
                raise SyntaxError("数组大小必须是常量数字")
            array_size = int(tokens[i][1])
            i += 1
            if tokens[i][1] != ']':
                raise SyntaxError("缺少 ']'")
            i += 1
        
        # 创建声明节点
        node = {
            'type': 'declaration',
            'data_type': type_val,
            'name': name,
            'init': init,
            'array_size': array_size,
            'end': i
        }
        
        # 添加到符号表
        size = array_size if array_size else 1
        if type_val == 'int' or type_val == 'word':
            size *= 2
        self.add_symbol(name, type_val, size=size)
        
        return node
    
    def _parse_function(self, tokens, start):
        """解析函数定义"""
        i = start
        return_type = tokens[i][1]
        i += 1
        
        # 函数名
        if tokens[i][0] != TokenType.IDENTIFIER:
            raise SyntaxError("预期函数名")
        name = tokens[i][1]
        i += 1
        
        # 参数列表
        if tokens[i][1] != '(':
            raise SyntaxError("预期 '('")
        i += 1
        
        params = []
        while i < len(tokens) and tokens[i][1] != ')':
            # 参数类型
            if tokens[i][0] != TokenType.KEYWORD or tokens[i][1] not in ['byte', 'int', 'word', 'bool', 'ptr']:
                raise SyntaxError("预期参数类型")
            param_type = tokens[i][1]
            i += 1
            
            # 参数名
            if tokens[i][0] != TokenType.IDENTIFIER:
                raise SyntaxError("预期参数名")
            param_name = tokens[i][1]
            i += 1
            
            params.append({'type': param_type, 'name': param_name})
            
            # 逗号分隔
            if i < len(tokens) and tokens[i][1] == ',':
                i += 1
        
        if tokens[i][1] != ')':
            raise SyntaxError("预期 ')'")
        i += 1
        
        # 函数体
        if tokens[i][1] != '{':
            raise SyntaxError("预期 '{'")
        i += 1
        
        # 进入新的作用域
        self.current_scope += 1
        
        # 添加参数到符号表
        for param in params:
            size = 2 if param['type'] in ['int', 'word'] else 1
            self.add_symbol(param['name'], param['type'], size=size)
        
        body = []
        while i < len(tokens) and tokens[i][1] != '}':
            # 解析语句
            stmt = self._parse_statement(tokens, i)
            body.append(stmt)
            i = stmt['end']
        
        if tokens[i][1] != '}':
            raise SyntaxError("预期 '}'")
        i += 1
        
        # 退出作用域
        self.current_scope -= 1
        
        # 创建函数节点
        node = {
            'type': 'function',
            'name': name,
            'return_type': return_type,
            'params': params,
            'body': body,
            'end': i
        }
        
        # 添加到符号表
        self.add_symbol(name, 'func')
        
        return node
    
    def _parse_struct(self, tokens, start):
        """解析结构体定义"""
        i = start
        
        if tokens[i][1] != 'struct':
            raise SyntaxError("预期 'struct'")
        i += 1
        
        # 结构体名
        if tokens[i][0] != TokenType.IDENTIFIER:
            raise SyntaxError("预期结构体名")
        name = tokens[i][1]
        i += 1
        
        if tokens[i][1] != '{':
            raise SyntaxError("预期 '{'")
        i += 1
        
        # 解析成员
        members = []
        while i < len(tokens) and tokens[i][1] != '}':
            # 成员类型
            if tokens[i][0] != TokenType.KEYWORD or tokens[i][1] not in ['byte', 'int', 'word', 'bool', 'ptr']:
                raise SyntaxError("预期成员类型")
            member_type = tokens[i][1]
            i += 1
            
            # 成员名
            if tokens[i][0] != TokenType.IDENTIFIER:
                raise SyntaxError("预期成员名")
            member_name = tokens[i][1]
            i += 1
            
            members.append({'type': member_type, 'name': member_name})
            
            # 分号
            if tokens[i][1] != ';':
                raise SyntaxError("预期 ';'")
            i += 1
        
        if tokens[i][1] != '}':
            raise SyntaxError("预期 '}'")
        i += 1
        
        # 分号
        if tokens[i][1] != ';':
            raise SyntaxError("预期 ';'")
        i += 1
        
        # 创建结构体节点
        node = {
            'type': 'struct',
            'name': name,
            'members': members,
            'end': i
        }
        
        # 添加到符号表作为类型
        self.add_symbol(name, DataType.STRUCT, is_type=True)
        
        return node
    
    def _parse_statement(self, tokens, start):
        """解析语句"""
        i = start
        token_type, token_val = tokens[i]
        
        # if语句
        if token_type == TokenType.KEYWORD and token_val == 'if':
            return self._parse_if(tokens, i)
            
        # while循环
        if token_type == TokenType.KEYWORD and token_val == 'while':
            return self._parse_while(tokens, i)
            
        # for循环
        if token_type == TokenType.KEYWORD and token_val == 'for':
            return self._parse_for(tokens, i)
            
        # return语句
        if token_type == TokenType.KEYWORD and token_val == 'return':
            return self._parse_return(tokens, i)
            
        # 块语句
        if token_val == '{':
            return self._parse_block(tokens, i)
            
        # 变量声明
        if token_type == TokenType.KEYWORD and token_val in ['byte', 'int', 'word', 'bool', 'ptr']:
            return self._parse_declaration(tokens, i)
            
        # 表达式语句
        expr = self._parse_expression(tokens, i)
        if tokens[expr['end']][1] == ';':
            expr['end'] += 1
        return expr
    
    def _parse_expression(self, tokens, start):
        """解析表达式"""
        # 简化的表达式解析
        i = start
        left = self._parse_primary(tokens, i)
        i = left['end']
        
        while i < len(tokens) and tokens[i][0] == TokenType.OPERATOR:
            op = tokens[i][1]
            i += 1
            right = self._parse_primary(tokens, i)
            i = right['end']
            
            left = {
                'type': 'binary_expr',
                'operator': op,
                'left': left,
                'right': right,
                'end': i
            }
        
        return left
    
    def _parse_primary(self, tokens, start):
        """解析基本表达式"""
        i = start
        token_type, token_val = tokens[i]
        
        # 数字
        if token_type == TokenType.NUMBER:
            i += 1
            return {
                'type': 'number',
                'value': int(token_val),
                'end': i
            }
            
        # 标识符
        if token_type == TokenType.IDENTIFIER:
            name = token_val
            i += 1
            
            # 函数调用
            if i < len(tokens) and tokens[i][1] == '(':
                i += 1
                args = []
                while i < len(tokens) and tokens[i][1] != ')':
                    arg = self._parse_expression(tokens, i)
                    args.append(arg)
                    i = arg['end']
                    if tokens[i][1] == ',':
                        i += 1
                
                if tokens[i][1] != ')':
                    raise SyntaxError("预期 ')'")
                i += 1
                
                return {
                    'type': 'call',
                    'name': name,
                    'args': args,
                    'end': i
                }
            
            # 数组访问
            if i < len(tokens) and tokens[i][1] == '[':
                i += 1
                index = self._parse_expression(tokens, i)
                i = index['end']
                
                if tokens[i][1] != ']':
                    raise SyntaxError("预期 ']'")
                i += 1
                
                return {
                    'type': 'array_access',
                    'name': name,
                    'index': index,
                    'end': i
                }
            
            # 结构体成员访问
            if i < len(tokens) and tokens[i][1] == '.':
                i += 1
                if tokens[i][0] != TokenType.IDENTIFIER:
                    raise SyntaxError("预期成员名")
                member = tokens[i][1]
                i += 1
                
                return {
                    'type': 'member_access',
                    'object': name,
                    'member': member,
                    'end': i
                }
            
            # 简单变量引用
            return {
                'type': 'identifier',
                'name': name,
                'end': i
            }
            
        # 字符串
        if token_type == TokenType.STRING:
            i += 1
            return {
                'type': 'string',
                'value': token_val,
                'end': i
            }
            
        # 括号表达式
        if token_val == '(':
            i += 1
            expr = self._parse_expression(tokens, i)
            i = expr['end']
            
            if tokens[i][1] != ')':
                raise SyntaxError("预期 ')'")
            i += 1
            
            return {
                'type': 'paren_expr',
                'expr': expr,
                'end': i
            }
            
        raise SyntaxError(f"意外的标记: {token_val}")
    
    def generate_code(self, ast):
        """生成TC-15汇编代码"""
        code = []
        
        # 生成数据段
        code.append("; 数据段")
        for name, symbol in self.symbol_table.items():
            if symbol.type in ['byte', 'int', 'word', 'bool', 'ptr'] and not isinstance(symbol.type, DataType):
                size = symbol.size
                if symbol.type in ['int', 'word']:
                    size //= 2
                code.append(f"{name}: .res {size}")
        
        # 生成代码段
        code.append("\n; 代码段")
        code.append(".code")
        code.append("main:")
        
        # 遍历AST生成代码
        for node in ast['body']:
            code += self._generate_node(node)
        
        # 添加程序结束
        code.append("    HALT")
        
        return '\n'.join(code)
    
    def _generate_node(self, node):
        """生成单个节点的代码"""
        code = []
        
        if node['type'] == 'declaration':
            # 变量声明
            name = node['name']
            symbol = self.symbol_table[name]
            
            if node['init'] is not None:
                # 有初始化表达式
                init_code = self._generate_expression(node['init'])
                code += init_code
                
                # 存储到变量地址
                if symbol.size == 1:
                    code.append(f"    STORE [{symbol.address}], R0")
                else:
                    code.append(f"    STOREX [{symbol.address}], R0")
                    code.append(f"    STOREX [{symbol.address+1}], R1")
        
        elif node['type'] == 'binary_expr':
            # 二元表达式
            left_code = self._generate_expression(node['left'])
            right_code = self._generate_expression(node['right'])
            
            code += left_code
            code.append("    PUSH R0")  # 保存左值
            
            code += right_code
            code.append("    POP R1")   # 恢复左值到R1
            
            op = node['operator']
            if op == '+':
                code.append("    ADD R0, R1")
            elif op == '-':
                code.append("    SUB R0, R1")
            elif op == '*':
                # 简单乘法实现
                code.append("    MOV R2, R0")
                code.append("    MOV R0, #0")
                code.append("mul_loop:")
                code.append("    JZ R2, mul_end")
                code.append("    ADD R0, R1")
                code.append("    DEC R2")
                code.append("    JMP mul_loop")
                code.append("mul_end:")
            elif op == '/':
                # 简单除法实现
                code.append("    MOV R2, R0")
                code.append("    MOV R0, #0")
                code.append("    MOV R3, R1")
                code.append("div_loop:")
                code.append("    CMP R3, R2")
                code.append("    JC div_end")
                code.append("    INC R0")
                code.append("    SUB R3, R2")
                code.append("    JMP div_loop")
                code.append("div_end:")
            elif op == '&':
                code.append("    AND R0, R1")
            elif op == '|':
                code.append("    OR R0, R1")
            elif op == '^':
                code.append("    XOR R0, R1")
            elif op == '==':
                code.append("    CMP R0, R1")
                code.append("    MOV R0, #0")
                code.append("    JNZ not_eq")
                code.append("    MOV R0, #1")
                code.append("not_eq:")
            elif op == '!=':
                code.append("    CMP R0, R1")
                code.append("    MOV R0, #0")
                code.append("    JZ is_eq")
                code.append("    MOV R0, #1")
                code.append("is_eq:")
            elif op == '<':
                code.append("    CMP R1, R0")
                code.append("    MOV R0, #0")
                code.append("    JC is_lt")
                code.append("    MOV R0, #1")
                code.append("is_lt:")
            elif op == '>':
                code.append("    CMP R0, R1")
                code.append("    MOV R0, #0")
                code.append("    JC is_gt")
                code.append("    MOV R0, #1")
                code.append("is_gt:")
            elif op == '<=':
                code.append("    CMP R1, R0")
                code.append("    MOV R0, #0")
                code.append("    JZ is_le")
                code.append("    JC is_le")
                code.append("    MOV R0, #1")
                code.append("is_le:")
            elif op == '>=':
                code.append("    CMP R0, R1")
                code.append("    MOV R0, #0")
                code.append("    JZ is_ge")
                code.append("    JC is_ge")
                code.append("    MOV R0, #1")
                code.append("is_ge:")
        
        elif node['type'] == 'identifier':
            # 变量引用
            name = node['name']
            symbol = self.symbol_table[name]
            
            if symbol.size == 1:
                code.append(f"    LOAD R0, [{symbol.address}]")
            else:
                code.append(f"    LOADX R0, [{symbol.address}]")
                code.append(f"    LOADX R1, [{symbol.address+1}]")
        
        elif node['type'] == 'number':
            # 数字常量
            value = node['value']
            code.append(f"    MOVI R0, #{value}")
        
        elif node['type'] == 'call':
            # 函数调用
            name = node['name']
            
            # 压入参数
            for arg in reversed(node['args']):
                arg_code = self._generate_expression(arg)
                code += arg_code
                code.append("    PUSH R0")
            
            # 调用函数
            code.append(f"    CALL {name}")
            
            # 清理栈 (假设调用者负责清理)
        
        elif node['type'] == 'function':
            # 函数定义
            name = node['name']
            code.append(f"{name}:")
            
            # 函数序言
            code.append("    PUSH RR2")  # 保存调用者寄存器
            
            # 生成函数体
            for stmt in node['body']:
                code += self._generate_node(stmt)
            
            # 函数结尾
            code.append("    POP RR2")   # 恢复调用者寄存器
            code.append("    RET")
        
        elif node['type'] == 'return':
            # return语句
            if 'expr' in node:
                expr_code = self._generate_expression(node['expr'])
                code += expr_code
            
            code.append("    RET")
        
        elif node['type'] == 'if':
            # if语句
            cond_code = self._generate_expression(node['cond'])
            code += cond_code
            
            label_else = f"if_else_{len(code)}"
            label_end = f"if_end_{len(code)}"
            
            code.append(f"    JZ R0, {label_else}")
            
            # then分支
            then_code = self._generate_node(node['then'])
            code += then_code
            code.append(f"    JMP {label_end}")
            
            # else分支
            code.append(f"{label_else}:")
            if 'else' in node:
                else_code = self._generate_node(node['else'])
                code += else_code
            
            code.append(f"{label_end}:")
        
        elif node['type'] == 'while':
            # while循环
            label_start = f"while_start_{len(code)}"
            label_end = f"while_end_{len(code)}"
            
            code.append(f"{label_start}:")
            
            # 条件
            cond_code = self._generate_expression(node['cond'])
            code += cond_code
            code.append(f"    JZ R0, {label_end}")
            
            # 循环体
            body_code = self._generate_node(node['body'])
            code += body_code
            code.append(f"    JMP {label_start}")
            
            code.append(f"{label_end}:")
        
        elif node['type'] == 'for':
            # for循环
            init_code = self._generate_node(node['init'])
            cond_code = self._generate_expression(node['cond'])
            update_code = self._generate_node(node['update'])
            body_code = self._generate_node(node['body'])
            
            label_start = f"for_start_{len(code)}"
            label_end = f"for_end_{len(code)}"
            
            # 初始化
            code += init_code
            
            # 循环开始
            code.append(f"{label_start}:")
            
            # 条件检查
            code += cond_code
            code.append(f"    JZ R0, {label_end}")
            
            # 循环体
            code += body_code
            
            # 更新表达式
            code += update_code
            code.append(f"    JMP {label_start}")
            
            code.append(f"{label_end}:")
        
        return code
    
    def _generate_expression(self, node):
        """生成表达式代码"""
        return self._generate_node(node)
    
    def assemble(self, asm_code):
        """将汇编代码转换为机器码"""
        # 简化的汇编器实现
        lines = asm_code.split('\n')
        machine_code = []
        labels = {}
        pc = 0
        
        # 第一遍：收集标签
        for line in lines:
            line = line.strip()
            if not line or line.startswith(';'):
                continue
                
            if ':' in line:
                label = line.split(':')[0].strip()
                labels[label] = pc
            else:
                pc += self._instruction_size(line)
        
        # 第二遍：生成机器码
        pc = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith(';') or ':' in line:
                continue
                
            opcode, operands = self._parse_instruction(line)
            machine_code.append(opcode)
            
            if operands:
                for operand in operands:
                    if isinstance(operand, str) and operand in labels:
                        operand = labels[operand]
                    machine_code.append(operand)
            
            pc += 1 + (len(operands) if operands else 0)
        
        return bytes(machine_code)
    
    def _parse_instruction(self, line):
        """解析单条汇编指令"""
        parts = line.split()
        mnemonic = parts[0].upper()
        operands = parts[1:] if len(parts) > 1 else []
        
        # 转换为操作码
        opcode_map = {
            'HALT': 0x00,
            'LOAD': 0x01,
            'STORE': 0x02,
            'MOV': 0x03,
            'ADD': 0x04,
            'SUB': 0x05,
            'AND': 0x06,
            'OR': 0x07,
            'XOR': 0x08,
            'NOT': 0x09,
            'JMP': 0x0A,
            'JZ': 0x0B,
            'JC': 0x0C,
            'CALL': 0x0D,
            'RET': 0x0E,
            'INC': 0x0F,
            'LOADI': 0x11,
            'PUSH': 0x12,
            'POP': 0x13,
            'LOADX': 0x14,
            'STOREX': 0x15,
            'MOVI': 0x16,
            'CMP': 0x17,
            'DEC': 0x18,
            'SHL': 0x19,
            'SHR': 0x1A,
        }
        
        opcode = opcode_map.get(mnemonic, 0x00)
        
        # 处理操作数
        parsed_operands = []
        for operand in operands:
            if operand.startswith('R'):
                # 寄存器
                reg_num = int(operand[1:])
                parsed_operands.append(reg_num)
            elif operand.startswith('#'):
                # 立即数
                imm = int(operand[1:], 0)
                parsed_operands.append(imm)
            elif operand.startswith('[') and operand.endswith(']'):
                # 内存地址
                addr = int(operand[1:-1], 0)
                parsed_operands.append(addr)
            else:
                # 标签或其他符号
                parsed_operands.append(operand)
        
        return opcode, parsed_operands
    
    def _instruction_size(self, line):
        """计算指令大小"""
        opcode, operands = self._parse_instruction(line)
        return 1 + len(operands)

# 示例使用
if __name__ == "__main__":
    # 示例TCC程序
    source = """
    int add(int a, int b) {
        return a + b;
    }
    
    int main() {
        int x = 10;
        int y = 20;
        int z = add(x, y);
        return z;
    }
    """
    
    # 编译
    compiler = TCCCompiler(debug=True)
    asm_code = compiler.compile(source)
    print("生成的汇编代码:")
    print(asm_code)
    
    # 汇编为机器码
    machine_code = compiler.assemble(asm_code)
    print("\n生成的机器码:", machine_code)
    
    # 加载到TC-15 CPU并执行
    cpu = TC15_CPU(debug=True)
    cpu.load_program(machine_code)
    cpu.run()
    
    print("\n执行结果:")
    print("R0 =", cpu.registers[0])  # 返回值在R0中