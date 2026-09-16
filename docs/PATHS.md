# AI 小说工具链 · 本地路径地图

> 生成时间：2026-09-16
> 用途：一页看清「代码在哪、数据在哪、谁读谁」，以及换机器/重装后怎么恢复

---

## 一、总览：一张图

```
┌─────────────────────────────────────────────────────────────────┐
│  工具代码（1 MB）                              ← 已上传 GitHub   │
│  D:\gz\xm\workBuddy_gj\gzkj\ai-novel\                            │
│    ├── novel-asset-hub\        L2 设定资产（应然）                │
│    ├── novel-memory-system\    L2 长程记忆（实然）                │
│    ├── novel-creation-engine\  L3 判据评审                        │
│    └── xs\                     L1 IP 证据采集（可选）             │
└─────────────────────────────────────────────────────────────────┘
                              │ 读
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  外部知识（2 GB）                              ← 不进仓库        │
│  D:\gz\xm\ai_gq\kf\xs_data\                                      │
│    └── data\ip\<ip>\processed\index\evidence.sqlite3              │
└─────────────────────────────────────────────────────────────────┘
                              │ 读
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  你的作品（约 3 MB）                           ← 不进仓库        │
│  D:\gz\cc\xm\综漫：\                                             │
│    ├── 原著\           投稿原件（只读）                          │
│    ├── processed\raw\  正文 89 章（工作副本）                    │
│    ├── 参考\           总纲 V2.0 等规范                          │
│    ├── 设定资产\       nah 工作区（卡片库）                      │
│    └── _backup\        备份区                                    │
└─────────────────────────────────────────────────────────────────┘
```

**核心原则**：代码单向读数据，数据永不写回代码目录。

---

## 二、代码位置（两份副本）

### 2.1 主副本 · monorepo　【以后改这里】

```
D:\gz\xm\workBuddy_gj\gzkj\ai-novel\
```

| 子项目 | 层 | 入口 | 说明 |
|---|---|---|---|
| `novel-asset-hub\` | L2 应然 | `nah.py` / `nah.bat` | 设定卡片库，零依赖 |
| `novel-memory-system\` | L2 实然 | `etl.py` / `wb_tools.py` | 需 PostgreSQL 16 + pgvector |
| `novel-creation-engine\` | L3 | `ce.py` / `ce.bat` | 判据评审，零依赖 |
| `xs\` | L1 | `run_ip_agent.py` | IP 证据采集与检索 |

顶层另有：`README.md`（三项目关系 + 独立使用方式）、`LICENSE`(MIT)、
`.gitignore`、`docs\`（architecture / creation-layer / design）、`push.bat`（一键推送）。

- 体积：**1 MB**
- 远端：https://github.com/ben3132/ai-novel （public，main 分支）
- 推送：`push.bat "你的提交说明"`

### 2.2 原副本 · ai1　【保留，仍可跑，但不建议改】

```
D:\gz\xm\workBuddy_gj\gzkj\ai1\novel-asset-hub\          278 KB
D:\gz\xm\workBuddy_gj\gzkj\ai1\novel-creation-engine\    115 KB
D:\gz\xm\workBuddy_gj\gzkj\ai1\novel-memory-system\       84 MB（含 .venv）
D:\gz\xm\ai_gq\kf\xs\                                    495 KB（xs 代码）
```

> ⚠️ **两份是彼此独立的副本。改一边不会同步到另一边。**
> 建议：只改 monorepo 那份；原副本作为回滚备份留着。

---

## 三、数据位置

### 3.1 你的作品　`D:\gz\cc\xm\综漫：\`

| 子目录 | 内容 | 大小 | 写入者 |
|---|---|---|---|
| `原著\` | 投稿原件 `*.docx` / `*.xlsx` | 1 MB | **只读，不可改** |
| `processed\raw\` | 正文工作副本 `ep_001–089.md` | 568 KB | 手工/Agent 改这里 |
| `参考\` | 总纲 `总纲-合并去重最终版-V2.0.md` 等 | 756 KB | 作者维护 |
| `设定资产\` | nah 工作区：`cards\` + `assets.db` + `workspace.json` | 150 KB | `nah add / sync` |
| `_backup\` | 历史备份、已退役引擎、评审报告存档 | 684 KB | 脚本自动 |

**`设定资产\` 内部结构**（这是 L2 应然侧的真相源）：

```
设定资产\
├── cards\<类型>\<名字>.md    ← 唯一真相源，人/Agent 手写
├── workspace.json             ← 工作区配置：项目名 / 类型集合 / chapters_dir / ip_evidence
├── assets.db                  ← SQLite 派生索引（可重建）
├── _registry.json             ← 派生缓存（可重建）
├── 00_索引.md                 ← 派生缓存（可重建）
├── _log.md                    ← 变更日志
└── README.md
```

> **铁律**：改过 `cards\` 必须跑 `nah sync`；改角色名必须用 `nah rename`，手工改文件名会产生断链。

### 3.2 外部知识　`D:\gz\xm\ai_gq\kf\xs_data\`（2 GB，不进仓库）

| 子目录 | 内容 |
|---|---|
| `data\ip\<ip>\processed\index\evidence.sqlite3` | **只读证据库**（表 `sources` / `text_units` / `context_windows` + FTS） |
| `source_l1\` | L1 官方一手来源归档 |
| `source_derived\` | 衍生转录来源归档 |

现有 IP：`ben10` / `jackie_chan` / `pacific_rim` / `douluo` / `lol`。

### 3.3 nms 数据库　PostgreSQL

- 当前状态：**本机未运行**，需 `docker compose up -d`（`novel-memory-system\docker-compose.yml`）
- 连接串：由 `novel-memory-system\.env` 的 `DATABASE_URL` 决定（该文件不入库）
- 数据落 Docker 命名卷 `pgdata`，不在上述任何目录内

---

## 四、工具怎么找到数据（四级路径解析）

`novel-creation-engine` 需要找到另外几个项目。解析顺序：

| 优先级 | 来源 | 用法 |
|---|---|---|
| ① | **环境变量** | `NAH_ENGINE` / `NMS_ROOT` / `XS_ROOT` / `XS_DATA` |
| ② | **同级目录** | `<本项目>\..\<子项目名>` —— monorepo 默认布局，**零配置** |
| ③ | **用户配置** | `~\.ai-novel\config.json`（在用户主目录，**不在仓库内**） |
| ④ | 占位符 | 报「未找到」并给配置提示 |

**当前实际解析结果**：

| 目标 | 来源 | 状态 |
|---|---|---|
| `nah` | [同级目录] | ✓ 可用 |
| `xs` | [同级目录] | ✓ 可用 |
| `nms` | [同级目录] | 找到，但缺 `asyncpg` / `pgvector` |
| `xs_data` | — | ✗ 未找到（不在同级）→ 建议写用户配置 |

### 让 `xs_data` 也能被找到

```bat
"D:\gz\xm\workBuddy_gj\gzkj\ai-novel\novel-creation-engine\ce.bat" ^
    config --set xs_data="D:/gz/xm/ai_gq/kf/xs_data"
```

查看当前配置 / 全部探测结果：

```bat
ce.bat config          :: 查看用户配置
ce.bat doctor          :: 查看每个工具解析到哪、从哪找到的
```

---

## 五、上 GitHub 与不进 GitHub

| 内容 | 位置 | 是否进仓库 |
|---|---|---|
| 工具代码 | `ai-novel\` | ✅ 是（190 文件） |
| 你的正文 | `综漫：\processed\raw\` | ❌ 否 |
| 设定卡片 | `综漫：\设定资产\cards\` | ❌ 否 |
| 写作规范 | `综漫：\参考\` | ❌ 否（属作品资产） |
| 原作证据库 | `xs_data\` | ❌ 否（2GB） |
| 凭据 / 本机配置 | `.env`、`nah.config.json`、`config\*.ps1` | ❌ 否（仓库内只有 `.example` 模板） |
| 运行产物 | `state\`、`logs\`、`reports\`、`__pycache__\` | ❌ 否 |

---

## 六、换机器 / 重装后怎么恢复

```bat
:: 1. 拿代码
git clone https://github.com/ben3132/ai-novel.git

:: 2. 装依赖
cd ai-novel\novel-memory-system
pip install -e .                       :: 需要 asyncpg + pgvector
docker compose up -d                   :: 起 PostgreSQL

:: 3. 搬数据（这三个都不在 git 里，需另行拷贝/备份）
::    · D:\gz\cc\xm\综漫：\              整目录
::    · D:\gz\xm\ai_gq\kf\xs_data\       整目录（2GB）
::    · 各项目的 .env / nah.config.json   按 .example 模板重建

:: 4. 指路（若数据不在默认位置）
ce.bat config --set xs_data="<新路径>"
ce.bat doctor                          :: 确认四个目标都 ✓
```

---

## 七、日常操作速查

```bat
:: 设定资产管理
nah.bat --ws 综漫 check                :: 全库审计
nah.bat --ws 综漫 brief <名字…>        :: 写作前取资料包
nah.bat --ws 综漫 add                   :: 登记新资产
nah.bat --ws 综漫 sync                  :: 改过 cards 后必跑

:: 章节评审
ce.bat review "<章.md 或目录>" --no-setting   :: 纯本地判据
ce.bat review "<章.md>"                       :: 含设定闸

:: 环境体检
ce.bat doctor
ce.bat config

:: 推送代码
cd D:\gz\xm\workBuddy_gj\gzkj\ai-novel
push.bat "feat: 说明"
```

---

*文档位置：`D:\gz\xm\workBuddy_gj\gzkj\ai-novel\docs\PATHS.md`*
