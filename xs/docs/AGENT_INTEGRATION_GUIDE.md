# Agent 接入与能力边界

本文件只说明“什么能调用”。研究规则以 `IP_RESEARCH_PROTOCOL.md` 为准，命令参数
以各脚本的 `--help` 为准，机器应优先读取 `get_agent_guidance` 返回值。

## 角色

- 接入 Agent：理解目标、建立作品树、联网发现动态信源、核验主体与版本、提出等级、评估覆盖缺口。
- 本项目：校验元数据、采集并保存原始响应、按 IP 隔离数据、确定性切片、建立索引、返回证据。
- 本项目不内置大模型；模型记忆不是证据。

## `run_ip_agent.py` 已实现操作

只有以下名称可作为 `operation`：

```text
get_agent_guidance
initialize_ip
get_research_state
get_research_status
get_corpus_status
register_work
register_source
update_source_status
save_claim_candidate
next_actions
list_works
get_entity
search_evidence
search_hybrid
```

## 独立 CLI（不是 operation）

```text
采集              run_l1_collect.py
PDF按页文本提取     run_extract_pdf.py
确定性切片         run_process.py
上下文窗口         run_build_windows.py
SQLite证据库       run_build_index.py
可选作品层级       run_build_hierarchy.py
FAISS向量索引      build_ip_vector_index.py
```

这些命令当前需要 Agent 按数据状态组合执行，不存在统一的 `collect`、`process` 或
`index` Agent operation。执行前用 `python <脚本> --help` 获取真实参数。

## Agent任务（不是程序接口）

以下词出现在 `next_actions` 时只是建议任务：

```text
discover_work_tree
discover_sources
choose_collector
cross_check_l1
assess_coverage_and_gaps
```

`next_actions[].directly_executable` 当前为 `false`；有对应脚本组合时会在
`required_commands` 中列出。不要把 `action` 字符串直接传回 `operation`。

## 尚未实现

```text
自动联网发现信源
自动建立作品树
单命令端到端流水线
coverage_report操作
自治研究循环
扫描型PDF的逐页OCR回退（文本型PDF页级解析已经实现）
FinalDraft/FDX/XML结构化剧本解析
```

Agent可以自行完成研究判断并调用现有工具，但不得向用户声称上述能力已经由项目实现。

## PDF处理

`run_extract_pdf.py` 读取采集层保存的 Base64 PDF 原件，验证格式与可用的 SHA-256，
使用 pypdf 原样按页提取文本，写入 `processed/pdf_pages/`。每页保留父
`source_id`、PDF 字节哈希、页码、解析器版本和派生类型，之后将该输出通过
`run_process.py --input <pdf_pages.jsonl>` 接入切片链路。原始 PDF 不会修改。

`requires_ocr=true` 表示该页没有可提取文本。扫描型 PDF 的页面渲染与 PaddleOCR
回退尚未实现，不能把“已有图片 OCR 采集器”误报为“可直接 OCR PDF”。

基础 `search_evidence` 只要求 `sources/context_windows/windows_fts`，不要求作品层级。
`run_build_hierarchy.py` 是小说卷章、剧集等结构筛选的可选增强，不是 PDF、网页、
字幕或 API 证据检索的前置条件。多份来源可以映射到同一作品而不会发生结构 ID 冲突。

## 状态与统计术语

- `source_artifact_count`：原始信源数量，用户报告只能使用此字段。
- `processed_source_record_count`：索引内部来源记录，可能包含 PDF 页等技术记录。
- `document_unit_count`：文档派生单元数量，不是信源数量。
- `text_unit_count` / `context_window_count`：切片与检索窗口数量。

采集链完成不等于 IP 完成。L2/L3 允许按等级归档和检索；只有 L4 强制排除推理。

## 首次检查

```powershell
'{"operation":"get_agent_guidance"}' | python run_ip_agent.py --pretty
```

```powershell
'{"operation":"initialize_ip","ip_domain":"example_ip","name":"Example IP"}' |
  python run_ip_agent.py --pretty
```

数据根目录由 `IP_SOURCE_DATA_ROOT` 指定，结构固定为：

```text
data/ip/<ip_domain>/raw
data/ip/<ip_domain>/processed
```
