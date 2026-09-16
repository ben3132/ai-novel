# novel-creation-engine（L3 创作层）

> **不建库、不存事实、不做检索。**
> 只做三件事：① 按正确时序调外部命令　② 把总纲判据变成可执行检查　③ 产出「依据 → 命中 → 建议」三段式的可回查报告。

这是五层架构里的 **L3 创作层**。它的存在理由不是"多一个工具"，而是**补上一个没人认领的空位**：写作流程里「什么时候调谁、判据怎么裁、报告怎么留痕」这三件事，nah / nms / xs 都不做。

---

## 1. 边界：谁已经在做什么

**L3 的第一原则：已经有项目做的东西，L3 只接线，不重复实现。**
重复实现的风险不是浪费代码，而是**同一份事实出现两个写入者**。

| 能力 | 归属 | L3 怎么做 |
|---|---|---|
| 已写正文的梳理与提取 | **nms**（ETL + 5 表） | 子进程调 `wb_tools` |
| 位置／世界观／原作知识归纳 | **xs**（IP 证据库） | 子进程调 `run_ip_agent.py` |
| 原作角色判定 | **xs** | 经 `nah orphan` 中转 |
| 本书设定的登记与审计 | **nah**（卡片库） | 子进程调 `nah.py` |
| **编排时序** | **L3** ← 唯一没人做 | 本仓库 |
| **判据裁决** | **L3** | 本仓库 `ce/rules/` |
| **评审报告** | **L3** | 本仓库 `ce/review.py` |
| 编写正文／去 AI 味 | L3 只做**接线**（见 §4） | 不自接 LLM |

设计论证见 `novel-asset-hub/docs/creation-layer.md`。

---

## 2. 快速开始

```bash
# 探测三个外部项目的可用性
python ce.py doctor

# 审一章（纯本地判据，不碰外部项目）
python ce.py review "D:/path/to/我的小说/processed/raw/ep_001.md" --no-setting

# 审一章（含设定闸：调 nah + nms）
python ce.py review "D:/path/to/我的小说/processed/raw/ep_001.md"

# 批量审一个目录，出汇总
python ce.py review "D:/path/to/我的小说/processed/raw" --no-setting

# 只跑某几个判据集
python ce.py review ep_001.md --rules §23

# 出 JSON 而非 Markdown
python ce.py review ep_001.md --json

# 跑单元测试（离线，零依赖）
python -m unittest discover -s tests -v
```

零安装：只依赖 Python 标准库。

---

## 3. 判据：把总纲变成可执行检查

判据来源是**唯一现行版**的写作规范文档（如 `<小说仓库>/参考/总纲.md`），由作者自行维护。

| 模块 | 覆盖 | 对应总纲 |
|---|---|---|
| `ce/rules/forbidden.py` | 八条一级禁则（红线） | §23 |
| `ce/rules/ironclad.py` | 写作铁律 + 章节四层判定 | §24 / §25 |

### 3.1 原则：能给客观量就给客观量，给不了就承认给不了

§23 是红线，机器可以给"疑似违反"；§24/§25 是**方法要求与自问清单**，其中大量条目（"这段有戏剧作用吗？"）**机器无法判断**。

对这类条目，L3 的做法不是硬凑一个假判据，而是**生成待答问题 + 附上机器能给出的客观量**。

最典型的例子是 **§25 节拍闸**。它前后做过三版：

| 版本 | 做法 | 结果 |
|---|---|---|
| v1 | 用 `(?=说\|道\|问\|答)` 从章末提取专名 | 抽出「脸兴奋的」「伴随着」「跑到街」 |
| v2 | 扩到全章找首现专名 | 噪声性质相同（「在瓦龙」「再怎么」） |
| **v3** | **只给客观量**（字数／段数／对话占比／章末节选） | 诚实、可用 |

根因：**中文没有词边界**。`[\u4e00-\u9fa5]{2,4}(?=道)` 会把"跑到街**道**"的"跑到街"当说话人。**纯正则做中文实体识别不可行**；硬做的产物是噪声，而噪声比不报更糟——它会淹没真问题、损害整份报告的可信度。

需要实体清单时，L3 明确指向 `nah orphan` / nms 实体提取——**那是它们的职责**。

### 3.2 每条命中的数据结构

```python
Hit(
    rule_id="§23-6",
    rule_name="禁止结尾喊口号",
    severity="红线",          # 红线 / 铁律 / 闸门 / 提示
    line=237,                # 行号
    snippet="那么，英雄登场",  # 命中的原文
    basis="总纲 §23：…",       # 【依据】
    advice="把口号换成…",      # 【建议】
    confidence="mid",        # high / mid / low —— 启发式必诚实标注
    context="…",             # 上下文，便于人工复核
)
```

**每条命中必须三段齐全**（依据 → 命中 → 建议），不允许只有"这里有问题"。

---

## 4. 适配层：对三个外部项目只有读权限

`ce/adapters/` 是**接线层**，不含任何检索／归纳／校验的实现。
全部走子进程，不 import 外部项目的模块——避免把它们的依赖与副作用（数据库连接、savepoint）耦合进 L3 进程。

| 模块 | 外部项目 | 调用方式 |
|---|---|---|
| `adapters/nah.py` | novel-asset-hub | 子进程调 `nah.py` CLI |
| `adapters/nms.py` | novel-memory-system | 子进程 `python -c` 调 `wb_tools` |
| `adapters/xs.py` | xs IP 证据库 | 子进程调 `run_ip_agent.py --request-json` |

**三个都必须可缺席**：外部项目不可用时，adapter 返回 `available=False` 并给出安装提示，绝不让整个 L3 崩溃。`--no-setting` 时禁则闸 + 铁律闸是纯本地的，零外部依赖也能跑。

可换路径（环境变量）：`NAH_ENGINE` / `NMS_ROOT` / `XS_ROOT` / `XS_DATA`。

---

## 5. 接线层踩过的坑（实测记录）

这些是接外部项目时才暴露的问题，全部已修，记在这里避免重犯。

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | `nah check --json` 输出人类可读文本 | 该版 `nah check` **没有 `--json`**（只有 `orphan` 有） | `check()` 返回原始文本；需结构化走 `orphan --json` |
| 2 | `xs.list_works` 永远返回空 | query 层 `ip_domain` **硬编码默认 `"douluo"`**，request 不传就查错库 | 注入 `ip_domain` 到 request |
| 3 | `--database <目录>` 报 `Evidence database not found` | `agent_api._database()` 把该值**直接当库文件路径**；只有传 `None` 才回落到 `IpDataPaths(...)` 推导 | 传 `evidence.sqlite3` 完整路径 |
| 4 | `search_hybrid` 静默返回 0 结果 | `VectorDependencyError` **只在建索引时抛**；查询路径找不到索引会**静默降级** | 主动检查 `processed/vector/` 是否有文件（`hybrid_available()`） |
| 5 | **查询串'十二符咒'命中 0，'符咒'命中 1** | xs 词法检索是**整串 LIKE（AND 语义）、不分词**。空格也不是分词符 | `search_terms()`：多词**分别检索**再按 `window_id` 去重合并 |
| 6 | `nms` 报 `ModuleNotFoundError` 却看不出原因 | 依赖（`asyncpg`/`pgvector`）缺失与"代码不存在"混为一谈 | 包装脚本分 `stage`（import/lookup/call）+ `hint`；`probe()` 预检依赖 |

---

## 6. L3 最终形态

### 第一步（已完成）：`review`
只读、零风险。对任意章出判据报告。

三闸门：

| 闸门 | 数据源 | 性质 |
|---|---|---|
| 禁则闸 | 纯本地（§23） | 机械可判 |
| 铁律闸 | 纯本地（§24） | 机械可判 |
| 设定闸 | **外部**：nah（应然）+ nms（实然） | L3 只转述，不裁决 |

### 第二步（待建）：`brief` + `commit`
- `ce brief <名字…>` —— 调 `nah brief` / `nms get_chapter_context` / `xs search_terms` 拼装上下文
- `ce commit <章.md>` —— 写 L4 正文 + 触发 `nah check`、`nms validate_consistency`

**「编写」归 L3，但 L3 不自接 LLM**：产出 Brief，交给 Agent 生成。
依据是 xs 自己的能力声明——`get_agent_guidance()` 的 `not_implemented` 列了 7 项
（`automatic_web_source_discovery` / `automatic_work_tree_discovery` /
`single_command_end_to_end_pipeline` / `coverage_report_operation` /
`autonomous_research_loop` / `pdf_page_ocr_fallback` / `structured_xml_fdx_extraction`），
且 `embedded_llm_required: False`、`decision_owner: connected_agent`。

---

## 7. 校准记录（2026-09-16）

判据不是写完就算完，必须**在真实语料上校准**。首次在一部长篇（89 章）上全量跑的结果：

| 规则 | 首轮 | 校准后 | 处理 |
|---|---|---|---|
| §25-3 效用闸 | 109 | **1** | 要求描写词处于主位，不再因"脚边的树"命中动作句 |
| §23-6 结尾喊口号 | 33 | **8** | 补入「那么，X」形态；剔除疑问／应答类对白 |
| §24-5 时序 | 58 | **29** | 剔出「想起」这类高频正常动词 |
| §23-7 原主混淆 | 4 | **0** | 剔除「4 臂前身」「原身体」误报 |
| §25-1 节拍闸 | 89 | 89 | 改为只给客观量 |

**校准后的全库分布**（89 章 / 208 条命中）：`§25-1` 89（每章 1 条待答问题）·
`§23-1` 37 · `§24-4` 34 · `§24-5` 29 · `§23-6` 8 · 其余 ≤4。

**一条重要情报**：全库「原主」出现 **0 次**、「前身」仅 **2 次**。
说明 §23-7 这条禁则**在该书正文里几乎没有适用场景**——这不是判据失效，是事实。
（前身相关表述极少，可能意味着"穿越者与原主"的区分在这本书里并未成为问题。）

---

## 8. 已知局限

1. **精度优先、召回有限**。这些是句式启发式，定位是**人工复核清单，不是拦截器**。
   命中不等于违规，未命中也不等于合格。
2. **§25 节拍闸 / 效用闸无法由机器回答**，只给客观量与待答问题。
3. **只读**。对 nah/nms/xs 只有读权限；唯一写出口是 L4 正文（`commit`，待建）。
4. **报告是纯派生输出**，可随时删除重建。**不要把判定写回报告**——需要固化的结论
   请写入 novel-asset-hub 的卡片。
5. `reports/` 目录不入版本控制。

---

## 9. 目录结构

```
novel-creation-engine/
├── ce.py                     # 零安装入口
├── ce/
│   ├── __init__.py           # 定位声明
│   ├── cli.py                # 统一 CLI（review / doctor）
│   ├── review.py             # 三闸门编排 + 三段式报告
│   ├── rules/
│   │   ├── hit.py            # Hit 数据结构（承载三段式）
│   │   ├── forbidden.py      # §23 八条一级禁则
│   │   └── ironclad.py       # §24 铁律 + §25 四层判定
│   └── adapters/             # 只读接线层
│       ├── base.py           # 子进程执行 + 可用性探测
│       ├── nah.py
│       ├── nms.py
│       └── xs.py
├── tests/test_rules.py       # 33 项离线自测
├── reports/                  # 派生输出（可删）
└── README.md
```
