# 独立 OpenCI 服务

OpenCI 为独立进程。当前 Controller、Scheduler 状态层、CLI 和 OCI Runner 源码已实现；PoUW 可选且尚未接入。完整 Buildroot 验收工具与 Controller 的自动编排接入仍在实施，不把两条分离测试称为最终业务闭环。

## Controller

在仓库根目录安装既有 Python 依赖，然后：

```sh
python -m openci --root /srv/openci init
python -m openci --root /srv/openci serve --port 8768
```

init 只创建新文件，拒绝覆盖；owner.token 和 controller.json 为 0600，服务默认仅监听回环。远程访问应在运营者自己的 HTTPS 入口之后部署，客户端拒绝明文非回环地址。现阶段浏览器 Origin 请求拒绝，独立 GUI 尚在实施；REST/CLI 不使用 cookie、URL 参数凭据或默认公开读取。

## Worker

Controller 主机操作员执行：

```sh
python -m openci --root /srv/openci principal-add runner1 --role worker --worker node1 --project example
python -m openci --root /srv/openci worker-approve worker.json
```

`worker.json`：

```json
{"worker":"node1","arch":"x86_64","pool":"community","cpu":2,"memory_mb":1024,"slots":2,"projects":["example"]}
```

操作员须根据真实受控主机验证这些上限。远端自报 CPU/内存不产生调度权限；未知 Worker 默认拒绝，修改忙碌节点上限必须先排空。当前已实现操作员批准的资源上限，远端可信硬件证明与自动验证仍未实现。

通过运营者安全通道将该独立 Worker token 文件交给 Worker；不要交付 owner.token。Worker 上由操作员预载允许使用的 OCI 镜像，使用完整摘要，运行：

```sh
python -m openci --root /srv/openci-worker runner --server https://controller.example --token-file /srv/openci-worker/runner1.token --image docker.io/library/python@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
```

示例镜像只是 Runner CI 的 Python 执行环境，不是 Buildroot 或通用发行版工具链。Runner 需要可用 OCI Docker 引擎；失败不会回退到主机执行。无外网、只读根与源码、非 root 用户、去掉 capabilities、进程/CPU/内存/文件/临时目录/日志预算。构建写入 `/work`，交付文件写入 `/out`；当前源快照最多64MiB、工作tmpfs128MiB、交付tmpfs64MiB。这是通用小任务 Runner，大型 Buildroot 需要后续专用协调 Runner。

## 源码、流水线与制品

上传明确选择的源码 tar，禁止把主机凭据目录打包：

```sh
python -m openci --root /srv/openci upload --project example source.tar
```

返回原生 Content Fabric 对象 ID 和明文 SHA-256。Pipeline 的 source 使用该完整引用，不能只凭 URL 或不可验证文件名执行。

```json
{
  "schema":"openci.pipeline.v1",
  "project":"example",
  "nonce":"build-001",
  "source":{"object":"cf1-REPLACE_WITH_ACTUAL_OBJECT_ID","digest":"sha256:REPLACE_WITH_ACTUAL_DIGEST"},
  "tasks":[{
    "id":"test","needs":[],
    "image":"docker.io/library/python@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258",
    "argv":["python3","/src/test.py"],
    "arch":"x86_64","pool":"community","cpu":1,"memory_mb":128,"timeout":60,"attempts":2
  }]
}
```

上面的替换标记为文档输入参数，不是可执行测试产物。提交前必须填入实际上传返回值：

```sh
python -m openci --root /srv/openci submit pipeline.json
python -m openci --root /srv/openci inspect PIPELINE_ID
```

同项目 nonce+相同输入幂等；nonce 被不同输入复用会409。DAG 有环、未知依赖、浮动镜像、未批准 Worker、资源不足均不会伪装为运行成功。构建完成只进入 completed，独立验证记录另存，release 和 settlement 保持各自状态。

对象字节直接使用已有 Content Fabric → SafeFS/ChunkStore：应用账户按项目分离，分块、AEAD、摘要、持久化和预算沿用原生实现。没有另建明文制品 CAS。外部 UFS 服务与 dCPM 原生安装尚待后续 Adapter，不能将本地 ChunkStore 复用记为外部服务互通已完成。

## 恢复与迁移

- Controller 新建独立数据库，schema version 1；拒绝打开更新版本。SQLite WAL/FULL，领取、结果和审计在同一事务。每次调度/查询回收过期租约，受 attempts 上限约束。
- Worker 离线后租约到期才能重分配；旧租约不能提交新任务的结果。取消会撤销租约，Runner 心跳失败或取消时杀掉容器。
- Runner 启动时清理仅属于本状态目录标签的遗留容器；未确认的 finish 回执以0600日记保存，重启重试；失效回执保留为 rejected 供审计。每个目录只允许一个 CLI Runner 持有文件锁。
- Pipeline、任务与日志都有上限；全量日志作为原生对象持久保存，实时日志上限1MiB，最终日志上限16MiB。
- 备份时停止该独立服务或使用 SQLite online backup，同时备份 Content Fabric 数据与账户密钥。升级前备份整个私有状态目录；回滚恢复同版代码与一致状态备份。没有对既有 Corium/ETP/Shadow6 数据库做迁移。
- 当前自动运行的是手动提交和 API；Git/Webhook、定时触发、签名发布、GUI/MCP、多发行版专用 Runner 与原生 PoUW 仍在实施，不宣称全量完成。
