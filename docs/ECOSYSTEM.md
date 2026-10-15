# Ziokt ecosystem / Ziokt 联邦生态

The source catalogue is `companions/ecosystem.json`; inspect it using `python3 -m ziokt companion catalog`. Runtime features are explicitly configured and remain disabled until their own native authorization and readiness checks pass.

组件目录通过 `python3 -m ziokt companion catalog` 查看。源码存在与运行就绪是两个不同状态；默认不启动服务，也不自动降级为直连。

## Integrated components / 集成部件

| Component | Current integration / 当前入口 |
|---|---|
| Shadow6 | Native Profiles, S6EPE, joint Virtual Broker node export, signed isolated Extensions on Go/Rust/Gleam/Ada/Nim/Idris |
| Corium | Native P2P/DHT, signed ledger facts, private ZKN, ZKC; `corix p2p get HASH [FILENAME]` verifies SHA-256 and rejects overwrite/symlinks |
| WATChat | `companions/watchat/WATChat-code`, browser ECDH/HKDF/AES-GCM sealed messages, fixed 2048-byte frames, contact fingerprint pins, durable ciphertext outbox, opt-in Ziokt inbox pull with signed event acknowledgements and content-digested attachments |
| SafeFS | `ziokt companion safefs`, scoped padded AEAD vault, signed encrypted community publication |
| ZDA / Ano | `ziokt companion ano`, exact bounded rational arithmetic, typed unknown evidence, all-required-claims authorization gates |
| UFS + DCPM | `ziokt companion ufsdcpm`, signed packages inside an encrypted UFS vault; coupled storage and package integrity remain native functions |
| TC-16 / TCC | `ziokt companion tc16`, real 16-bit registers and arithmetic, 16 registers, byte/word memory, stack/calls, BCD, interrupts, bounded capability calls; TCC functions, recursion, conditions and loops |
| ENEO ETP Core | Source in `companions/etp/src`, pinned local native `ziokt_gateway` adapter; explicit approved onion paths, no direct fallback. Minimal and integrated native builds, library tests and four-process onion forwarding pass in CI (run 38747367637); selected integrated features include TC-16/TCC, DSL, UFS, SafeFS, ENS and read-only contract RPC |
| SIM Manager | `companions/sim-manager/src`, encrypted IndexedDB state, migration of old plaintext after successful save, 304 bilingual static labels, PWA, private durable reminder gateway |
| Tri | `companions/tri/app` is a loopback development build and `/tri/` offline PWA, without third-party asset hosts or API-key injection; `ziokt companion tri put/get/publish` validates bounded snapshots and carries signed project files through SafeFS ciphertext |

Original archives remain unchanged in the home directory; SOURCE.json files record their SHA-256. Tri project interchange validates JSON data and stores signed community events with the machine snapshot encrypted by the app-scoped SafeFS key. The simulator runs only when a user explicitly starts its local/browser UI; publishing a project never runs imported code. Historical Python files containing root/BCC hooks, pickle/eval or incomplete server implementations are preserved as original reference and are not the modern runtime entry points. Some optional ETP bindings were absent from the supplied archive and fail explicitly when selected; they are not advertised as working implementations.

WATChat federation is opt-in through a fixed Ziokt bridge configuration. Each installation polls only conversations whose users and mutual contacts already exist locally, transfers sealed frames and up to two bounded attachment objects, verifies each attachment digest, persists the local message, then acknowledges the signed community event. A crash before the local save leaves the event unacknowledged for retry; duplicate event IDs are idempotent. The two installations must share the conversation's UUID identities and contact mapping. This adapter does not synchronize accounts or contact discovery.

原始压缩包保持不变；历史实现保留用于兼容参考，不作为现代运行入口。导入包里缺失的 ETP Lua/Shell/PowerShell 绑定会明确拒绝启用。

## TC-16 compatibility / TC-16 兼容性

The Python TC-16 ISA is `tc16.v1`. Its encoding intentionally resolves collisions in the old TC-15 bytecode; old bytecode is not silently relabelled. TCC supports bounded integer functions (including recursion), local variables, if/else, while, break/continue, short-circuit expressions and unsigned 16-bit arithmetic. `byte` and `bool` truncate explicitly. The preserved native ETP VM is renamed TC-16 and uses its own ETP wire/ISA contract; there is no implicit translation between those native formats.

TC-16 保留 BCD、标志位、栈、函数调用、中断、调试和受控系统调用。旧 TC-15 字节码编码存在冲突，需要显式转换。Python 与 ETP 原生 VM 的线格式不同，不自动互译。

## WATChat and SIM Manager PWA / 安卓安装与通知

Use HTTPS for phone installations. WATChat's process listens only on loopback: put a reviewed TLS reverse proxy in front, then set WATCHAT_ORIGIN to the exact public HTTPS origin. Set ADMIN_PASSWORD (at least 12 characters), a private DATA_DIR and ZIOKT_BRIDGE_CONFIG. Explicit standalone fixture mode uses ZIOKT_STANDALONE=1.

For backend Web Push, WATCHAT_PUSH_CONFIG references a private JSON file with `subject`, `publicKey`, `privateKey`, and optional `endpointHosts`. User permission is requested only through the notification button. Subscriptions are encrypted at rest and restricted to reviewed HTTPS push hosts; the server sends only a generic wakeup. Browser push providers can observe timing and endpoint identifiers. No account names, phone numbers or message content are included in notifications.

SIM Manager runs at `/sim/`. Its notification gateway uses the same authenticated `/api/reminders`, `/api/push-key` and `/api/push-subscription` interfaces. Serve the built SIM PWA behind the same HTTPS origin as the private gateway. Opaque due-time schedules survive gateway restart and retry delivery failures. Browser-only reminders work while the app is active; phone background delivery needs Web Push configuration. Experimental Notification Triggers must not be treated as a universal Android scheduler. Audible system notifications also depend on device/browser settings.

WATCHAT_WEBHOOK_CONFIG optionally selects one operator-reviewed HTTPS endpoint and an authentication secret of at least 32 characters. Webhooks contain an opaque event ID only, use an HMAC signature, reject private/reserved destinations, pin the resolved address for the request and do not follow redirects. Client-provided URLs do not authorize outbound delivery.

安卓端通过 HTTPS 页面“安装应用”或浏览器安装菜单安装。默认通知不显示发送者、正文、号码、PIN/PUK。浏览器关闭后推送需要部署配置与主动授权；无头测试环境不代表真实手机通知已经验证。SIM Manager 的服务端调度不会依赖实验性 Notification Trigger 的普遍可用性。

## Privacy boundaries / 隐私边界

Keyless relays only learn transport-adjacent peers and forward nested TLS/ciphertext. Random route selection, signed discovery admission, no direct fallback, padded small requests, one-time collectible receivers and separate receipt mailbox keys reduce exposed information. Retrying a ZKN gift preserves the same signed transaction and reconciles native inclusion before resending; it does not create a second gift. On-chain collectible identifiers and one-time owner addresses remain public ledger facts and can link successive transfers of the same collectible. This is not a proof of anonymity against a global observer, colluding relays, compromised endpoints or malicious browser code updates.

ZKN contains an immutable signed 0–F lucky digit. Private transfers are the default; legacy public transfer requires explicit selection. ZKC is issued by the current ZKN holder, with repeat serial 0 and unique positive decimal serials; no supply cap or fees are introduced. Packs seal signed edition references; contents must be retrieved by their verified immutable digests. Packer forwarding is bounded and content-addressed, not a guarantee of delivery when all peers are unavailable. Deep historical inclusion is bounded by the native 128-block observation window; stale facts are rejected, not treated as trusted confirmation.

中继不持有内容解密密钥，但网络地址、时间、流量长度桶与公开收藏件链仍有可观察信息。不能保证全局观察者无法关联、恶意节点无法丢包，或全网离线时仍即时送达。默认转赠、ZKC 签发与转发没有收费概念；资源预算仅用于限流和防滥用。

The imported ETP Noise pattern requested a hash outside the declared Snow 0.9 resolver contract. The active source uses the supported IK/25519/ChaChaPoly/BLAKE2s pattern; there is no algorithm fallback. See [Snow 0.9 documentation](https://docs.rs/crate/snow/0.9.6) and [hash choices](https://docs.rs/snow/0.9.6/snow/params/enum.HashChoice.html).

## AirGap / 隔离运行

Start a **fresh process** with `python3 -m ziokt --airgap companion catalog`, or set `ZIOKT_AIRGAP=1` before launching Ziokt. `python3 -m ziokt airgap` reports the enforced policy. Federation configurations may include `"network_mode":"airgap"`; `ziokt init --network-mode airgap ...` writes this setting. Loading such a configuration activates AirGap for the remainder of that process. Restart explicitly without the setting to return online; changing an environment variable in a running process cannot disable the guard.

AirGap denies Python socket operations (including loopback listeners, proxies and DNS) and external process execution. Native providers, Shadow6 transport handles, Tor/I2P connectors and ETP workers fail with `AIRGAP_DENIED` before starting. The native ETP engine/gateway and WATChat service also reject the AirGap environment independently. Existing services must be stopped before switching modes: activation does not terminate unrelated or already running processes. This application policy is not an OS sandbox for hostile native code, nor a substitute for physically disconnecting the device.

本地 Ano、TC-16/TCC、SafeFS、UFS/DCPM、Tri 数据包、签名检查点与组件密文交换可继续使用。通过人工介质搬运签名检查点，接收端先验证再导入；不会自动执行导入内容。网络发现、多跳、P2P 同步和服务器通知需要恢复联网进程。浏览器离线 PWA 缓存与此进程策略不同；隔离设备应事先安装所需 PWA，关闭在线服务并断开网络。

## Scoped component exchange / 组件互操作

`ziokt companion link send/receive` uses explicitly pinned signing keys, recipient mailbox keys and artifact kind grants. All 110 directed pairs of the ten catalogue components plus Tri share this encrypted artifact contract. Recipient receipts remain in local SQLite; they do not create extra federated receipt events. Repeated delivery returns the same local sealed object and schema. A combined regression runs TCC/TC-16 output through UFS/DCPM and SafeFS, replicates a signed community checkpoint, and validates Tri state and the Ano decision audit. This verifies artifact interoperability; feature-specific native readiness checks remain required.

Node.js CI and project version files select 24; package engines permit 22 as the fallback. The original archives and reference implementations are preserved. The modern active runtime is the maintained entry point; absent optional native bindings are not advertised as implemented.

原生统一调用、全部组件路由、SIM Manager 调度与公开 Engine Zero 奋斗页见 [部署说明](NATIVE-APPLICATIONS.md)。
