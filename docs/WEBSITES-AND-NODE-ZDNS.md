# 节点对等的建站与访问入口

每个节点提供相同的 Gateway 网站入口和节点 ZDNS 解析器。访问者无需在操作系统或浏览器手工设置 ZDNS：

```
https://<所选节点>/gateway/corix/example/index.html
https://<所选节点>/corix/blog.team.example/posts/hello/
```

前一个路径也可直接使用 `/<Ziokt TLD>/<域名>/<文件>`；TLD 和完整域名分别对应其原生组件命名权威。`/api/gateway/sites` 返回支持的全部后缀、方式清单与当前节点是否已配置解析器。Gateway GUI 的应用中心与 Chromium/Firefox/Thunderbird 扩展均可输入所选节点、完整 Ziokt 域名及文件路径，生成同一地址；不要求把浏览流量交给固定网站。

| 方式 | 发布与读取 | 授权边界 |
| --- | --- | --- |
| 原生 Corium/Nomen 静态目录 | `corix site publish ./public --domain example`，文件摘要 manifest 经本机原生 NNS 发布并确认后访问 | 验证当前所有者签名、规范区块收录与文件 SHA256 |
| Hugo/Hexo/Jekyll/Astro/Eleventy/Zola/MkDocs/Pelican/Docusaurus/VitePress/VuePress/Next export/Gatsby | `python tools/prepare_static_blog.py` 汇总已经生成的静态输出，再由原生站点发布路径发布 | 节点不执行第三方生成器或服务端代码 |
| 手写静态站、Wiki 和博客导出 | 使用相同 files/index manifest；支持 clean URL、显式 SPA、404、JS 模块和显式 WASM | 共享 Gateway 使用不带 allow-same-origin 的沙箱，不能取得管理身份 |
| ZDNS 多层子域站点 | 原生注册中发布逐层签名 delegation，公开 component service object 指向静态 manifest | 每层委托、期限、父版本、所属网络及最终 public 分类逐一验证 |
| Content Fabric、Library、Netnews 应用 | 原有 capability/application API；独立内容服务及扩展统一使用相应节点的应用接口 | 私人藏书、会员内容和写入能力仍须独立凭证 |
| Shadow6、UFS/dCPM、TC-16 等组件服务 | ZDNS 对应组件的已配置原生命名源和服务描述 | 不跨组件借用 Corium 所有权，不把发现记录当作执行授权 |

没有 `dns_config` 时，具备完整原生路径的 Gateway 使用本节点的 Corium NNS 验证器；有配置时复用本节点多 realm ZDNS 的默认视图。独立部署脚本自动生成自己的 `dns.json` 并连接自己的数据库。不存在固定生产域名或“官方节点”解析回退。尚未安装的组件会返回不可用，不能借另一个组件的名义伪装服务。

原生旧版静态 files manifest 仅支持已注册根域，不会自动产生任意子域。带 ziokt_naming 的新式声明必须遵守显式服务公开性，不能借同时附带 files 绕过 authenticated 分类。路径穿越、编码斜线、过期注册、未绑定的 NNS 目标和私有站点均被拒绝。Gateway 只读取内容寻址对象，不根据域名记录代理任意 HTTP/IP 地址，不访问系统公共 DNS，也不解密私人描述。

单一 Gateway 共享 origin 适合公开阅读和隔离脚本。需要持久浏览器存储或 Service Worker 的站点应采用现有独立静态 origin 服务；不能通过公开请求开启与 Gateway 管理 API 共用权限的 allow-same-origin。
