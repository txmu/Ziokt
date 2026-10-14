import { InstructionsMap } from './types';

export const INSTRUCTIONS: InstructionsMap = {
  '0': { name: 'HALT', desc: { en: 'Halts program execution (Privileged)', zh: '停止程序执行 (特权)' } },
  '1': { name: 'LOAD', desc: { en: 'Load value from memory [addr] to ACC', zh: '加载内存[addr]到ACC' } },
  '-1': { name: 'STORE', desc: { en: 'Store ACC value to memory [addr]', zh: '存储ACC到内存[addr]' } },
  '2': { name: 'ADD', desc: { en: 'ACC = ACC + value at [addr]', zh: 'ACC = ACC + [addr]' } },
  '-2': { name: 'SUB', desc: { en: 'ACC = ACC - value at [addr]', zh: 'ACC = ACC - [addr]' } },
  '3': { name: 'MUL', desc: { en: 'ACC = ACC × value at [addr]', zh: 'ACC = ACC × [addr]' } },
  '-3': { name: 'DIV', desc: { en: 'ACC = ACC ÷ value at [addr]', zh: 'ACC = ACC ÷ [addr]' } },
  '4': { name: 'MOD', desc: { en: 'ACC = ACC % value at [addr]', zh: 'ACC = ACC % [addr]' } },
  '-4': { name: 'AND', desc: { en: 'ACC = ACC & value at [addr]', zh: 'ACC = ACC & [addr]' } },
  '5': { name: 'OR', desc: { en: 'ACC = ACC | value at [addr]', zh: 'ACC = ACC | [addr]' } },
  '-5': { name: 'XOR', desc: { en: 'ACC = ACC ^ value at [addr]', zh: 'ACC = ACC ^ [addr]' } },
  '6': { name: 'NOT', desc: { en: 'ACC = ~ACC (Bitwise NOT)', zh: 'ACC = ~ACC (按位取反)' } },
  '-6': { name: 'SHL', desc: { en: 'ACC = ACC << value at [addr] (Shift Left)', zh: 'ACC = ACC << [addr] (左移)' } },
  '7': { name: 'SHR', desc: { en: 'ACC = ACC >> value at [addr] (Shift Right)', zh: 'ACC = ACC >> [addr] (右移)' } },
  '-7': { name: 'JMP', desc: { en: 'Unconditional jump to [addr]', zh: '无条件跳转到[addr]' } },
  '8': { name: 'JZ', desc: { en: 'Jump to [addr] if Zero flag is set', zh: 'Zero标志置位时跳转' } },
  '-8': { name: 'JNZ', desc: { en: 'Jump to [addr] if Zero flag is not set', zh: '非Zero时跳转' } },
  '9': { name: 'JN', desc: { en: 'Jump to [addr] if Negative flag is set', zh: 'Negative标志置位时跳转' } },
  '-9': { name: 'JNN', desc: { en: 'Jump to [addr] if Negative flag is not set', zh: '非Negative时跳转' } },
  '10': { name: 'CMP', desc: { en: 'Compare ACC with value at [addr] and set flags', zh: '比较ACC与[addr]的值并设置标志' } },
  '-10': { name: 'INC', desc: { en: 'Increment ACC (ACC++)', zh: 'ACC++' } },
  '11': { name: 'DEC', desc: { en: 'Decrement ACC (ACC--)', zh: 'ACC--' } },
  '-11': { name: 'PUSH', desc: { en: 'Push ACC onto the stack', zh: '压栈' } },
  '12': { name: 'POP', desc: { en: 'Pop from stack into ACC', zh: '出栈' } },
  '-12': { name: 'CALL', desc: { en: 'Call subroutine at [addr]', zh: '调用子程序' } },
  '13': { name: 'RET', desc: { en: 'Return from subroutine', zh: '子程序返回' } },
  '-13': { name: 'LOADB', desc: { en: 'Load value from memory [addr] to Register B', zh: '加载到B寄存器' } },
  '14': { name: 'STOREB', desc: { en: 'Store Register B value to memory [addr]', zh: '存储B寄存器' } },
  '-14': { name: 'LOADC', desc: { en: 'Load value from memory [addr] to Register C', zh: '加载到C寄存器' } },
  '15': { name: 'STOREC', desc: { en: 'Store Register C value to memory [addr]', zh: '存储C寄存器' } },
  '-15': { name: 'MOVAB', desc: { en: 'Move ACC to Register B (B = ACC)', zh: 'B = ACC' } },
  '16': { name: 'MOVBA', desc: { en: 'Move Register B to ACC (ACC = B)', zh: 'ACC = B' } },
  '-16': { name: 'MOVAC', desc: { en: 'Move ACC to Register C (C = ACC)', zh: 'C = ACC' } },
  '17': { name: 'INT', desc: { en: 'Trigger software interrupt [vector]', zh: '触发中断' } },
  '-17': { name: 'IRET', desc: { en: 'Return from interrupt', zh: '中断返回' } },
  '18': { name: 'IN', desc: { en: 'Read from peripheral port <operand>', zh: '从外设端口读取' } },
  '-18': { name: 'OUT', desc: { en: 'Write ACC to peripheral port <operand>', zh: '输出到外设端口' } },
  '19': { name: 'JEQ', desc: { en: 'Jump to [addr] if Equal (Zero flag is set)', zh: '相等时跳转 (JZ别名)' } },
  '-19': { name: 'JNE', desc: { en: 'Jump to [addr] if Not Equal (Zero flag is not set)', zh: '不相等时跳转 (JNZ别名)' } },
  '20': { name: 'LOADI', desc: { en: 'Load immediate value into ACC', zh: '加载立即数到ACC' } },
  '-20': { name: 'MOVCA', desc: { en: 'Move Register C to ACC (ACC = C)', zh: 'ACC = C' } },

  // Privileged Mode Instructions
  '21': { name: 'SETMB', desc: { en: 'Set MMU Memory Boundary from ACC (Privileged)', zh: '设置MMU内存边界 (特权)' } },
  '22': { name: 'SYSCALL', desc: { en: 'Software interrupt for user mode (INT 0)', zh: '用户模式软件中断 (INT 0)' } },
  '23': { name: 'CHPL', desc: { en: 'Change Privilege Level to [operand] (Privileged)', zh: '改变特权级别 (特权)' } },

  // New register and jump instructions
  '24': { name: 'LOADBI', desc: { en: 'Load immediate value into Register B (LOADB_IMM)', zh: '加载立即数到B寄存器' } },
  '-24': { name: 'LOADCI', desc: { en: 'Load immediate value into Register C (LOADC_IMM)', zh: '加载立即数到C寄存器' } },
  '25': { name: 'MOVBC', desc: { en: 'Move Register B to Register C (C = B)', zh: 'C = B' } },
  '26': { name: 'JC', desc: { en: 'Jump to [addr] if Carry flag is set', zh: 'Carry标志置位时跳转' } },
  '-26': { name: 'JNC', desc: { en: 'Jump to [addr] if Carry flag is not set', zh: '非Carry时跳转' } },
  
  // Indirect Addressing Instructions
  '27': { name: 'LOAD_IB', desc: { en: 'Load ACC from memory at address in Reg B', zh: 'ACC = Mem[B]' } },
  '-27': { name: 'STORE_IB', desc: { en: 'Store ACC to memory at address in Reg B', zh: 'Mem[B] = ACC' } },
  '28': { name: 'LOAD_IC', desc: { en: 'Load ACC from memory at address in Reg C', zh: 'ACC = Mem[C]' } },
  '-28': { name: 'STORE_IC', desc: { en: 'Store ACC to memory at address in Reg C', zh: 'Mem[C] = ACC' } },
  
  // Stack Pointer Manipulation
  '29': { name: 'MOVSP', desc: { en: 'Move ACC to Stack Pointer (SP = ACC)', zh: '设置栈指针 SP = ACC' } },

  // Float Mode Instructions
  '30': { name: 'FLOAD', desc: { en: 'Load mem[addr] to float reg F[B]', zh: '加载内存到浮点寄存器F[B]' } },
  '31': { name: 'FSTORE', desc: { en: 'Store float reg F[B] to mem[addr]', zh: '存储浮点寄存器F[B]到内存' } },
  '32': { name: 'FADD', desc: { en: 'F[B] = F[B] + F[C]', zh: '浮点加法 F[B]=F[B]+F[C]' } },
  '33': { name: 'FSUB', desc: { en: 'F[B] = F[B] - F[C]', zh: '浮点减法 F[B]=F[B]-F[C]' } },
  '34': { name: 'FMUL', desc: { en: 'F[B] = F[B] * F[C]', zh: '浮点乘法 F[B]=F[B]*F[C]' } },
  '35': { name: 'FDIV', desc: { en: 'F[B] = F[B] / F[C]', zh: '浮点除法 F[B]=F[B]/F[C]' } },
  '36': { name: 'LDACCF', desc: { en: 'Load ACC bits into float reg F[B]', zh: '加载ACC到浮点寄存器F[B]' } },
  '37': { name: 'STACCF', desc: { en: 'Store float reg F[B] bits into ACC', zh: '存储浮点寄存器F[B]到ACC' } },

  // Vector Mode Instructions
  '40': { name: 'VLOAD', desc: { en: 'Load mem[addr].. to vector reg V[B]', zh: '加载内存到向量寄存器V[B]' } },
  '41': { name: 'VSTORE', desc: { en: 'Store vector reg V[B] to mem[addr]..', zh: '存储向量寄存器V[B]到内存' } },
  '42': { name: 'VADD', desc: { en: 'V[ACC] = V[B] + V[C] element-wise', zh: '向量加法 V[ACC]=V[B]+V[C]' } },
  '43': { name: 'VSUB', desc: { en: 'V[ACC] = V[B] - V[C] element-wise', zh: '向量减法 V[ACC]=V[B]-V[C]' } },
  '44': { name: 'VMUL', desc: { en: 'V[ACC] = V[B] * V[C] element-wise', zh: '向量乘法 V[ACC]=V[B]*V[C]' } },

  // DMA Instructions
  '50': { name: 'DMA_START', desc: { en: 'Start DMA: ACC=count, B=src, C=dest', zh: '启动DMA: ACC=数量, B=源, C=目标' } },

  // Heap Instructions
  '51': { name: 'ALLOC', desc: { en: 'Allocate heap memory. ACC=size. Returns addr in ACC (Privileged)', zh: '分配堆内存. ACC=大小. ACC返回地址 (特权)' } },
  '-51': { name: 'FREE', desc: { en: 'Free heap memory. ACC=addr. (Privileged)', zh: '释放堆内存. ACC=地址 (特权)' } },

  // Extended Memory Instructions
  '60': { name: 'EXT_LOAD', desc: { en: 'Load value from Extended Memory [B] to ACC', zh: '从扩展内存[B]加载到ACC' } },
  '61': { name: 'EXT_STORE', desc: { en: 'Store ACC value to Extended Memory [B]', zh: '存储ACC到扩展内存[B]' } },

  // Hard Disk Instructions
  '70': { name: 'DISK_CMD', desc: { en: 'Disk Command. ACC=cmd, B=diskId, C=param1, [addr]=param2', zh: '磁盘命令. ACC=命令, B=磁盘ID, C=参数1, [addr]=参数2' } },

  // Ternary Expansion Memory (TEM) Instructions
  '80': { name: 'TLOAD', desc: { en: 'Load from Ternary Expansion Memory [addr] to ACC (Privileged)', zh: '从三进制扩展内存[addr]加载到ACC (特权)' } },
  '-80': { name: 'TSTORE', desc: { en: 'Store sign of ACC to Ternary Expansion Memory [addr] (Privileged)', zh: '存储ACC符号到三进制扩展内存[addr] (特权)' } },
  '81': { name: 'TADD', desc: { en: 'ACC = ACC + TEM value at [addr] (Privileged)', zh: 'ACC = ACC + TEM[addr] (特权)' } },
  '-81': { name: 'TNEG', desc: { en: 'Negate trit at TEM [addr] (Privileged)', zh: '反转TEM[addr]的三进制值 (特权)' } },
  '82': { name: 'TCMP', desc: { en: 'Compare ACC with TEM value at [addr] (Privileged)', zh: '比较ACC与TEM[addr]的值 (特权)' } },
  '83': { name: 'TDMA_MT', desc: { en: 'Start DMA Main Mem -> TEM. ACC=count, B=mem, C=tem (Privileged)', zh: '启动DMA 主存->TEM (特权)' } },
  '-83': { name: 'TDMA_TM', desc: { en: 'Start DMA TEM -> Main Mem. ACC=count, B=tem, C=mem (Privileged)', zh: '启动DMA TEM->主存 (特权)' } },
  '84': { name: 'SETTB', desc: { en: 'Set TEM Boundary from ACC (Privileged)', zh: '设置TEM边界 (特权)' } },
};

export const EXAMPLES: { [key:string]: { name: string; desc: string; code: string } } = {
  'add': { name: 'Addition', desc: 'Adds two numbers from memory.', code: `// Adds mem[46] (5) and mem[47] (3)
// Result stored in mem[45]
LOAD 46
ADD 47
STORE 45
HALT`},
  'factorial': { name: 'Factorial (Recursive)', desc: 'Calculates factorial recursively.', code: `// Calculates factorial of N (e.g., 4)
// Result will be in ACC after HALT
LOADI 4
CALL factorial
STORE 45 // Store result 24 in mem[45]
HALT

factorial:
  CMP 40      // Compare n with 1
  JEQ base_case // if n == 1, jump to base case
  
  PUSH 0      // Push n onto stack
  DEC         // n-1
  CALL factorial // factorial(n-1)
  
  MOVBA       // B = ACC (result of inner call)
  POP         // ACC = n (from stack)
  MUL 1       // ACC = n * B
  RET

base_case:
  LOADI 1
  RET

// Data section
// mem[40] = 1 (for comparison)` },
   'subroutine': { name: 'Subroutine Call', desc: 'Demonstrates CALL and RET.', code: `LOADI 5
CALL multiplyByTwo
STORE 50 // Store result (10)

HALT

// Subroutine definition
multiplyByTwo:
  ADD 0 // ACC = ACC + ACC
  RET`},
  'interrupt': { name: 'Interrupt Test', desc: 'Triggers a software interrupt.', code: `// Set Interrupt Vector Table
// Vector 1 handler is at address 30
LOADI 30
STORE 113 // 112 + 1 (vector 1) - Adjusted for new IVT base

// Trigger interrupt
INT 1 
HALT

// Interrupt Service Routine at addr 30
// isr:
//   LOADI 123
//   STORE 50 // Store a value to show it ran
//   IRET` },
  'privileged': { name: 'Privileged Mode', desc: 'Demonstrates memory protection.', code: `// Kernel space sets up protection
// User space: 0-63, Kernel: 64-127
LOADI 64
SETMB
CHPL 1    // Drop to user level

// --- User code begins ---
// This will succeed (User space)
LOADI 100
STORE 25

// This will fail and trigger interrupt 2
// (General Protection Fault)
STORE 70

HALT`},
  'float': { name: 'Floating Point', desc: 'Calculates Pi using Leibniz formula.', code: `// Calculate Pi/4 = 1 - 1/3 + 1/5 - 1/7...
// Requires Float Mode
LOADI 1
LDACCF 0   // f0 = 1.0 (term)
LOADI 3
LDACCF 1   // f1 = 3.0 (denominator)
LOADI 0
LDACCF 2   // f2 = 0.0 (sum)
LOADI -1
LDACCF 3   // f3 = -1.0 (sign)

// B=term, C=denominator, ACC=sum
loop:
  LOADB 0 // f0
  LOADC 2 // f2
  FADD    // f0 = f0 + f2 -> sum in f0
  STOREB 2 // Store sum back to f2

  LOADB 1 // f1
  LOADI 2
  ADD 0   // ACC = 2
  LDACCF 1 // f1 += 2.0
  
  LOADB 0  // f0 (term)
  LOADC 3  // f3 (sign)
  FMUL     // f0 = term * -1
  STOREB 0 // Store sign flip
  
  LOADB 0  // f0 (term)
  LOADC 1  // f1 (denom)
  FDIV     // f0 = term / denom
  STOREB 0 // Store new term

  // Loop 10 times for approximation
  LOAD 40
  INC
  STORE 40
  CMP 41
  JNE loop
  
// Result for Pi/4 is in f2
// Multiply by 4
LOADI 4
LDACCF 1 // f1 = 4.0
LOADB 2
LOADC 1
FMUL
STACCF 0 // Result for Pi in ACC

HALT
// mem[40] = loop counter
// mem[41] = 10` },
  'vector': { name: 'Vector Processing', desc: 'Adds two arrays using SIMD.', code: `// Adds vector1 and vector2, stores in vector3
// Requires Vector Mode
LOADI 30 // addr of vector1
LOADB 0
VLOAD 0  // v0 = [mem[30]..]

LOADI 34 // addr of vector2
LOADB 0
VLOAD 1  // v1 = [mem[34]..]

LOADB 1  // B=1 (v1)
LOADC 0  // C=0 (v0)
LOADI 2  // ACC=2 (dest v2)
VADD     // v2 = v0 + v1

LOADI 38 // addr of vector3
LOADB 0
VSTORE 2 // mem[38].. = v2

HALT

// Data section
// mem[30]: 1, 2, 3, 4 (vector1)
// mem[34]: 5, 6, 7, 8 (vector2)
// mem[38]: result will be 6, 8, 10, 12`},
  'dma': { name: 'DMA Transfer', desc: 'Copies memory using DMA controller.', code: `// Copy 5 values from addr 30 to 40
// Requires DMA Mode
LOADI 5  // Count
LOADB 30 // Source
LOADC 40 // Destination
DMA_START

// CPU can do other work here, e.g., a loop
// We'll just wait for the DMA interrupt
// The DMA completion ISR will halt the CPU
loop:
  JMP loop
  
// DMA completion interrupt (vector 4)
// handler should be at mem[116]
// isr: HALT`},
  'heap': { name: 'Heap Allocation', desc: 'Demonstrates dynamic memory management.', code: `// Requires Privileged Mode
// 1. Allocate a block of size 3
LOADI 3
ALLOC
STORE 30 // Store ptr1

// 2. Allocate another block of size 4
LOADI 4
ALLOC
STORE 31 // Store ptr2

// 3. Write to the first block
LOAD 30 // ptr1
MOVBA  // B = ptr1
LOADI 111
STORE_IB // mem[ptr1] = 111
LOADB 30
INC
MOVAB
MOVBA
LOADI 222
STORE_IB // mem[ptr1+1] = 222

// 4. Free the first block
LOAD 30
FREE

// 5. Allocate a new block of size 2
// This should reuse the recently freed block
LOADI 2
ALLOC
STORE 32 // Store ptr3

HALT`},
  'storage': { name: 'Disk & Extended RAM', desc: 'Writes to Ext RAM, then copies to disk.', code: `// Assumes Ext RAM (1024 words) and Disk 0 are loaded.
// Writes values to extended RAM
LOADI 100
LOADB 200 // Ext RAM address
loop_ext_ram:
  EXT_STORE 0
  INC
  LOADC 0   // C = ACC
  MOVBA     // B = REG B
  INC
  MOVAB     // ACC = B
  CMP 40    // Compare with 10 (loop count)
  JNE loop_ext_ram

// Now, copy from extended RAM to disk 0
// Using DMA for this would be faster!
// This example uses a manual copy loop.

// DISK_CMD: cmd=1 (WRITE), diskId=0 in B
// C=memAddr, [addr]=diskAddr, count=10 in temp reg
LOADI 1   // WRITE command
LOADB 0   // Disk 0
LOADC 20  // Source data in main memory
LOADI 100 // Disk address
STORE 42  // Store disk address
DISK_CMD 42 // Start write of block at mem[20]

// Wait for disk interrupt (vector 5)
wait_disk:
  JMP wait_disk

// Disk ISR at mem[117] (IVT Base 112 + 5)
// isr: HALT`},
 'tem_demo': { name: 'Ternary Memory', desc: 'Demonstrates Ternary Expansion Memory (TEM).', code: `// Ternary Expansion Memory Demo
// Requires TEM Enabled & Privileged Mode

// Set TEM boundary. Kernel space from 700 onwards
LOADI 700
SETTB

// Store -1, 0, 1 into TEM
LOADI -1
TSTORE 10 // TEM[10] = -1
LOADI 0
TSTORE 11 // TEM[11] = 0
LOADI 1
TSTORE 12 // TEM[12] = 1

// Load from TEM and add
TLOAD 10 // ACC = -1
TADD 12  // ACC = -1 + TEM[12] = -1 + 1 = 0
STORE 50 // mem[50] = 0

// Negate a TEM value
TNEG 10  // TEM[10] becomes 1
TLOAD 10 // ACC = 1
STORE 51 // mem[51] = 1

// This will fail (user code writing to kernel TEM)
CHPL 1
LOADI 1
TSTORE 710 // Triggers protection fault

HALT`},
 'graphics_demo': { name: 'Graphics & Input', desc: 'Draws on the pixel display and handles clicks.', code: `// Graphics & Input Demo
// Set IVT[9] (112+9=121)
LOADI click_isr
STORE 121

// Move Stack to safe area (105) to avoid code/data collision
LOADI 105
MOVSP

// Init Constant 16 at address 101
LOADI 16
STORE 101

// Init Flag at address 100
LOADI 0
STORE 100

// Main Loop
LOADI 0
MOVAB // B = X = 0

loop_x:
  LOADI 0
  MOVAC // C = Y = 0
  
  loop_y:
    // Draw Pixel (X=B, Y=C)
    MOVBA
    OUT 10 // Set X
    MOVCA
    OUT 11 // Set Y
    
    // Color Logic
    LOAD 100 // Load Flag
    JNE draw_red // If flag != 0, red
    LOADI 255 // Blue
    JMP draw_pixel
  
  draw_red:
    LOADI 16711680 // Red
  
  draw_pixel:
    OUT 12 // Set Color & Draw
    
    // Increment Y (C)
    MOVCA
    INC
    MOVAC
    // Check Y < 16
    CMP 101 // Compare with constant 16
    JNE loop_y
    
    // Increment X (B)
    MOVBA
    INC
    MOVAB
    // Check X < 16
    CMP 101
    JNE loop_x

// Wait loop
wait_inf:
  JMP wait_inf

// Click Interrupt Handler
click_isr:
  PUSH      // Save ACC
  LOADI 1
  STORE 100 // Set Flag = 1
  POP       // Restore ACC
  IRET

// Data Addresses:
// 100: Flag
// 101: Constant 16
// 105: Stack Top
// 121: IVT[9]
`},
'keyboard_echo': { name: 'Keyboard Echo', desc: 'Echoes keyboard input to the TTY display using interrupts.', code: `// Setup keyboard interrupt handler
LOADI kbd_handler
STORE 118 // IVT for vector 6 (112+6)

// Wait for interrupts
loop:
  JMP loop
  
kbd_handler:
  IN 0     // Read char from kbd buffer into ACC
  OUT 0    // Write char from ACC to TTY
  
  // Check for newline (char code 10)
  CMP 40   // Compare with 10
  JNE continue
  
  // If newline, print "> "
  LOADI 62 // '>'
  OUT 0
  LOADI 32 // ' '
  OUT 0
  
continue:
  IRET

// Data
// mem[40]: 10`},
};