# 通用 IP 研究协议（Agent 必读）

本项目不是百科答案生成器，而是 Agent 的可追溯研究工具箱。Agent 负责理解、搜索词设计和语义判断；项目负责保存研究状态、采集原件、建立证据索引和约束输出。

## 强制原则

1. 先区分作品和连续宇宙，再整理人物与设定。未知归属写 `unresolved`，禁止猜测。
2. 网络搜索结果只是“信源候选”；完成发布主体核验后才能登记等级。
3. L1=官方原生一手内容；第三方原作转录固定为 11；有引用规范的 Wiki 为 L2；社区分析为 L3；低可信/同人/AI 为 L4。
4. L4 可以归档和提供搜索线索，但 `eligible_for_reasoning=false`，禁止支持设定结论。
5. 采集层保存完整原始响应，不用清理后的正文覆盖原件。
6. 所有事实先保存为 `candidate`。没有真实 `window_id` 的结论不得进入事实库。
7. 同名人物在不同连续宇宙中默认是不同实体；除非证据证明，禁止跨宇宙合并。
8. 证据矛盾时保存冲突分支，不按模型偏好静默选择。

## 陌生 IP 标准流程

### A. 初始化

调用 `initialize_ip`，记录名称、别名、语言和用户研究目标。随后调用 `next_actions`，不要依赖聊天记忆判断进度。`next_actions` 是建议任务，不是可直接作为 `operation` 调用的接口。

### B. 作品树

搜索并登记原作、正传、外传、动画、漫画、游戏、电影、重启和设定出版物。每项必须有 `work_id`、`kind`、`continuity_id`、`canon_status`。尚未核实的字段使用 `unknown/unresolved`。

### C. 信源发现

按以下顺序寻找：官方主站/API/文档 → 本地合法原件 → 第三方原作转录 → 引用型 Wiki → 社区考据 → L4 线索。对每个候选调用 `register_source`，填写等级理由、作品和连续宇宙范围、适用采集器。

不能仅凭域名或搜索排名判定等级。官方域名中的用户内容也不自动属于 L1；Wiki 即使准确也不能标记为 L1-derived。

### D. 采集和原件归档

将 `status` 改为 `approved/collecting` 后调用匹配的采集器。成功后标记 `collected`；失败必须记录原因，保留 URL 供下一个 Agent 续作。密钥只通过环境变量传入。

### E. 处理和索引

对 collected 原件先按介质解析，再执行：确定性切片 → 上下文窗口 → SQLite FTS → 可选 BGE/FAISS。作品层级是可选增强，不是基础检索前置条件。派生数据必须保留父 `source_id`、介质坐标（页码/时间码/XML路径）、原文偏移和内容哈希。

每个 IP 使用独立索引文件：

```powershell
python build_ip_vector_index.py --ip-domain transformers `
  --database <evidence.sqlite3> --output-dir <vector目录> --model-path <BGE模型目录>
```

### F. 整理事实

通过检索获取局部证据后再让模型抽取。每条原子事实只表达一个主谓宾关系，并绑定作品、连续宇宙、`window_id`、`source_id` 和信源等级，然后调用 `save_claim_candidate`。

### G. 验证与交接

只有证据定位有效且语义支持的候选可以标记 grounded；只有满足项目交叉验证规则的候选可以标记 verified。每次工作结束前调用 `get_research_status`，按 `next_actions` 继续或把状态交给其他 Agent。

不得把“采集器成功”“首批来源处理完成”写成“IP收集完成”。IP完成至少需要作品树、
连续宇宙、信源类型和未解决缺口四个维度的覆盖说明。统计时原始信源使用
`get_corpus_status.source_artifact_count`；PDF页、XML节点、TextUnit 和窗口不得计为信源。

## Agent 单一入口

Python：

```python
from src.agent.ip_agent import run_ip_agent

result = run_ip_agent({
    "operation": "initialize_ip",
    "ip_domain": "transformers",
    "name": "变形金刚",
    "aliases": ["Transformers"]
})
```

跨进程：

```powershell
'{"operation":"get_research_status","ip_domain":"transformers"}' |
  python run_ip_agent.py --request-json -
```

研究状态位于独立数据目录的 `data/ip/<ip_domain>/processed/research/`，不得与采集器脚本混放。
