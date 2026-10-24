# 奋斗端第三模式：轻量分布式 C 对象编译

三个贡献入口为网络协作、Engine Zero 计算、OpenCI 轻量编译。自动选择不是第四类任务。Web 与 Windows 共用经 HTTPS 加载的受限 WebAssembly 编译器；Android 第三模式在独立应用进程的系统 WebView 渲染器中运行，前两种模式仍为 Java 原生单线程。Android 离开第三模式即停止编译，不暗中申请后台权限。所有平台都不执行任务产物。Windows 与 Android 可显式选择自己的 HTTPS 节点；切换节点会停止原任务并保留目标 Origin 的导航边界。

客户端先检测实际硬件架构：Windows 从 RuntimeInformation、Android 从 SUPPORTED_64_BIT_ABIS、普通浏览器从高熵 UA 架构取得。无法检测则拒绝，不能手选猜测。服务端检查客户端上报、已审批 Worker 架构与本节点 platform.machine 一致。远程硬件报告不等于硬件认证，不能因此取得 Trusted 身份。

目标架构与执行架构分开。默认仅允许节点同架构目标。只有 `light_compile.cross_compile=true` 且 Worker 编译器 profile 明确批准目标 bundle 时，才能领取对应交叉编译任务。当前正式支持 x86_64/aarch64 的预处理 C 翻译单元到 ELF64 `.o`；不声称支持任意 C++、所有 GCC 扩展或直接在手机上完整构建 LFS。

输入为 Content Fabric 的 `openci.light-source.v1` JSON，精确字段 `schema/name/source`，name 固定 unit.i，C 输入最多128 KiB，不接受 NUL。每任务 CPU1、内存64 MiB、期限最多20秒，输出仅 unit.o、最多1 MiB。固定 TinyCC 源码在 CI 通过 Emscripten 构建为 WASM，无宿主文件、动态执行、任意 Shell 或任务代码执行权限。编译器 manifest 及 JS/WASM 字节均校验 SHA-256。TinyCC LGPL 源码位置、精确 revision 和许可证随组件交付。

任务使用原生 OpenCI 的持久租约、项目 ACL、Content Fabric、Artifact Set、Ed25519 Worker 签名、独立故障域重建及 Trusted verifier。OCI 与 light-c 执行器互不领取对方任务。ELF 类型、目标 machine、输入与编译器承诺在完成入口再次核对。编译完成只记 completed；独立匹配、dCPM 交付、原生共识登记和贡献分结算是后续状态。

通过运营者原有的一次性限时邀请准入，专用密钥在设备生成；下载/导入 Worker 私有凭证。凭证只在页面内存使用，退出清除。Android 唯一宿主桥只允许把当前固定 HTTPS 页生成的限定凭证经系统文档选择器写出；不能读取宿主文件或执行命令。

Controller 配置示例（路径与摘要须由运营者显式提供）：

```json
{"light_compile":{"compiler_root":"/owner/releases/light-compiler","manifest_sha256":"<manifest文件SHA256>","cross_compile":false}}
```

奋斗服务与 Controller 分开运行；Controller 以 public_origin/public_origins 明确审批自身与奋斗页的 Origin；同源反向代理将 `/openci/*` 去前缀后转发至指定 Controller。不向浏览器提供 owner token。运行中的编译器必须来自全部通过的 `openci-light.yml` CI artifact，不在生产节点编译。轻量 C 对象核验与 ALFS 镜像验收是两条实测路径，不能互相替代。

每个节点的奋斗服务可通过明确的 loopback `openci_endpoint` 挂载自己的 `/openci/` 工作区和 API，不依赖固定生产域名。代理只连接运营者固定的本机 Controller，限制方法与消息/响应长度、不接受调用者指定上游、不注入管理凭证或 Cookie、不跟随重定向。Worker 的凭证和签名由 Controller 原样验权。CI 浏览器同时经过 Controller 根路径和该实际本机挂载完成 C→ELF、加密对象上传、签名完成回执与独立故障域结果核验。

Android 的第三模式要求设备上的 System WebView 支持 WebAssembly、Web Worker、BigInt 和 Ed25519 WebCrypto；OS 版本满足安装门槛并不单独保证其 WebView 具备这些能力。缺少能力时明确拒绝编译，不降级为不签名回执。前两种 Java 模式不依赖 WebView；物理 ARM 设备和各种厂商后台策略应分别记录实际验收结果。
