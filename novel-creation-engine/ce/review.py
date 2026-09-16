# -*- coding: utf-8 -*-
"""review.py —— 三闸门编排 + 「依据 → 命中 → 建议」三段式报告。

**这是 L3 唯一真正原创的部分。** 三闸门中：
  · 禁则闸 / 铁律闸 —— 纯本地判据（`ce.rules`），零外部依赖
  · 设定闸         —— 调外部：nah（应然侧）+ nms（实然侧），L3 不自己实现

设计原则：
  1. **零外部依赖也能跑**。设定闸的外部项目缺席时，报告降级但仍完整产出。
  2. **报告必须自陈局限**。每条命中都带置信度；报告抬头写明"是线索不是结论"。
  3. **判定权归人**。review 永不自动改正文。
"""

import os
import re
from datetime import datetime

from . import rules
from .adapters import nah, nms
from .adapters.base import ToolUnavailable

# 章节文件名的章号模式：ep_001.md / 第1章.md / 001.md
_CH_NO = re.compile(r"(\d{1,4})")


def guess_chapter_no(path):
    """从文件名猜章号。猜不出返回 None。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = _CH_NO.search(stem)
    return int(m.group(1)) if m else None


def review_file(path, rule_set=None, with_setting_gate=True, ws=None):
    """审一章。返回 dict（结构性结果，可 json 化）。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    ch_no = guess_chapter_no(path)
    hits = rules.run(text, chapter_no=ch_no, rules=rule_set)

    ch = {"path": path, "chapter_no": ch_no, "text": text, "hits": hits,
          "setting": None, "setting_error": None, "warnings": []}

    if with_setting_gate:
        try:
            ch["setting"] = _setting_gate(path, ch_no, ws)
        except ToolUnavailable as ex:
            ch["setting_error"] = str(ex)

    # 语料质量提示：正文里出现疑似导航栏/页脚残留
    navs = _detect_nav_residue(text)
    if navs:
        ch["warnings"].append(f"正文疑似含网页导航残留 {navs} 处（检查素材来源清洁度）")

    return ch


# ---------------------------------------------------------------- 设定闸

def _setting_gate(path, ch_no, ws):
    """设定闸：调外部项目，不自己实现。

    返回 {"nah": <原始文本或错误>, "nms": <校验结果或跳过原因>}
    """
    out = {"nah": None, "nms": None, "notes": []}

    # ① 应然侧：nah 六类审计（全局，不分章——一致性问题是全库性质）
    try:
        out["nah"] = nah.check(ws=ws)
    except ToolUnavailable as ex:
        out["nah"] = None
        out["notes"].append(f"nah 不可用，跳过设定审计：{str(ex)[:120]}")

    # ② 实然侧：nms 校验本章（需章号）
    if ch_no is None:
        out["notes"].append("文件名无法解析章号，跳过 nms 一致性校验")
    else:
        try:
            out["nms"] = nms.validate_consistency(ch_no)
        except ToolUnavailable as ex:
            out["notes"].append(f"nms 不可用，跳过一致性校验：{str(ex)[:120]}")

    return out


# ---------------------------------------------------------------- 语料清洁度

_NAV_MARK = re.compile(r"(设为首页|网站地图|观看记录|选择去向|客服|退出登录|VIP邮箱)")


def _detect_nav_residue(text):
    return len(_NAV_MARK.findall(text))


# ---------------------------------------------------------------- 报告渲染

CONF_ORDER = {"high": 0, "mid": 1, "low": 2}
SEV_ORDER = {"红线": 0, "铁律": 1, "闸门": 2, "提示": 3}


def render_report(ch, full_run=False):
    """把一章的 review 结果渲染成 Markdown 报告。"""
    hits = ch["hits"]
    by_sev = {}
    for h in hits:
        by_sev.setdefault(h.severity, []).append(h)

    name = os.path.basename(ch["path"])
    L = []
    L.append(f"# 判据评审报告 · {name}")
    L.append("")
    L.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"- 正文路径：`{ch['path']}`")
    L.append(f"- 章号：{ch['chapter_no'] if ch['chapter_no'] is not None else '（未识别）'}")
    L.append(f"- 正文字数：{len(ch['text'])}")
    L.append(f"- 命中合计：{len(hits)} 条"
             f"（红线 {len(by_sev.get('红线', []))} / 铁律 {len(by_sev.get('铁律', []))}"
             f" / 闸门 {len(by_sev.get('闸门', []))} / 提示 {len(by_sev.get('提示', []))}）")
    L.append("")

    # ---- 局限声明（必须有，且必须在最上面）
    L.append("> **已知局限（请先读）**")
    L.append(">")
    L.append("> 本报告由句式启发式生成，**精度优先、召回有限**。")
    L.append("> 它的定位是**人工复核清单，不是拦截器**——命中不等于违规，")
    L.append("> 未命中也不等于合格。凡标注 `置信度 low` 的条目，机器只是把可疑处")
    L.append("> 指给你看，判定权在你。")
    L.append(">")
    L.append("> 判据来源：`参考/总纲-合并去重最终版-V2.0.md` §23 / §24 / §25。")
    L.append("")

    for w in ch.get("warnings") or []:
        L.append(f"- ⚠️ {w}")
    if ch.get("warnings"):
        L.append("")

    # ---- 禁则闸
    L.append("## 一、禁则闸（§23 一级禁则）")
    L.append("")
    reds = sorted(by_sev.get("红线", []), key=lambda h: (h.line, CONF_ORDER.get(h.confidence, 9)))
    if reds:
        for i, h in enumerate(reds, 1):
            L.append(h.render(idx=i))
            L.append("")
    else:
        L.append("未命中。")
        L.append("")

    # ---- 铁律闸
    L.append("## 二、铁律闸（§24 写作铁律）")
    L.append("")
    rules_hits = sorted(by_sev.get("铁律", []), key=lambda h: h.line)
    if rules_hits:
        for i, h in enumerate(rules_hits, 1):
            L.append(h.render(idx=i))
            L.append("")
    else:
        L.append("未命中。")
        L.append("")

    # ---- 四层判定
    L.append("## 三、四层判定（§25 写完必过）")
    L.append("")
    L.append("四层判定中，**节拍闸与效用闸机器无法回答**，只能给出客观量与待答问题。"
             "请逐条作答后再定稿。")
    L.append("")
    gate_hits = sorted(by_sev.get("闸门", []), key=lambda h: h.rule_id)
    for i, h in enumerate(gate_hits, 1):
        L.append(h.render(idx=i))
        L.append("")

    # ---- 提示
    notes = sorted(by_sev.get("提示", []), key=lambda h: h.line)
    if notes:
        L.append("## 四、机器提示（非判据，仅供参考）")
        L.append("")
        for i, h in enumerate(notes, 1):
            L.append(h.render(idx=i))
            L.append("")

    # ---- 设定闸
    L.append("## 五、设定闸（外部项目裁决，L3 仅转述）")
    L.append("")
    st = ch.get("setting")
    if st is None and ch.get("setting_error"):
        L.append(f"设定闸未能运行：{ch['setting_error'][:300]}")
        L.append("")
    elif st is None:
        L.append("（本次运行未启用设定闸）")
        L.append("")
    else:
        L.append("### 5.1 应然侧 · nah 设定资产审计")
        L.append("")
        L.append("```")
        L.append((st.get("nah") or "（不可用）").rstrip())
        L.append("```")
        L.append("")
        L.append("### 5.2 实然侧 · nms 本章一致性校验")
        L.append("")
        if st.get("nms") is None:
            L.append("（未运行）")
        else:
            import json
            try:
                L.append("```json")
                L.append(json.dumps(st["nms"], ensure_ascii=False, indent=2)[:3000])
                L.append("```")
            except Exception:
                L.append(str(st["nms"])[:3000])
        L.append("")
        for n in st.get("notes") or []:
            L.append(f"- {n}")
        L.append("")

    L.append("---")
    L.append("")
    L.append("*本报告由 `novel-creation-engine` 的 `ce review` 生成。"
             "report 是纯派生输出，可随时删除重建；**不要把判定结果写回这里**，"
             "需要固化的结论请写入 novel-asset-hub 的卡片。*")
    return "\n".join(L)


def render_summary(chapters):
    """多章汇总（批量跑时用）。"""
    L = [f"# 判据评审汇总 · {len(chapters)} 章", ""]
    L.append("| 章 | 红线 | 铁律 | 闸门 | 提示 | 合计 |")
    L.append("|---|---|---|---|---|---|")
    tot = [0, 0, 0, 0]
    for ch in chapters:
        c = {}
        for h in ch["hits"]:
            c[h.severity] = c.get(h.severity, 0) + 1
        row = [c.get("红线", 0), c.get("铁律", 0), c.get("闸门", 0), c.get("提示", 0)]
        tot = [a + b for a, b in zip(tot, row)]
        L.append(f"| {os.path.basename(ch['path'])} | {row[0]} | {row[1]} | {row[2]} "
                 f"| {row[3]} | {sum(row)} |")
    L.append(f"| **合计** | {tot[0]} | {tot[1]} | {tot[2]} | {tot[3]} | {sum(tot)} |")
    L.append("")
    L.append("> 命中数不等于质量问题数。**红线**条目应逐条人工过一遍；"
             "闸门/提示条目是待答问题与线索。")
    return "\n".join(L)
