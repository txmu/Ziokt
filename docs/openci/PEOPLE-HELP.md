# 人民助力：轻量浏览器网络协作

地理学习页沿用现有奋斗页地址。默认不启动计算或网络协作；一次点击开始，一次点击停止。界面只保留简短用量提示、状态和设置。经纬网课程在本地运行，不下载地图瓦片、字体、广告或分析脚本。

## 旧浏览器

`effort/relay.js` 和地理脚本使用 ES5、XMLHttpRequest、JSON；不要求 WebCrypto、Service Worker、Web Worker、fetch 或 WebAssembly。旧 CSS 提供颜色和单列布局回退。普通自动档在具备现有计算能力时选择计算，否则使用网络协作；也可以显式选择。浏览器仍必须能建立经过证书验证的 HTTPS，不能为兼容而关闭 TLS 校验或降低到过时的公共明文协议。

页面只处理受限参与码和不透明帧，不持有原生身份、内容解密或发布私钥。参与码只留在内存/表单，停止后清除运行中的连接引用，不写 localStorage、Cookie、URL 或日志。参与码不是匿名身份证明，也不授予任意代理权限。

## 原生接入

两个运营者分别部署固定接入点。入口接收本机原生应用的连接；出口只连接经过批准、锁定源摘要和服务锁的原生 Shadow6 stream：

```sh
python -m ziokt.relay_web --config /private/relay-a.json --port 8769 --ingress-port 8770
python -m ziokt.relay_web --config /private/relay-b.json --port 8769 --native-binding /private/native-binding.json
```

监听固定为回环地址，公开入口由运营者现有 HTTPS 反向代理转入；不自动申请域名、开放防火墙或启动 Tor/I2P。原生应用将自己的 **端到端 mTLS 字节流** 送入入口 `127.0.0.1:8770`，出口绑定提供对应协议的 Shadow6 原生服务。`native-binding.json` 使用已有 `shadow6-stream` 配置，必须设置 `require_s6epe: true`。适配器通过已有 `connect_native`/libshadow6 调用原生引擎，不重新实现 Shadow6 加密、连接或路由。

**S6EPE SDK 的应用流可能已经由 SDK 解开外层封装，因此 S6EPE 本身不能替代应用端到端 mTLS。不能把明文应用服务接入后声称浏览器看不到明文。** 当前传输核心不解密应用流，也不能仅凭字节格式证明流内部已经加密；部署准入必须核验实际应用端点和证书。真实测试使用独立端点 TLS 1.3 双向认证。

接入点配置，权限 0600：

```json
{
  "schema": "ziokt.browser-relay.v1",
  "origins": ["https://people.example.org"],
  "principals": {
    "phone-a": {"token_sha256": "OPERATORS_64_HEX_SHA256_OF_RANDOM_CAPABILITY"}
  }
}
```

占位字符串不是合法配置：运营者必须用 `secrets.token_urlsafe(36)` 等 CSPRNG 生成真实能力码，配置只写摘要。每个身份最多一个活跃会话；每次请求验证当前配置，另有后台撤销检查。不得将生产身份私钥放入参与码。

奋斗页配置增加 `relay_origins`，只列实际批准的两个或更多 HTTPS origin；该列表同时生成 CSP connect-src。没有批准节点时页面明确表示未配置，不伪装为已在贡献。参与码格式：

```json
{"v":1,"a":{"origin":"https://entry.example.org","token":"OPERATOR_ISSUED_CAPABILITY"},"b":{"origin":"https://exit.example.org","token":"OPERATOR_ISSUED_CAPABILITY"}}
```

以上为格式示意，不是可用凭证/域名。没有添加任何未经用户提供的 ziokt.com 子域或 sslip.io 别名。

## 资源、隐私与恢复

- 4 KiB 原生帧，每方向最多两帧在内存；单个半连接每方向 4 MiB，最长 300 秒。原生写入默认约束 8 KiB/s、8 KiB 突发，浏览器活动帧间隔 500 ms，空闲轮询 250 ms。不是无限公开代理。
- 有数据的 HTTP 读响应和写请求补齐到 6144 字节，减少末尾小帧的长度差异；不产生持续的无用大流量。填充不计入原生有效字节。此措施不能隐藏活动时序、端点 IP 或所有流量特征。
- 网络路径可由已有 Shadow6 原生服务选择。当前适配器未实现跨运营商多路径迷惑传输或证明 AS 独立性，也不能保证交换机旁监听者无法识别 HTTPS 流量。两接入点可能串谋；这里不宣称完整匿名性。
- 序号、重复确认、同一帧重试、冲突与乱序校验；只有原生 sendall 完成才回报 native_written。写入中途异常关闭连接，禁止对不确定的部分写入盲目重放。半关闭保留反向数据。
- 原生连接不跨进程重启保留。租约、字节预算、撤销或进程失败后必须由原生应用重建连接；不得把新 TCP/TLS 连接报告为旧连接连续恢复。
- 允许后台必须主动勾选。XHR 在浏览器允许时继续；可用时申请屏幕唤醒锁，并在停止时释放。没有音频/忙循环保活，不承诺绕过系统冻结。离开页面关闭会话；端点租约是最后保护。
- 传输计数不是有效服务证明、不可关联性证明或 PoUW 结算。当前会话计数只在内存，无链上奖励、无持久计量或贡献签名。接收方应用回执、反串谋、独立计量及原生贡献结算仍需完成。

## 验证与回滚

`test_relay_stream` / `test_relay_web` 使用真实 socket 和 HTTP，包含重试、乱序、半关闭、背压、限额、来源/凭证/会话边界。`tools/people_relay_browser_smoke.cjs` 在禁用 WebCrypto/SW/Worker/fetch 的真实浏览器中，经两套独立 HTTP 服务传输真实应用 mTLS 数据，并检查地图交互及手表/手机/桌面滚动。测试里的 HTTP 仅在回环；不是公共 TLS 部署证据。Shadow6 SDK 接线和 Android 32 位实体设备还没有该路径的验收证据。

无数据库迁移。关闭接入点会结束活跃连接；撤销凭证并移除奋斗页的 `relay_origins` 即停用新接入。回滚前停止活跃会话；保留原计算入口和原生服务。
