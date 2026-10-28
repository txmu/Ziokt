# 奋斗客户端下载镜像

`downloads.android` / `downloads.windows` 保持兼容旧的 HTTPS URL，也接受 `{github, server, sha256}`。两条链接均要求 HTTPS、无 URL 凭证；校验值必须为 64 位 SHA256。页面保留 GitHub Release，额外展示本服务器直链及校验值。

服务器镜像沿用 `tools/install_effort_downloads.py` 和 `tools/install_effort_android_downloads.py` 安装的不可变构建目录。它们仍是原来的开发安装包，不代表已重新签名或重新构建。地域未核实时不标为中国内地或承诺提速。

测试：`python3 -m unittest discover -s tests -p test_effort_mirror_config.py -v`。实际服务器下载的 APK/EXE 已逐字节 SHA256 核对。回滚：恢复旧 downloads 配置即可隐藏额外链接，不影响原有安装包或工作任务。
