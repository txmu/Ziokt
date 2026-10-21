# Buildroot / distcc / QEMU 验收（只在 CI）

工作流：`.github/workflows/openci-buildroot.yml`。首轮运行：
[CI 39506625922](https://github.com/txmu/Ziokt/actions/runs/39506625922)，源码提交 `048a2d6`，创建记录时状态为运行中，不能记为通过。

通过 workflow_dispatch 选择 `all`、`x86_64` 或 `aarch64`。本机脚本通过 `GITHUB_ACTIONS` 环境条件拒绝普通执行；开发会话只检查语法。工作流不使用生产发布密钥、不触发 Corium 交易、不修改正在运行的 Ziokt 节点。

## 固定输入

`ci/openci/buildroot.lock.json` 固定官方 Buildroot 2025.02.18 LTS 的完整源码提交 `d030e36bbc9669230c015be971b14b6e062cfdde`。采用该提交已有的 `qemu_x86_64_defconfig` 和 `qemu_aarch64_virt_defconfig`；有效 `.config` 随证据保存，而非重新手写另一套板级配置。

对照来源：[Buildroot 下载页](https://buildroot.org/download.html)、[官方手册](https://buildroot.org/downloads/manual/manual.html)、[distccd 手册](https://www.distcc.org/man/distccd_1.html)。原生 Buildroot 负责 host、staging/sysroot、软件包安装 hook、内核、rootfs 及 post-image 的顺序；不跨节点拼接这些目录。

## 实际执行路径

1. 在临时 GitHub VM 安装工具，获取并校验固定源码提交。
2. 从上游 defconfig 生成配置，启用 ccache，加入只包含提交标识的 rootfs overlay；QEMU 使用 CI 提供的二进制。
3. Buildroot 准备本架构交叉工具链与 host ccache。
4. 启动两个仅监听回环的 distccd 进程，限定编译器清单、并发及任务寿命。两者使用同一交叉工具链。普通 distcc 模式，未使用 pump。
5. 对相同源码和编译参数分别做本地与两个 Worker 远程编译并逐字节比较对象；禁止 distcc 静默本地回退。注入不可连接 Worker，要求明确失败，然后恢复健康 Worker。
6. `CCACHE_PREFIX=distcc` 使后续缓存未命中的编译分发；Buildroot 继续协调完整镜像构建。
7. 检查真实远程编译数量超过探针数，并要求真实 ccache 命中。
8. QEMU 用串口登录，核对镜像里的本次提交标识、proc/net 设备与网络探针，检查 panic/Oops，再正常关机。
9. 输出原始日志、配置、工具链树摘要、制品 SHA-256、Buildroot 包信息、基础 CycloneDX 软件清单与机器可读构建证据。失败时仍上传已产生的日志。

## 不夸大的边界

两个 Worker 是同一临时 CI VM 中的独立进程；这验证真实 distcc 通信和交叉编译，尚未验证异构多宿主 Worker、SSH/Shadow6 认证传输、恶意社区节点、真实加速比或公网部署。CI VM 隔离不代表已经实现 OpenCI 的社区容器隔离。

工具链树摘要在构建后记录；完整工具链缓存、跨节点预登记身份比较与远端资源证明仍待实现。下载缓存依赖 Buildroot 原生包哈希验证；ccache 是性能缓存，不能作为可信结果验证器。

QEMU 测试覆盖串口、rootfs 标识、内核错误检查和用户网络探针。SSH、具体业务服务及外部硬件 Runner 未验收。基础软件清单未补全许可证和依赖关系，不等于完整供应链审核。

`build-evidence.json` 明确保持以下字段为 false：可复现构建、软件安全、Ziokt 原生内容存储、签名发布、Corium 贡献验证、全量任务完成。GitHub artifact 上传不能替代 UFS/dCPM 原生安装和 PoUW 结算。

## 故障与恢复

任一必需命令失败使 job 失败；工具链、镜像或启动失败不记为构建成功。distccd 清理只终止本次启动的 PID。QEMU 使用临时快照，不更改交付的 rootfs 原件。重试可复用经 Buildroot 验证的下载缓存与按架构区分的 ccache；不复用跨任务 staging/target 目录。

当前重试由 GitHub Actions 负责。Controller 租约、跨节点任务恢复、独立验证服务与原生存储交付仍属于未实现的 OpenCI 平台工作。

### Compiler routing correction

The first resumed x86_64 build progressed through the toolchain/packages and
failed in Linux 6.12.27 host objtool `libsubcmd/parse-options.c`. Its fallthrough
annotations are comments. Ordinary distcc preprocessing removed those comments,
so host GCC's `-Werror=implicit-fallthrough` rejected valid host source. See the
[actual Linux source](https://github.com/gregkh/linux/blob/v6.12.27/tools/lib/subcmd/parse-options.c)
and [GCC's warning semantics](https://gcc.gnu.org/onlinedocs/gcc-12.2.0/gcc/Warning-Options.html).

The ccache prefix now distributes only absolute, approved Buildroot target
GCC/G++ entrypoints from the prepared toolchain directory. Native host compilers
remain on the dedicated coordinator. A CI-only host fallthrough regression probe
keeps warnings enabled, while target probes still require real distcc with local
fallback disabled. Routing decisions are recorded in `compiler-routing.jsonl`.
Probe compilation counts are captured before the build, so final evidence must
show additional successful remote compilations beyond that actual baseline.
This avoids treating a larger probe suite as proof that the build used distcc.

### Retained firmware re-verification

Run 39541559605 successfully produced the ARM64 kernel/root filesystem and
reached a real guest root shell. Its serial harness then timed out because it
expected one carriage return, while the actual PTY emitted `\r\r\n` after the
assertion marker. `OPENCI_BOOT_OK` was present in the actual serial buffer; the
network assertion was not reached, so that run remains failed.

The marker parser now accepts serial CR expansion while rejecting echoed
commands and prefixed/suffixed marker text. QEMU remains CI-only. The manual
`openci-qemu-recheck.yml` workflow downloads retained **real** image artifacts
from a selected same-repository Buildroot run, records its original build commit
and image hashes, and reruns serial/rootfs/network/shutdown assertions on CI.
It does not rebuild images or claim that a failed source run passed. Separate
artifact/run references distinguish build evidence from re-verification evidence.
