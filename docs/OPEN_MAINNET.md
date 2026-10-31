# 开放主网

主网包含 `ziokt-main` 与 `ziokt-dna-side-20261024`。加入节点自行生成两套身份密钥，
验证两条链的历史，然后启动 P2P、工作量出块与各自消费者。无需邀请、质押、贡献余额或管理员登记。
节点用稳定身份签署地址及公开 TLS 证书，已有节点自动认证新端点；公网 IP 变化会自动重新通告。

下载 `https://app.ziokt.com/mainnet/join_mainnet.py` 后，在有 Python 3、cryptography、
OpenSSL、Bash、curl、jq、SQLite 的服务器运行：

```sh
python3 join_mainnet.py --root "$PWD/ziokt-node" --business-chain dna --enable-services
```

`primary` 是另一种主要业务链选择。两种选择均创建两条链及两个消费者；身份密钥保存在
节点目录中。省略 `--enable-services` 可先生成并检查服务配置。引导包及 SHA-256 文件位于
`https://app.ziokt.com/mainnet/bootstrap.zip` 与 `bootstrap.zip.sha256`。

[图书馆与新闻组](https://read.ziokt.com/)支持直接创建普通账户，
[聊天](https://chat.ziokt.com/)保留开放注册。普通账户拥有自己的内容与讨论权限。
管理操作和其他账户的私人数据仍由各自所有者授权。

ZDNS 使用新用户自己的密钥签署注册，贡献扣除为零。注册内容直接绑定在原生链上，无须申请节点的对象上传权限：

```sh
python3 tools/register_public_name.py --name my-public-name --address YOUR_PUBLIC_IP --key-file ./name-owner.pem
```

添加 `--network ziokt-dna-side-20261024` 可在 DNA 业务链注册。默认 DoH 入口为
`https://dns.ziokt.com/dns-query`，DNA 入口为 `https://dns.ziokt.com/realms/dna/dns-query`。
命名密钥与原生所有者密钥保存在 `--key-file` 所在目录；后续更新继续使用这两把密钥。

Both chain consumers verify local canonical inclusion and current producer delegation. Confirmed `status.get` observations can be read after mining and confirmation delays; direct RNA ingress and native mutations retain their signed live execution window. Reorganizations replay read-only consumers idempotently, while consumers configured for native writes require review before resuming on a changed consumed branch.

Use `deploy.py mainnet` to join both public chains with persistent services, `mainnet --create --network NAME` to create a sovereign pair, and a creator-provided checksum-pinned bootstrap to join that pair. Each pair records its recommended mainnet IBC peers in `IBC.json`; foreign checkpoints are admitted by native governance. See the Releases repository for service lifecycle commands and [UFS protocol integration](UFS_PROTOCOLS.md) for the full native protocol set.
