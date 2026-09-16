# IP Research Toolkit — Agent Operating Contract

This is a deterministic evidence toolkit, not an autonomous research application.
The connected Agent owns research judgment. Do not infer implemented functionality
from workflow prose: only operations returned by `get_agent_guidance` are callable.

## Required startup

1. Read `docs/AGENT_INTEGRATION_GUIDE.md` and `docs/IP_RESEARCH_PROTOCOL.md`.
2. Call `get_agent_guidance` before researching an unfamiliar IP.
3. Use a stable lowercase `ip_domain`; never reuse another IP's directory.
4. Call `initialize_ip`, then inspect `get_research_status` / `next_actions`.

## Agent responsibilities

- Interpret the user's research or writing goal.
- Discover the work tree, adaptations, continuities, reboots, and dynamic sources.
- Verify publisher/rights-holder identity and propose a justified trust level.
- Select the appropriate technical collector and continue low-risk local/read-only work.
- Keep novel, manga, animation, game, reboot, translation, and fan continuities separate.
- Use retrieved evidence when answering; model memory is never evidence.

`next_actions` returns advisory tasks, not operation names. Inspect each item's `kind`,
`directly_executable`, and `required_commands`. The missing-capability list in
`get_agent_guidance.not_implemented` is authoritative.

## Autonomy and stopping rules

Proceed without asking for every next step when the action is local, read-only,
reversible, low-cost, and within the user's stated IP scope. Stop and ask only for
missing credentials/files, paid access, CAPTCHA/login intervention, destructive
changes, copyright/access-control bypass, or a choice that materially changes scope.

Do not claim an IP is complete merely because one source was collected. Report
coverage by work/continuity/source type and explicitly list unresolved gaps.
“采集完成”“处理链完成”和“IP研究完成”是三个不同状态。调用
`get_corpus_status` 获取统计；只把 `source_artifact_count` 称为信源数量，PDF页、
XML节点、切片和窗口都不是独立信源。

L2、L3 可以按等级进入证据库；L3 不能单独支撑高置信结论。L4 只能提供线索，
不得参与设定推理。不得因为资料不是 L1 就拒绝归档。

## Data boundary

Never place collected or processed data in this code repository. Resolve the external
data root using `IP_SOURCE_DATA_ROOT`. Never commit credentials, original texts,
JSONL evidence, SQLite databases, FAISS indexes, WARC files, or generated dashboards.
