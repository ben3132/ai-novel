# IP考据信源采集与证据处理工具箱

外部 Agent 接入时先阅读 `AGENTS.md` 和 `docs/AGENT_INTEGRATION_GUIDE.md`，或调用
`{"operation":"get_agent_guidance"}`。本项目不内置大模型，研究判断与动态信源
发现由接入 Agent 负责。

采集层只负责获取原始数据、写入 `raw_content` 和补充来源元数据；处理层在独立
`processed/` 中执行介质解析、确定性切片和索引，绝不覆盖原件。项目不内置 LLM。
L1/11/L2/L3/L4 均可按固定等级归档；只有 L4 强制排除设定推理。

文本响应保持响应原文；PDF、图片等二进制响应使用可逆 Base64 作为 JSON 字符串载体，`extra_meta` 同时保存 MIME、原始字节数和 SHA-256，解码后逐字节等于原响应体。

当前采集类型包括本地文本、官方 API/HTML/文档、本地扫描 OCR、第三方转录网页或
二进制文档，以及 L2/L3/L4 参考网页。L1-derived 永久固定为 `trust_level=11`。

## 使用

1. 创建虚拟环境并安装 `requirements-l1.txt`。
   动态页面可在配置中设置 `browser.channel: chrome` 复用本机 Chrome；否则首次使用需执行 `python -m playwright install chromium`。
2. 代码与数据使用独立根目录；数据目录通过 `IP_SOURCE_DATA_ROOT` 指定。
3. 将素材放入 `<数据根目录>/data/ip/<ip_domain>/raw/source_material/` 对应类别。
4. 编辑 `config/source_config_l1.yaml`，确认来源等级后将目标任务设为 `enabled: true`。
5. 在代码根目录运行：`python run_l1_collect.py`。

默认数据根目录为代码目录同级的 `<代码目录名>_data`。也可以使用环境变量 `IP_SOURCE_DATA_ROOT` 或参数 `--data-root` 指定。配置、源码和依赖文件不会写入数据目录；JSONL、WARC、状态索引和本地原始素材不会写入代码目录。

每个启用任务输出一条 JSONL 记录。单任务失败会打印 `[FAIL]`，批量中的其他任务仍继续执行；存在失败时进程退出码为 1。

本项目仅用于本地考据研究，不得公开分发抓取到的版权内容。

## 信源注册与筛选

每个任务必须提供全局唯一且稳定的 `source_key`。未来选择层只需要返回这些 key。

```powershell
python run_l1_collect.py --list-sources --include-disabled
python run_l1_collect.py --ip-domain ben10 --dry-run --include-disabled
python run_l1_collect.py --source ben10_hero_generation_series_bible --dry-run --include-disabled
```

`--dry-run` 不发起请求也不写文件。默认只执行 `enabled: true` 的信源。公开、只读、
已在用户指定 IP 范围内的采集可由 Agent 自动推进；登录、验证码、付费、DRM、凭据或
重大范围变化时才暂停。

正常执行会把运行开始、任务开始、任务成功/失败和运行结束事件追加到
`<数据根目录>/data/ip/<ip_domain>/raw/_state/collect_runs.jsonl`。每次运行生成独立 `run_id`，失败记录包含异常类型和消息，且不会中断后续任务。

API支持 GET/POST、Bearer或 API Key环境变量认证，以及固定页码和 HTTP Link-header分页。每页响应独立写一条 JSONL，不合并、不解析业务内容。凭据配置只写环境变量名称，禁止把密钥写入 YAML。

所有 API 调用统一经过 `src/api/api_client.py`。该模块只接受端点和环境变量名称，私密值只从当前进程环境读取，且不会写入日志、状态文件或采集记录。`config/api_credentials.example.ps1` 只有占位示例，不含真实密钥。

HTTP ETag/Last-Modified 保存在各 IP 的 `raw/_state/http_validators.json`；服务器返回 304 时记录为 `unchanged`。内容哈希索引也按 IP 存在 `raw/_state/content_hashes.json`。

采集器序列化规则升级、需要重新生成记录时可使用 `--force-refresh`。它只跳过条件请求缓存，不删除或覆盖旧记录。

网络响应同时追加到各 IP 的 `raw/warc/<source_key>.warc.gz`。WARC保存响应体原始字节及安全响应头，JSONL中的 `warc_path`、`warc_record_id` 可定位原件。为防止凭据泄漏，不归档请求头，API查询参数密钥和会话 Cookie会脱敏。任务可显式设置 `archive_warc: false` 关闭归档。

`official_site_crawl_l1` 用于静态官网的批量获取，只解析 `<a href>` 用于导航，不提取正文。必须配置允许域名、可选路径前缀、最大页数和最大深度；默认无法确认 robots.txt 时停止，且重定向越出允许域名会直接失败。

`dynamic_web_l1` 使用无头 Chromium。它只保存允许域名内的 document/XHR/fetch响应，并将每个响应独立写入 JSONL/WARC。执行脚本后的 DOM另存为 `browser_rendered_dom`，明确标记为派生快照，不冒充原始 HTTP响应。默认不使用登录态，不绕过验证码、付费墙或 DRM。

`official_media_subtitle_l1` 与 `derived_media_subtitle` 使用 yt-dlp发现公开媒体元数据和字幕轨道，始终 `skip_download`，不下载视频，也禁止 Cookie、浏览器登录态、用户名和密码。L1任务必须人工确认官方频道且只允许官方人工字幕；自动字幕或第三方字幕强制使用 L1-derived=11。字幕原文件独立写入 JSONL/WARC，yt-dlp元数据另标为派生快照。

`lol_data_dragon_l1` 先保存官方版本列表响应，只解析第一项版本号用于构造后续官方端点，再按配置分别保存英雄、装备、符文等不同语言的原始JSON。任何数据集响应都不合并、不清洗、不提取字段。

## 独立处理层：第一步确定性分片

处理层与 L1 采集入口隔离，`run_l1_collect.py` 仍然只保存原始内容。分片入口为
`run_process.py`，输出写入对应 IP 的 `processed/units/`，不会修改或覆盖
`data/ip/<ip_domain>/raw/`。

数据采用 IP 优先隔离：每个 IP 只有 `raw/`（原样获取、不可变）和
`processed/`（可重建的切片、索引、向量、事实候选）两类。代码目录不得存放运行数据。

```powershell
python run_process.py --data-root C:\path\to\ip-research-data --ip-domain douluo --dry-run
python run_process.py --data-root C:\path\to\ip-research-data --input C:\path\to\raw.jsonl
```

分片阶段完全不调用 LLM。HTML 保留最小可见文本块及其原始 HTML 字符范围；TXT
按卷/章标题、自然段和标点切分；SRT/VTT 按时间码切分。二进制 PDF、图片、音视频
Base64 记录不会被误当作文本，留给后续专用解析器。处理不会提升或改变信源等级。

文本型 PDF 使用页级解析入口，产物保留父原件、页码和 PDF 哈希：

```powershell
python run_extract_pdf.py --data-root C:\path\to\ip-research-data --ip-domain ben10
python run_process.py --data-root C:\path\to\ip-research-data --input C:\path\to\pdf_pages.jsonl
```

无文本页会标记 `requires_ocr=true`；扫描型 PDF 的逐页 OCR 回退尚未实现。

## 本地处理结果仪表盘

打开 `dashboard/index.html` 可查看作品覆盖、处理统计、18阶段任务进度、规则候选分布
和本地模型试验结论。页面不包含小说正文，也不会向网络发送数据。更新处理产物后运行：

```powershell
python scripts/generate_dashboard.py `
  --data-root C:\path\to\ip-research-data `
  --output dashboard\data.js
```
