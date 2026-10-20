# 普通 NNTP 客户端

PhoNews、Thunderbird、slrn 和 tin 应连接 `nntp.ziokt.com` 的隐式 TLS 端口 563，启用服务器证书验证。119 为兼容性明文匿名只读入口，不接受密码。客户端发布/回复使用独立 Ziokt 新闻账户；不能使用 Gateway 管理凭证。

TLS 终止代理转发到独立的 IPv4 loopback 8120；公开明文 119 仅转发到不含账户的 8119。配置项 `nntp_tls_bridge` 必须明确启用 `allow_loopback_auth`，仅适用于受信任的本机 TLS 代理。不得把带凭证的后端端口直接暴露公网。若不使用终止代理，可直接配置 NNTP `tls.cert`/`tls.key`。

凭证配置 `nntp_tls_bridge_tokens`，每项只有 `account`、强随机 `token`、`scopes` 和可选 `senders`。投稿只需 `netnews:read`、`netnews:write`，不授予服务器联邦 `netnews:feed`。`senders` 指管理员为该账户绑定的邮件地址，例如 `owner@ziokt.com`；客户端可使用 `Display Name <owner@ziokt.com>`。未绑定地址会被拒绝，不能通过修改 From 冒充其他用户。

读取命令包括 GROUP、LIST ACTIVE/NEWSGROUPS/OVERVIEW.FMT、LISTGROUP、ARTICLE/HEAD/BODY/STAT、NEXT/LAST、OVER/HDR 及 XOVER/XHDR 别名。GROUP/LIST 的计数及高低水位来自实际可见持久记录，不以第一页 1000 条代替全组统计。LISTGROUP 分页读取编号，避免加载全部正文。OVER/HDR 仍受可选 `nntp_max_range` 单次预算限制；历史客户端应分批请求。

## 文本与附件

投稿接受纯文本或 multipart/mixed 的纯文本正文加最多 8 个显式附件。默认接收 wire 上限 12 MiB，解码附件总量 8 MiB，可通过 `max_article_bytes`（最大32 MiB）、`max_decoded_attachment_bytes`（最大16 MiB）调整；正文目前最多8192字节。wire 表示暂存到私有节点目录，MIME 解析并发为每节点一个，stdlib 解析内存仍受 wire 预算约束。预算拒绝会返回失败并关闭连接，不返回伪成功。

ARTICLE/BODY 的附件发送直接读取已校验的加密分块并流式 base64 编码；默认预算使用节点对象上限，可通过 `max_attachment_transfer_bytes` 下调。超过发送预算或尚未缓存的附件显示明确的对象/HTTPS引用，不能当作已经交付的二进制。普通客户端兼容标准 MIME；未实现 yEnc/uuencode 分卷重组，不声称支持所有传统二进制新闻格式。

服务器间 IHAVE/CHECK/TAKETHIS 要求独立 feed scope 和组白名单。原始来源以节点证明保留，不冒充上游作者签名。当前 feed 原文保留预算仍为16000字节，较大二进制跨节点传输应走原生 Content Fabric 分块路径；后续应补大原文对象引用模式。

真实 TCP 测试 `test_content_nntp_clients.py` 创建1003篇签名持久文章，验证跨1000编号导航、LISTGROUP、别名、256KiB二进制投稿/读回和 From 冒充拒绝。`test_netnews_feed.py` 验证实际 TLS 和联邦命令。它们不是 PhoNews/slrn/tin/Thunderbird 安装运行验收；实际应用版本与设备仍需单独记录。
