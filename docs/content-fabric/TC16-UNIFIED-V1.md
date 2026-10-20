# TC-16 家族与 Unified v1

TC-16 是家族名称，不是二进制兼容保证。旧裸程序继续由原执行器处理；不进行猜测或自动转换。

|目标|ISA|ABI|负载格式|
|---|---|---|---|
|tc16-python-legacy|tc16-python-v1|tc16-python-abi-v1|tc16-python-raw-v1|
|tc16-etp-legacy|tc16-etp-v1|tc16-etp-abi-v1|tc16-etp-raw-v1|
|tc16-unified-v1|tc16-unified-v1|tc16-unified-abi-v1|tc16-package-v1|

规范化操作码表见 `spec/tc16/unified-v1.json`。Unified v1 固定现有 Python TC-16 的 44 条指令编码与语义；ETP 增加独立 Rust 执行器，不改变原 `tc16_tcc`。不得把原 ETP 的 0x30 MOVI 与 Python/Unified 的 0x02 MOVI 混用。

## 程序头

8 字节 ASCII `TC16PKG1`，随后 4 字节大端无符号头长度，规范 JSON 头，再跟机器码。头只允许：isa_id、abi_id、binary_format、capability_profile、entrypoint、code_size、sha256。头不超过 4096 字节；机器码 1..65536 字节。入口必须位于代码内，大小与 SHA-256 必须一致。包装旧负载只增加目标标识，不改变旧负载机器码。

## 状态、内存和异常

16 个无符号 16 位寄存器 R0..R15；64 KiB 字节内存；16 位字的小端读写；非对齐字访问允许，但不能越界。SP 是执行器内部整数，初值 65536；GETSP 映射为低 16 位。向下增长的栈每次压入两字节。PC 不在内存边界时抛 TC16_MEMORY，不循环回零。

运算截断为 16 位。标志：Z=1、C=2、S=4、O=8、T=16、I=32、H=64、P=128。SUB/CMP 的 C 表示借位；P 表示整个 16 位结果中置位数为偶数。MOV/MOVI/LOAD/STORE 不改变算术标志。算术/逻辑标志更新保留 I/T；移位零位保留 C。BCD 是四位压缩十进制；非法十进制半字节抛 TC16_BCD。

异常码包括 INVALID_TC16、TC16_MEMORY、TC16_STACK、TC16_BCD、TC16_CAPABILITY、TC16_ARITHMETIC。异常中已发生的取指、内存或栈状态变更不回滚；失败指令不增加 cycles。HALT 计一个周期。预算耗尽返回未停止和 budget_exhausted，不伪造 HALT。差分结果比较寄存器、PC/SP、标志、模式、周期、异常、输出和整个内存的 SHA-256。

## ABI 与能力

TCC 使用 R0..R7 传递最多八个字参数，R0 返回；R15 为帧指针并由被调用者恢复；R0..R14 为调用者保存的临时寄存器。CALL 压入返回 PC，RET 弹出；栈参数和可变参数暂不支持。所有 int/word/ptr 为 16 位，byte/bool 使用现有 TCC 截断规则。

pure-v1 不授予任何 SYS。stdout-u16-v1 只授予 SYS 1：把 R0 的无符号十进制字符串追加到输出记录，不访问主机 stdout。不存在隐式 MMIO、主机文件、网络或合约存储权限。中断仅由受控宿主显式注入；公开服务描述仍禁止寄存器、内存、trace 等执行状态。

## 编译与执行

`TCCCompiler.compile_binary(source, target=..., profile=...)` 生成包装程序；已有 `compile()` 返回汇编的约定保持不变。Python 编译器目前能生成 Python Legacy 与 Unified。ETP Legacy 需要其原生编译器；显式请求但未连接该编译器时返回 TC16_TARGET_UNAVAILABLE，绝不返回不兼容机器码。

MCP：`applications_tc16_compile`、`applications_tc16_execute`，必须获得 applications:write，且启用 Content Fabric。执行接口只接受显式包装的程序。Rust runner 仅接受 Unified。

## 验证边界

Python 测试、轻量独立 Rust 源码差分与完整 ETP 工程 CI 分别报告。独立编译不证明原生 ETP 特性组合、网络入口或所有旧 ETP 程序已经兼容。
