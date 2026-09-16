# novel-memory-system

小说「记忆基础设施」：面向 10 万字级中文小说稿的**纯记忆存储 + ETL + 检索工具层**。
基于 **PostgreSQL 16 + pgvector**，OpenAI 兼容接口做 LLM 结构化提取与 embedding。

> 定位边界：本项目只做**记忆**——存什么、怎么存、怎么查。
> 不包含创作 Prompt / Agent 编排 / GUI / 排版导出；不复制任何开源代码，
> 仅参考 AI_NovelGenerator 与 AI-Novel-Writing-Assistant 的架构思想，实现全部原创。

```
novel-memory-system/
├─ docker-compose.yml      # 数据库服务（pgvector/pgvector:pg16 + init.sql + 命名卷 pgdata）
├─ init.sql                # 全部 DDL：枚举/序列/5 表/月分区/HNSW/双路径触发器/中文 COMMENT
├─ pyproject.toml          # 依赖 + [project.scripts] nms-etl + src 布局
├─ .env.example            # 环境变量模板（数据库/LLM/搜索/时间分布/日志）
├─ .gitignore
├─ etl.py                  # 根入口：python etl.py [--resume|--reprocess-chapter N|--mock ...]
├─ wb_tools.py             # 根入口：import wb_tools 后直用 5 个 async 函数
├─ data/chapters/          # 存量稿件只读输入：chapter_001.md, chapter_002.md ...
│   └─ chapter_00{1,2,3}.md  # 3 个原创示例章（武侠，用于验收）
├─ state/                  # 运行时：etl_state.json（断点续传，原子写）+ etl.lock
├─ logs/                   # 运行时：etl_errors.log（校验/LLM 失败明细，含截断 raw）
├─ src/novel_memory_system/  # 包本体（见下）
└─ tests/offline_selftest.py # 离线自测（无 DB/LLM/网络）
```

## 1. 快速开始

### 1.1 启动数据库

```bash
cp .env.example .env        # 按需修改（端口冲突就改 HOST_DB_PORT）
docker compose up -d
# 探活：容器内 psql 执行（等价于 Python 侧 DATABASE_URL）
docker compose exec db psql -U novel -d novel_memory -c "\dt"
```

- init.sql 仅在数据卷**首次初始化**时自动执行；之后修改 schema 需
  `docker compose down -v && docker compose up -d` 重灌，或手动
  `docker compose exec -T db psql -U novel -d novel_memory -f - < init.sql`。
- 自检（应能看到 5 张表 + 预建分区 + HNSW + 触发器）：

```sql
SELECT tablename FROM pg_tables
 WHERE tablename LIKE 'chapters_%' OR tablename LIKE 'events_%' ORDER BY 1;
SELECT tgname FROM pg_trigger WHERE NOT tgisinternal;   -- trg_events_chapter / trg_*_embedding
SELECT indexname FROM pg_indexes WHERE indexdef ILIKE '%hnsw%';
```

### 1.2 安装 Python 依赖

```bash
python -m venv .venv
# Windows
.venv\Scripts\python -m pip install -e ".[dev]"
# Linux/macOS
.venv/bin/python -m pip install -e ".[dev]"
```

不装依赖跑纯逻辑自测（不连库）：`.venv\Scripts\python tests\offline_selftest.py`

## 2. ETL：Markdown 存量稿件入库

### 2.1 稿件格式与运行参数

稿件放 `data/chapters/chapter_<N>.md`（章号正则 `^chapter_(\d+)\.md$`），
文件首个 `# ` 标题作为章节标题。可用 `--dir` 指向任意目录。

```bash
python etl.py                              # 全量导入（已 done 自动跳过）
python etl.py --resume                     # 断点续传（推荐常规用法）
python etl.py --reprocess-chapter 12       # 强制重跑第 12 章（先清旧数据再入库）
python etl.py --mock                       # 离线降级：启发式提取 + 确定性伪向量
python etl.py --dir ./my_chapters --log-level DEBUG
pip install -e . 之后也可：nms-etl --resume
```

流程：发现章号 → 按章加锁幂等预检 → LLM 提取 + Pydantic 校验 → 入库
（chapters → characters → world_settings[低置信度联网补全] → events → plot_threads）
→ 每 10 章一个事务（章级 savepoint，单章失败只回滚自身）→ COMMIT 后统一生成并
按复合主键 `(id, created_at)` 精确回填 embedding。

- 断点：`state/etl_state.json`（原子写），失败明细在 `logs/etl_errors.log`
  （含校验失败字段与截断 raw）。
- 失败重试：单章连续失败 ≥3 次（`MAX_CHAPTER_RETRIES`）后自动跳过，不阻塞整稿。
- 并发安全：进程文件锁 + 章号 advisory lock + EXISTS 预检，双进程并发跑不产生重复章节。

### 2.2 时间分布（v1.1 外化环境变量，适配不同篇幅）

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `ETL_TIME_BASE` | `now` | 基准时刻；建议固定 ISO8601（如 `2026-01-01T00:00:00+08:00`）保证重跑幂等 |
| `ETL_TIME_SPAN_DAYS` | `1.0` | 整稿时间跨度（天）；`0`=全部同一时刻；数千章长篇调大以跨多月分区 |

公式：`ts(chapter i) = BASE − (N − i) × SPAN×1440/N 分钟`（最新章锚定 base）；
章内第 j 个事件按 `j/(len+1)` 比例均布在本章区间内，不越章界。同一 base + span
下任何重跑产生完全一致的时间戳 → 分区稳定、可复现。

短稿默认落在单月分区即可；如需验证「动态建分区 + 逐子表 HNSW」，把 span 调大
（如 `ETL_TIME_SPAN_DAYS=180`）使时间分布跨多个月。

## 3. wb_tools：5 个 async 查询函数（WB/Agent 侧调用）

所有函数 docstring/类型注解/异常处理齐全；每次调用独立从连接池取连接，无需手工事务。
**events↔chapters 一律携带 `chapter_created_at` 复合 JOIN**，保证查询侧分区裁剪。

```python
import asyncio, wb_tools

async def main():
    ctx   = await wb_tools.get_chapter_context(5)      # 三层记忆
    hits  = await wb_tools.search_memory("主角第一次受伤", top_k=5)
    prof  = await wb_tools.query_character("林晓")
    ok    = await wb_tools.update_world_setting(1, "…新设定…", "user_confirmed", 0.95)
    issue = await wb_tools.validate_consistency(5)     # 一致性矛盾列表（空=通过）

asyncio.run(main())
```

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `get_chapter_context(n)` | `dict` | 三层上下文：settings（近 10 条）/ active_threads（仅 open/progressing，滤 resolved）/ recent_summaries（n 之前最近 3 章） |
| `search_memory(q, top_k=5)` | `list[dict]` | 三表 `UNION ALL` 向量检索，`score = 1 − cosine_distance`，返回 `[{table,id,content,score}]` |
| `query_character(name)` | `dict` | current_state + 按时间正序的角色事件时间线（复合 JOIN 剪枝）；角色不存在返回空不抛错 |
| `update_world_setting(id, value, source, confidence)` | `bool` | 人工确认闭环；校验 source/置信度；成功后该行 embedding 被触发器置 NULL（见 §5 重新生成） |
| `validate_consistency(n)` | `list[str]` | 空摘要 / 孤儿事件 / 非法角色引用 / first_appear 悬空 / 章号重复 / 时间线矛盾等（质量门禁） |

## 4. 数据模型（5 张表，全部中文 COMMENT）

| 表 | 分区 | 要点 |
| --- | --- | --- |
| `chapters` | 按 `created_at` 月分区 | PK`(id, created_at)`；number 由 ETL 幂等预检保证唯一；HNSW 逐子表 |
| `characters` | 无 | name 唯一；current_state jsonb；first_appear_chapter_id 应用层引用 |
| `world_settings` | 无 | (category,key) 唯一；source enum；confidence 0~1 CHECK；<0.7 且地理/历史/文化 → 联网补全 |
| `events` | 按 `timestamp` 月分区 | PK`(id, timestamp)`；`chapter_created_at` 与 chapter_id 复合引用 chapters（双路径触发器校验，非真实 FK）；related_characters jsonb |
| `plot_threads` | 无 | title 唯一；status enum + priority；related_events jsonb |

核心机制：
- **月分区**：无 DEFAULT 分区；`ensure_month_partition(parent, ts)` 幂等建
  `parent_YYYY_MM` 子表并同步建 HNSW（`m=16, ef_construction=64`）。入库前必建分区。
- **双路径参照完整性触发器** `check_events_chapter()`：快路径按
  `(chapter_id, chapter_created_at)` 等值命中 → 裁剪到单分区 O(1)，写入延迟不随分区数
  线性增长；未命中才走诊断路径区分「id 不存在」与「时间不匹配」（ERRCODE 23503）。
- **update_embedding() 列级触发器**：仅 `UPDATE ... SET content/summary/title`（或角色
  name/current_state、设定 key/value）时把 embedding 置 NULL 待重生成；回填语句只
  `SET embedding` 故不触发，无死循环。

## 5. 常见坑

1. **改 schema 必须重灌**：`docker compose down -v && docker compose up -d`。
2. **分区键只读**：`chapters.created_at` / `events.timestamp` / `events.chapter_created_at`
   一经写入绝不 UPDATE（分区键变更会触发行搬家/损坏）。
3. **改 embedding 模型需同步维度**：schema 为 `vector(1536)`，换 768/3072 维模型须同步
   改 `init.sql` 与 `.env` 的 `EMBED_DIM`。
4. **update_world_setting 后向量被置空**：该行暂时退出向量检索。重新生成：

   ```python
   import asyncio
   from novel_memory_system.db import connection
   from novel_memory_system.embed import backfill_single_key_embedding

   async def fix(ws_id: int, text: str):      # text 格式与 ETL 一致："{category} {key} {value}"
       async with connection() as conn:
           await backfill_single_key_embedding(conn, "world_settings", [(ws_id, text)], mock=False)
   asyncio.run(fix(1, "地理 青石巷 城西暗巷，雨夜潮湿"))
   ```

5. **Windows 注意**：用 `.venv\Scripts\python`；`.env` 保持 UTF-8 无 BOM；
   时间 env 用带时区 ISO（`+08:00`）或依赖 `TZ`。
6. **EXPLAIN 验证分区裁剪**（快路径/查询侧都应只有单分区被扫）：

   ```sql
   EXPLAIN (ANALYZE, BUFFERS)
   SELECT 1 FROM chapters WHERE id = 1 AND created_at = '2026-09-15T00:00:00+08:00';
   -- 期望输出仅含 1 个分区（如 chapters_2026_09），无 Append 扫全部分区
   EXPLAIN (ANALYZE)
   SELECT c.number FROM events e
   JOIN chapters c ON c.id = e.chapter_id AND c.created_at = e.chapter_created_at
   WHERE e.id = 1 AND e.timestamp = '2026-09-15T00:10:00+08:00';
   ```

## 6. 数据库侧验收清单（在装有 Docker/psql 的机器上执行）

> 本仓库交付**完整代码 + 离线自测**；以下步骤需真实 PostgreSQL 16 + pgvector 环境，
> 沙箱内无法代跑，请按顺序执行：

1. **起库**：`docker compose up -d`，`docker compose ps` 健康；§1.1 自检 SQL 全过。
2. **离线自测**：`.venv\Scripts\python tests\offline_selftest.py` → 全 PASS。
3. **首跑**：`cp .env.example .env`（可留空 LLM key）→ `python etl.py --mock`。
   日志出现「3 章全部 inserted」，`state/etl_state.json` 三章 done。
4. **断点续传**：删掉 `data/chapters/chapter_002.md` 后
   `python etl.py --resume --mock` → 不报错、跳过已 done；恢复文件后再跑 → 补齐第 2 章。
5. **幂等**：再跑一次 `python etl.py --mock` → 全部 skipped；
   `validate_consistency(2) == []`；`SELECT number, count(*) FROM chapters GROUP BY 1 HAVING count(*)>1` 为空。
6. **重跑单章**：`python etl.py --reprocess-chapter 1 --mock` → 第 1 章重新 inserted；
   `first_appear` 仍指向新章节 id（无悬空）。
7. **向量回填对齐**：
   `SELECT count(*) FROM chapters WHERE embedding IS NOT NULL;` = 3；
   characters/world_settings 同理；再次跑 `--resume --mock` 全部 skipped（无重复回填）。
8. **5 函数冒烟**（配好真实 LLM key 或仍 `--mock` 的确定性向量均可）：
   `get_chapter_context(3)` 三层结构；`search_memory("青石巷")` 返回章节记录；
   `query_character("林晓")` 返回 current_state+timeline；
   `update_world_setting(...)` 返回 True 且该行 embedding 变 NULL；
   `validate_consistency(1..3)` 全部 `[]`。
9. **剪枝验证**：执行 §5-6 两条 EXPLAIN，确认命中单分区。
10. **负向**：向 events 插入不存在的 `chapter_id` → 23503 报错；
    插入存在 id 但错误 `chapter_created_at` → 23503（时间不匹配信息）；
    无默认分区月份插入 → 明确报「no partition of relation found」而非静默吸收。

## 7. 目录内模块一览

| 模块 | 职责 |
| --- | --- |
| `config.py` | 环境变量集中读取（含 ETL_TIME_* 解析与校验），全局单例 |
| `db.py` | asyncpg 连接池 + register_vector + 事务/savepoint 辅助 |
| `partition.py` | 幂等建分区/批量建分区（对接 init.sql 存储函数） |
| `state.py` | etl_state.json 原子读写 + 文件锁 + 错误日志 |
| `schemas.py` | Pydantic v2 提取模型与严格校验（对齐 SQL 枚举） |
| `extract.py` | LLM 结构化提取（OpenAI 兼容） + mock 启发式降级 |
| `embed.py` | 批量 embedding + 复合主键 unnest 严格对齐回填（含断言） |
| `enrich.py` | 世界设定联网补全（低置信度 地理/历史/文化） |
| `etl_runner.py` | ETL 主流程（幂等预检/savepoint/批次回填/断点续传） |
| `wb_tools.py` | WB 侧 5 个 async 查询函数 |

## 8. 原创性说明

实现过程中**未复制任何开源代码**。参考 AI_NovelGenerator / AI-Novel-Writing-Assistant
仅用于提取「五表记忆分层 + LLM 提取入库 + 向量检索」的架构思想；
本项目全部 SQL/Python 均为原创，未参考 oh-story-claudecode。
