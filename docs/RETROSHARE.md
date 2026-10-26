# RetroShare 原生衔接

已提供 MCP / Gateway 工具：retroshare_status、retroshare_friends、retroshare_online、retroshare_shares、retroshare_downloads。TG 的同一工具分发器也可以使用。后四项需要显式 retroshare:read scope。接口只读取现有原生状态，不自动导入好友、创建身份、共享目录或复制内容。

RetroShare 是独立运行的软件，需要启用其 JSON API。官方定义：
https://github.com/RetroShare/libretroshare/blob/master/src/retroshare/rsjsonapi.h
https://github.com/RetroShare/libretroshare/blob/master/src/retroshare/rspeers.h
https://github.com/RetroShare/libretroshare/blob/master/src/retroshare/rsfiles.h

在 owner-only MCP 配置中显式添加：

```json
{"retroshare":{"enabled":true,"endpoint":"http://127.0.0.1:9092","auth_file":"/absolute/private/retroshare-auth.json"}}
```

原生 JSON API 配置好对应账号后，创建权限为 0600 的 auth_file：

```json
{"username":"ziokt","password":"填写原生 JSON API 密码"}
```

仅允许 literal loopback；认证不走环境代理、不跟随跳转；响应有超时与大小上限。未配置显示 not_configured，认证/连接失败显示 unavailable，不宣称好友传输已验证。本轮使用上游头文件核对方法，并进行了回环协议、认证、权限与路由测试；本机未安装/配置真实 RetroShare，所以原生实例和好友传输仍待运营者实测。
