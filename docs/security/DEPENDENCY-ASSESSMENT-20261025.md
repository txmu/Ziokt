# 发布依赖与告警核对

此次评估使用 GitHub Dependabot 原始告警、实际 package-lock/Cargo.lock、npm audit 注册表结果和上游修复记录。它覆盖列出的组件与交付路径，不能表述为所有运行时和所有依赖都已完成独立审计。

- SimManager 实际构建目录为 companions/sim-manager/src；锁文件升级 fast-uri 到3.1.9、serialize-javascript 到7.1.3后，本次 npm audit 返回0条告警。原始机器可读结果摘要与锁文件 SHA256 位于相邻 RELEASE-DEPENDENCIES-20261025.json。
- ETP 实际代码在 companions/etp/src，锁定 PyO3 0.29.3（async-runtimes 0.29），不使用 original 目录的旧 PyO3。
- Linux GUI 的 Tauri/GTK 依赖仍需要 GLib 0.18 ABI。已从 Cargo.lock 校验的 crates.io 0.18.5 源码导入 vendor/glib，将 VariantStrIter::impl_get 的 C 输出指针改为可变指针，采用[上游修复](https://github.com/gtk-rs/gtk-rs-core/pull/1343)的同一变更。Cargo 的 path patch 明确选择该修复，原始 crate SHA256、文件补丁摘要与来源保存在 ZIOKT-BACKPORT.json。CI 使用优化构建实际执行正向和反向字符串迭代；本机只做源码、锁文件和补丁校验。
- companions/*/original 是用于对比的不可执行上游快照。现有告警大部分指向这些路径；生产构建和 CI 构建入口使用 src 路径。保留这些快照并不宣称其中旧依赖已安全升级，也不会将其作为上线程序交付入口。
- 轻量编译器交付包含锁定 TinyCC 的完整原始源码归档、构建脚本、封装 C 源码和许可证，manifest 记录其源码归档摘要；编译器 JS/WASM 另有实际字节摘要与镜像 ID。ALFS 使用固定官方书本、jhalfs commit 和软件包校验，并独立保留 CI/QEMU 证据。

发布门槛检查精确源码 revision 的所有实际 CI workflow，失败、取消或尚未完成的 revision 不能进入新的安装 catalog。历史 catalog 会重新核验现有条目的完整 revision 状态；历史不可变 Release 留作审计，不作为新的通过记录。公开制品摘要、源码提交、平台签名状态与具体运行验收分开记录。
