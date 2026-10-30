# 公网地址变化

节点签名身份与 TLS 密钥独立于公网 IP。Corium 默认 `public_address_mode = auto`，
从有界 HTTPS 观测获取公网 IPv4，缓存五分钟；失败后短暂退避，不再通告过期公网地址
或云服务器的私网接口地址。特殊 NAT 映射可显式选择 `manual` 并指定 `public_ip`。

`tools/refresh_peer_addresses.py` 每分钟对两条链发送签名 `ANNOUNCE_ADDRESS`。
接收端仅采用真实 TCP 对端地址与签名中的监听端口，拒绝私网来源、过期声明和无效签名，
保留既有节点身份、信任等级及证书固定值。迁移地址时携带原固定证书，证书冲突会拒绝。
无须重新注册身份或修改共识。

安装示例（源脚本及状态根必须为实际部署路径）：

```sh
sudo python3 tools/refresh_peer_addresses.py --install-systemd \
  --source /srv/ziokt/bin/corix_v108.sh \
  --chain /srv/ziokt/corium ziokt-main \
  --chain /srv/ziokt/dna-sidechain ziokt-dna-side-20261024
```

定时服务按原生源文件所属用户运行。至少一个已知对等节点须仍可达；节点持续向其通告后，
对方会自动学习新路由。DNS 的 A/AAAA 记录仍由域名提供方管理，此服务不会声称已经更新 DNS。
