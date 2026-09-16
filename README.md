# ai-novel —— AI 小说创作工具链

一套给**长篇连载小说**用的工程化工具。核心问题是：**AI 写到第 300 章时，还记得第 30 章定下的设定吗？**

它由三个互相独立、各自能单独跑的项目组成，合起来覆盖「**查资料 → 记住自己 → 审自己**」这三件事。

```
你的小说仓库（正文 · 规范 · 素材）
        │
        │  ① 写之前：查原作资料
        ▼
┌──────────────────┐
│  xs              │  L1 外部知识 —— 把原作（动漫/游戏/小说）拆成可溯源的证据库
│  IP 证据采集      │  回答「这个原作里，某某到底是什么样，原文怎么写的」
└──────────────────┘
        │
        │  ② 写的时候：查自己定下的设定
        ▼
┌──────────────────┐
│  novel-asset-hub │  L2 本书事实「应然」—— 作者裁定的设定卡片库
│  设定资产管理     │  回答「这条设定**应该**是什么」；写前给 Brief，写后做审计
└──────────────────┘
        │                    ▲
        │                    │ 双向校验
        ▼                    │
┌──────────────────┐        │
│  novel-memory-   │  L2 本书事实「实然」—— 从已写正文 ETL 提取的记忆库
│  system          │  回答「正文里**实际**写了什么」，可随时重建
└──────────────────┘
        │
        │  ③ 写完：按规范审这一章
        ▼
┌──────────────────┐
│  novel-creation- │  L3 创作层 —— 薄编排 + 判据裁决
│  engine          │  把写作规范变成可执行检查，出「依据→命中→建议」三段式报告
└──────────────────┘
```

---

## 三个项目各管什么

| 项目 | 层 | 一句话 | 没有它会怎样 |
|---|---|---|---|
| **[novel-asset-hub](novel-asset-hub/)** | L2·应然 | 作者裁定的设定真相，写成 Markdown 卡片；写前 `brief`、写后 `check` | AI 每次设计情节都造新角色、忘掉旧设定 |
| **[novel-memory-system](novel-memory-system/)** | L2·实然 | 从已写正文自动提取事实，存 PostgreSQL + pgvector | 「正文里到底写没写过」只能靠人翻 |
| **[novel-creation-engine](novel-creation-engine/)** | L3 | 按正确时序调上面这些，并按小说规范裁决正文 | 写作流程全靠人记，判据全靠人眼 |
| **[xs](xs/)**（可选） | L1 | 采集原作证据，建可溯源证据库 | 跨世界观同人作里，「哪些名字是原作的」只能靠记忆 |

**为什么 L2 是两个项目？** 因为它们存的是**两种性质不同的东西**：

- `novel-asset-hub` 存**应然** —— 作者的判决。不能从正文反推出来，也不能被自动重建。
- `novel-memory-system` 存**实然** —— 从正文抽取的观测结果。删了重跑 ETL 就有。

**两者都不能当对方的副本。** 而它们的**差集**恰恰是最有价值的东西：正文写了但卡片库里没登记 → 这正是「AI 现编设定」的入口。这也就是上图那个「双向校验」。

---

## 每个项目都可以单独用

这是刻意的设计。你不需要装齐四个才能开始。

| 你只想…… | 那就只装 |
|---|---|
| 管设定、防止 AI 忘设定 | `novel-asset-hub`（零依赖，纯 Python 标准库） |
| 从已写正文建记忆库做检索 | `novel-memory-system`（需 PostgreSQL 16 + pgvector） |
| 按规范审章节正文 | `novel-creation-engine`（零依赖，纯标准库） |
| 采集原作资料 | `xs`（需 Python + 可选 Ollama/OpenAI 兼容模型） |

`novel-creation-engine` 会在启动时探测另外几个项目在不在。**不在也不影响使用**：

```bash
# 外部项目都没装？加 --no-setting 跳过设定闸，禁则闸 + 铁律闸是纯本地的
python ce.py review 我的章节.md --no-setting
```

---

## 快速开始

### 只想要其中一个

```bash
cd novel-asset-hub
python nah.py init "/path/to/我的小说/设定资产"
python nah.py --ws 我的小说 check
```

### 想要全套（推荐布局）

把四个项目放在**同一个父目录**下，引擎会自动按同级目录找到彼此，**零配置**：

```
ai-novel/
├── novel-asset-hub/
├── novel-memory-system/
├── novel-creation-engine/
└── xs/
```

```bash
cd novel-creation-engine
python ce.py doctor      # 看它认出了哪些外部项目、分别从哪里找到的
```

`doctor` 会打印每个项目的 **[来源]路径**，四种来源按优先级：

1. **环境变量** —— `NAH_ENGINE` / `NMS_ROOT` / `XS_ROOT` / `XS_DATA`
2. **同级目录** —— 上面那种布局，自动发现
3. **用户配置** —— `~/.ai-novel/config.json`（用 `ce config --set nah_engine=... ` 写；在用户主目录，不进仓库）
4. 都没有 → 报「未找到」并提示怎么配

三个项目**不需要**待在同一个父目录，各自 clone 到任意位置、用环境变量指过去同样可以。

---

## 代码与数据分离

本仓库**只放代码**。以下内容一律不入库，`git clone` 拿到的是干净的工具：

| 类别 | 举例 | 处理方式 |
|---|---|---|
| 你的小说正文 | `data/chapters/*.md`、`processed/raw/*.md` | 由你自建仓库管理 |
| 设定卡片 | `cards/**/*.md` | 属于你的作品资产，不属于工具 |
| 本机路径与凭据 | `.env`、`nah.config.json`、`config/*.ps1` | `.gitignore` 已排除，仓库内只有 `.example` 模板 |
| 运行产物 | `state/`、`logs/`、`__pycache__/`、`*.egg-info/` | 运行时自动创建 |
| 派生的评审报告 | `reports/` | 随时可删可重建 |

每引入一个真实路径，仓库里就多一个 `.example` 模板；跑起来的第一步永远是 `cp xxx.example xxx`。

---

## 更新这个仓库

改完代码后：

```bat
push.bat "feat: 你的改动说明"
```

或手动：

```bash
git add -A
git commit -m "feat: 你的改动说明"
git push origin main
```

凭据走系统凭据管理器，不会把 token 写进 `.git/config`。

---

## 文档

- [`docs/architecture.md`](docs/architecture.md) —— 完整分层设计、各层职责边界、已知缺口
- [`docs/creation-layer.md`](docs/creation-layer.md) —— L3 创作层的设计论证与踩坑记录
- 各子项目目录内另有自己的 `README.md` 与 `CHANGELOG.md`

---

## 许可

MIT，见 [LICENSE](LICENSE)。
