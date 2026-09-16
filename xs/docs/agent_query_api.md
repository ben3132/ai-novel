# 斗罗证据查询与 Agent 接口

第一阶段接口只负责从本地证据库检索原文。它不会把检索结果直接宣称为已经验证的设定，也不会调用 LLM 生成答案。

## 数据库配置

私密路径和后续 API 密钥统一通过环境变量或接口参数传入，不写入源码：

```powershell
$env:IP_SOURCE_DATA_ROOT = 'D:\path\to\xs_data'
```

也可复制 `config/agent_query.example.ps1` 后在本机修改；不要提交含私密信息的配置文件。

## Python 接口

```python
from src.query.agent_api import search_evidence

result = search_evidence(
    "霍雨浩的武魂是什么",
    works=["douluo_2"],
    top_k=5,
)
```

可用函数：

- `search_evidence(...)`：自然语言问题检索，返回带作品、章节、窗口、来源和可信等级的原文证据。
- `get_entity(...)`：返回某实体的原文提及证据，不自动归纳实体档案。
- `list_works(...)`：列出证据库中的作品和章节数。
- `query_agent(request)`：供其他 Agent 使用的单一 JSON 字典入口。

`query_agent` 支持 `search_evidence`、`search_hybrid`、`get_entity`、`list_works` 四种 operation。

```python
from src.query.agent_api import query_agent

response = query_agent({
    "operation": "search_evidence",
    "question": "唐三的武魂是什么",
    "works": ["douluo_1"],
    "trust_levels": [1, 11],
    "top_k": 5,
})
```

## CLI / 跨进程 JSON 接口

```powershell
python run_douluo_query.py --question "霍雨浩的武魂是什么" --work douluo_2 --top-k 5 --pretty
```

其他 Agent 可以通过标准输入传 JSON，避免命令行转义问题：

```powershell
'{"operation":"list_works"}' | python run_douluo_query.py --request-json -
```

## 混合 RAG 召回

向量索引只保存 512 维向量和 `window_id`；原文仍以 SQLite 为唯一事实存储。建索引不调用远程模型：

```powershell
python build_ip_vector_index.py --ip-domain <ip-domain> `
  --data-root $env:IP_SOURCE_DATA_ROOT `
  --output-dir $env:IP_VECTOR_INDEX_DIR `
  --model-path $env:IP_EMBEDDING_MODEL
```

Python 调用：

```python
from src.query.agent_api import search_hybrid

result = search_hybrid(
    "唐三的双生武魂分别是什么",
    works=["douluo_1"],
    top_k=8,
)
```

CLI 调用：

```powershell
python run_ip_query.py `
  --hybrid --question "…" --work <work-slug>
```

混合结果使用 RRF 融合，分别返回 `lexical_rank`、`vector_rank`、`vector_score` 和 `fusion_score`。证据库大小或修改时间发生变化时，接口会拒绝旧索引并要求重建。

## 返回结果约束

- `answer_status` 固定为 `evidence_only`，表示结果是候选证据而非最终答案。
- 每条结果保留 `source_id`、`window_id`、`chapter_id`、可信等级、来源路径和原文片段。
- `trust_level=11` 会产生强制警告，正式考据时必须与 L1 原件交叉验证。
- `evidence_window_start/end` 是片段在检索窗口内的位置，可用于前端定位。
- 千问等生成模型只接收少量检索结果做后续归纳，不参与全库切片和向量化。
