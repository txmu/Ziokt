# PDF / CBZ 隔离阅读

使用现有 `library.reader.manifest` 和 `library.reader.chapter`，不新增重复MCP工具。Content Web、统一GUI和扩展共享同一翻页组件。章节接口对PDF/CBZ返回重新编码的JPEG页图；PDF还返回有界可选择文本。每次读原生加密对象时执行权限与SHA-256检查，解析后再次检查书目权限。引用ID不授予访问权。

## 隔离与预算

PDFium和Pillow的固定版本从 `requirements-reader.txt` 安装，必须使用预编译wheel。Linux解释器以 `-I` 运行：先加载可信依赖、UTF-16编码与图像插件，再启动seccomp默认拒绝。解析文档时不能打开文件、访问网络或派生进程，沿用192MiB地址空间/3CPU秒/8秒总时限/两进程并发。父进程同时有界读取stdout（256KiB）和stderr（16KiB），不将私人页图暂存磁盘。安装依赖不等于放宽沙箱。

源文件最多16MiB，最多1024页。PDF只渲染，不执行JavaScript、动作、外部链接或表单交互；图片最长边1200像素，JPEG输出最多100000字节。CBZ最多2048成员/32MiB展开量，每个图像4MiB/800万像素，拒绝重复/越界路径、加密项及异常压缩比。仅PNG/JPEG图像；允许小型ComicInfo.xml但不解析其内容。页名自然排序，不向浏览器发送原始归档或SVG/HTML。浏览器不把私人API响应加入Service Worker缓存。

## 安装

在独立、可追溯的venv中执行 `python -m pip install --only-binary=:all: -r requirements-reader.txt`。运行MCP与Content服务的操作者可设置绝对路径 `ZIOKT_DOCUMENT_PYTHON=/path/to/venv/bin/python`；该路径不是HTTP或MCP参数。没有Linux隔离或依赖时明确拒绝，不退回进程内不隔离解析。

## 本轮验证与限制

`test_raster_reader`使用真实PDFium/Pillow与操作系统隔离，验证实际JPEG像素、两页PDF与文本、CBZ分页、私有权限、路径/重复条目/炸弹/格式混淆拒绝和父进程输出上限。`content_browser_smoke.cjs`通过真实HTTP、SQLite、加密块和Chromium上传/阅读/翻页/保存位置。CI结果另记；普通桌面/Android/鸿蒙构建及真机未据此宣称通过。

尚不支持：超过预算的大文件流式Range阅读、加密PDF密码交互、PDF表单/批注编辑、CBZ WebP/GIF/TIFF、OCR。这是有界文档阅读能力，不是所有文档阅读要求已清零。

接口依据：[PDFium支持模型](https://pypdfium2-team.github.io/pypdfium2/readme.html)、[文本分页API](https://pypdfium2.readthedocs.io/en/stable/python_api.html)。这些依赖的版本与本项目源码、部署回执分别记录。
