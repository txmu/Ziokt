# Ziokt 资讯订阅

同一个应用节点提供 RSS 2.0、Atom 和 JSON Feed 1.1；数据来自实际 Library、Netnews 数据库及经委托的原生 Community 论坛。尚未接入的 Corium、ETP、Wiki、Broadcast 不会被伪装为可用来源。

公开入口：

- `/feeds/all.atom`：已接入来源的统一订阅。
- `/feeds/library.rss`、`/feeds/netnews.atom`、`/feeds/netnews.json`。
- `/feeds/netnews.atom?group=ziokt.general`：单个新闻组。
- `/feeds/index.json`：格式与来源说明。
- `/feeds/subscriptions.opml`：授权订阅导出，不包含凭证。

三个后缀均适用于 `all`、`library`、`netnews`、`community`。社区入口必须配置原生账户委托并认证。`limit` 为 1–50，`offset` 为有界分页；这是近期更新入口，并非可靠消息队列或完整历史同步协议。文章正文预览最多 2000 字符，明确标注截断，保留原始 ID、来源与可用的原生签名证明。Community 无原始发布时间时，使用持久化首次观测时间并明确标记，不能当作作者发布时间。

## FreshRSS / Miniflux

在客户端添加公开 HTTPS 订阅地址即可读取，无须 Gateway 管理权限。私有订阅需在客户端认证设置中填写独立应用账户与 token，使用 HTTP Basic，禁止把凭证放入 URL。Basic 仅用于订阅入口，应用 API 仍使用 Bearer。必须使用 HTTPS；反向代理应避免记录 Authorization。配置 `feed_base_url` 为对外 HTTPS Origin，避免生成内部地址。

服务实施账户/作用域过滤、过期与撤回过滤、限速、有界输出、ETag/304。私有响应不缓存；匿名请求不能借用名为 public 或 anonymous 的真实用户身份。只输出本地授权可取的附件 enclosure；远端附件引用单独标记，不能声称已经可下载。私有附件仍使用授权内容下载工具，不保证订阅客户端能够自动携带所需的内容读取凭证。

`feeds.describe`、`feeds.items` 接入现有应用 API / MCP。`feeds:read` 仅授予读取本账户已授权资料的能力；不增加社区成员资格。

## 验证边界

`test_content_feeds.py` 使用实际 HTTP 服务验证 XML/JSON、ETag、私有隔离、撤回与 Community 原始证明。`ci/feed_clients.py` 在 CI 启动独立 FreshRSS 1.30.2、Miniflux 2.3.3 和 PostgreSQL 容器，要求三个格式的公开文章进入客户端实际存储，同时检查私有文章未导出。提交测试代码不代表客户端 CI 已通过，实际结果见相应运行记录。

规范参考：[RSS 2.0](https://www.rssboard.org/rss-specification)、[Atom RFC 4287](https://www.rfc-editor.org/rfc/rfc4287)、[JSON Feed 1.1](https://www.jsonfeed.org/version/1.1/)。
