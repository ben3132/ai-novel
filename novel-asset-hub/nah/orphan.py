#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orphan.py —— 全库反向扫描：正文出现了、但资产库没登记的名称。

补齐一致性校验的**反方向**：
  · `check`    查「登记了但正文没出现」  —— 应然而实不然（冗余登记 / 别名没挂全）
  · `orphan`   查「正文出现了但没登记」  —— 实然而应不然（AI 现编设定的入口）

中文散文没有双链标记，所以用**句式启发式**抽专名候选。规则如下：
  1. 锚点：先定位说话动词（说/道/问/答/喊/叫），再向前回看本分句窗口；
  2. 定位对象：窗口里必须出现介词「对/跟/向/和/与」，取**最后一个**介词之后的名词短语；
  3. 清洗：优先取「最后一个『的』之后」的中心词，再剥掉前导虚词与尾部助词；
  4. 词频裁剪：候选收缩到「仍在全文中高频出现（≥MIN_FREQ）的最长前缀」；
  5. 过滤：代词/虚词打头、含代词的、常见名词一律丢弃。

精度定位：这是**启发式**，只求「高精度低漏报可人工复核」，不是自动拦截器。
输出按三类分：
  · 已登记    —— 命中资产库（正常，不列为问题）
  · 原作已知  —— 命中外部 IP 证据库（属 L1 知识层，无需登记）
  · 未登记    —— 两边都没有 ← 这才是「AI 现编」的入口，需人工确认

IP 证据库来自工作区配置 `ip_evidence`（见 workspace.py）；未配置时退化为二分类。
"""
import re
import sqlite3
import json
from collections import Counter
from pathlib import Path

from . import workspace as W

VERB_RE = re.compile(r"(说|道|问|答|喊|叫)")
LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
# 称谓式：句读边界后 + 名字 + 称谓词（龙叔 / 小玉姐 / 张池哥…）
TITLE_RE = re.compile(
    r"(?:^|[。！？…”\"\n，、：；])([\u4e00-\u9fa5]{1,3}(?:哥|姐|叔|爷|姨|婶|嫂|伯|兄))")
TITLE_CHARS = set("哥姐叔爷姨婶嫂伯兄")
# 称谓式里「动词+名字+称谓」粘连时的动词头（看到龙叔 → 看到龙）
BAD_TITLE_HEAD = set("看见到说想知道来去走听问答叫喊笑哭拿放带进出上下遇见撞碰"
                     "找追打抓拉推扔踢坐站躺跪跑逃躲闪转回望瞧瞅盯住让给")
PREPS = "对跟向和与"
CLAUSE_CUTS = "。！？…”\"\n，、：；"
WINDOW = 24

# 名词短语前可能出现的限定/修饰（出现在名字之前的整块）
LEAD_MOD = ("那个", "这个", "身旁的", "旁边的", "身边的", "身后的", "眼前的",
            "已经走进", "走进", "坐在", "站在", "对面", "后面", "前面")

# 打头就绝不可能是人名的字
BAD_HEAD = set("的了着于方是在有就也还又而且则才只被把给让使从向往对和与跟同为以因由除关至到哪什么怎这那其该他她它我你您咱谁")
# 名字里不该出现的字
BAD_ANY = set("他她它我你您咱谁这那其该")
# 尾部可剥掉的助词/趋向词
TAIL_STRIP = set("来说道问答应喊叫笑的着过并且而且然后接着才就也又")
# 常见名词（不是专名）
COMMON = set("""众人 大家 他们 她们 对方 自己 旁人 别人 所有 二人 三人 两人 一边
老头 小孩 男人 女人 少年 少女 孩子 家伙 东西 事情 问题 时候 地方 警察 同伴
人类 情报 空气 物体 反应 隐藏 处理 计划 命令 消息 原因 办法 方法 机会 状态
能力 力量 声音 帮助 区别 成员 战力 体型 目标 感觉 表情 画面 速度 标志 麻烦
身影 生物 系统 样子 技能 注意力 距离 理由 早餐 光芒 大爷 人才 魔物 结果
情况 经验 记忆 感情 情绪 意识 精神 身体 头脑 眼睛 嘴巴 大哥 大姐 大叔 小哥
小弟 小妹 师兄 师弟 师姐 师妹 师父 师傅 姑娘 小姐 先生 女士 阁下 大人
现在 但是 可是 因为 所以 如果 虽然 然后 于是 只是 就是 还是 或者 而且 并且
不过 除了 关于 对于 兄弟 姐妹 朋友 亲戚 同学 老师 学生 医生 护士""".split())

MIN_FREQ = 4          # 候选收缩时要求的最短前缀词频
DEFAULT_MIN_COUNT = 2  # 最终清单的频次门槛


class OrphanError(Exception):
    pass


# ---------------------------------------------------------------- 候选抽取

def raw_candidates(text):
    """从一段正文里抽出「专名候选」（未去重）。两条规则：介词锚定 + 称谓式。"""
    out = []
    for m in VERB_RE.finditer(text):
        win = text[max(0, m.start() - WINDOW):m.start()]
        cut = max(win.rfind(c) for c in CLAUSE_CUTS)
        if cut >= 0:
            win = win[cut + 1:]
        idx = -1
        for i in range(len(win) - 1, -1, -1):
            if win[i] in PREPS:
                if win[i] == "对" and win[i + 1:i + 2] == "方":   # 「对方」是名词
                    continue
                idx = i
                break
        if idx < 0:
            continue
        seg = win[idx + 1:]
        if "的" in seg:
            seg = seg.rsplit("的", 1)[1]
        for mod in LEAD_MOD:
            if seg.startswith(mod):
                seg = seg[len(mod):]
        seg = seg.strip("，、：； 　")
        m2 = re.match(r"([\u4e00-\u9fa5]{2,4})", seg)
        if m2:
            out.append(m2.group(1))

    for m in TITLE_RE.finditer(text):
        c = m.group(1)
        if len(c) >= 3 and c[-1] in TITLE_CHARS:   # 「小玉姐」→「小玉」
            base = c[:-1]
            if base[0] in BAD_TITLE_HEAD:          # 「看到龙叔」这类动词粘连
                continue
            c = base
        elif c[0] in BAD_TITLE_HEAD:
            continue
        out.append(c)
    return out


def shrink(cand, corpus, min_freq=MIN_FREQ):
    """把候选收缩到「仍高频出现的最长前缀」，裁掉粘上来的修饰语。"""
    for n in range(len(cand), 1, -1):
        if corpus.count(cand[:n]) >= min_freq:
            return cand[:n]
    return None


def plausible(cand):
    if len(cand) < 2 or cand[0] in BAD_HEAD:
        return False
    if any(ch in BAD_ANY for ch in cand):
        return False
    c = cand
    while c and c[-1] in TAIL_STRIP:
        c = c[:-1]
    if len(c) < 2 or c in COMMON:
        return False
    return True


def iter_chapters(chapters_dir):
    d = Path(chapters_dir)
    for p in sorted(d.glob("*.md")):
        yield p, p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- IP 证据库

def _open_evidence(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        con.execute("SELECT 1 FROM context_windows LIMIT 1")
        return con
    except Exception:
        return None


def _label(path):
    parts = Path(path).parts
    for i, seg in enumerate(parts):
        if seg == "ip" and i + 1 < len(parts):
            return parts[i + 1]
    return Path(path).parent.name


def load_ip_evidence(paths):
    """打开若干 evidence.sqlite3，返回 [(label, conn)]。"""
    out = []
    for path in paths or []:
        con = _open_evidence(path)
        if con is not None:
            out.append((_label(path), con))
    return out


def hit_ip(name, dbs, cache):
    if name not in cache:
        got = None
        for label, con in dbs:
            try:
                n = con.execute(
                    "SELECT 1 FROM context_windows WHERE text LIKE ? LIMIT 1",
                    (f"%{name}%",)).fetchone()
            except sqlite3.Error:
                n = None
            if n:
                got = label
                break
        cache[name] = got
    return cache[name]


# ---------------------------------------------------------------- 主流程

def scan_gap(root, cfg, chapters_dir=None, min_count=DEFAULT_MIN_COUNT,
             use_ip=True, db_paths=None):
    """全库反向扫描。返回 dict(registered/from_ip/unregistered/...) 。"""
    chapters = Path(chapters_dir) if chapters_dir else cfg.get("chapters_dir")
    if not chapters:
        raise OrphanError("未配置正文章节目录（可在 workspace.json 写 chapters_dir，或加 --chapters）")
    chapters = Path(chapters)
    if not chapters.exists():
        raise OrphanError(f"正文章节目录不存在：{chapters}")

    from . import core   # 延迟导入，避免与 core 互相 import

    entities = core.load_entities(root)
    known = set()
    for e in entities:
        known |= set(e["aliases"]) | {e["name"]}

    texts = list(iter_chapters(chapters))
    corpus = "\n".join(t for _, t in texts)

    cnt = Counter()
    first = {}
    links = Counter()
    for path, text in texts:
        for nm in LINK_RE.findall(text):
            nm = nm.split(":")[-1].split("：")[-1].strip()
            if nm:
                links[nm] += 1
                first.setdefault(nm, path.name)
        for cand in raw_candidates(text):
            c = shrink(cand, corpus)
            if not c or not plausible(c):
                continue
            cnt[c] += 1
            first.setdefault(c, path.name)

    dbs = load_ip_evidence(db_paths if db_paths is not None
                           else (cfg.get("ip_evidence") or [])) if use_ip else []
    cache = {}

    registered, from_ip, unregistered = [], [], []
    merged = Counter(cnt)
    for nm, c in links.items():          # 双链是精确引用，直接并入
        merged[nm] += c
    try:
        for nm, c in merged.most_common():
            if nm in known:
                registered.append({"name": nm, "count": c,
                                   "via": "links" if nm in links else "heuristic"})
                continue
            if dbs:
                lab = hit_ip(nm, dbs, cache)
                if lab:
                    from_ip.append({"name": nm, "count": c, "ip": lab})
                    continue
            if c < min_count and nm not in links:
                continue
            unregistered.append({"name": nm, "count": c, "first_seen": first.get(nm, ""),
                                 "via": "links" if nm in links else "heuristic"})
    finally:
        for _, con in dbs:
            try:
                con.close()
            except Exception:
                pass

    return {
        "chapters_dir": str(chapters),
        "chapter_count": len(texts),
        "ip_sources": [lab for lab, _ in dbs],
        "registered": registered,
        "from_ip": from_ip,
        "unregistered": unregistered,
        "counts": {
            "candidates": len(merged),
            "registered": len(registered),
            "from_ip": len(from_ip),
            "unregistered": len(unregistered),
        },
    }


# ---------------------------------------------------------------- 命令

def cmd_orphan(args):
    try:
        res = scan_gap(args.root, args._ws_cfg, chapters_dir=args.chapters,
                       min_count=args.min_count, use_ip=not args.no_ip)
    except OrphanError as ex:
        print(f"[错误] {ex}")
        return 2

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    name = args._ws_cfg["name"]
    c = res["counts"]
    print("=" * 60)
    print(f"{name} · 反向扫描（正文出现但未登记）　扫描 {res['chapter_count']} 章  "
          f"候选 {c['candidates']} 项")
    if res["ip_sources"]:
        print(f"IP 证据库：{'、'.join(res['ip_sources'])}")
    else:
        print("IP 证据库：未配置（无法区分原作角色，结果会偏多；"
              "可在 workspace.json 加 ip_evidence）")
    print("=" * 60)

    print(f"\n【未登记】{c['unregistered']} 项　← 重点复核（AI 现编设定的入口）")
    if not res["unregistered"]:
        print("  ✓ 无")
    else:
        rows = res["unregistered"][: args.top or 40]
        for it in rows:
            mark = "  (双链)" if it["via"] == "links" else ""
            print(f"  ✗ {it['name']:<10} x{it['count']:<4} 首次 {it['first_seen']}{mark}")
        if len(res["unregistered"]) > len(rows):
            print(f"  … 另有 {len(res['unregistered']) - len(rows)} 项")
        print("\n  → 逐条确认：是本书新设定就 `add` 登记；是笔误就改正文；")
        print("    属原作既有角色则把它加进 IP 证据库的采集范围。")

    print(f"\n【原作已知】{c['from_ip']} 项　← 命中 IP 证据库，属 L1 知识层，无需登记")
    for it in res["from_ip"][:15]:
        print(f"  ◐ {it['name']:<10} x{it['count']:<4} <- {it['ip']}")
    if len(res["from_ip"]) > 15:
        print(f"  … 另有 {len(res['from_ip']) - 15} 项")

    print(f"\n【已登记】{c['registered']} 项　← 正常命中资产库")
    for it in res["registered"][:15]:
        print(f"  ✓ {it['name']:<10} x{it['count']}")
    if len(res["registered"]) > 15:
        print(f"  … 另有 {len(res['registered']) - 15} 项")
    return 0


def register_cli(sub, add_common):
    p = sub.add_parser(
        "orphan",
        help="全库反向扫描：正文出现但资产库未登记的名称（自动区分原作角色）")
    add_common(p)
    p.add_argument("--chapters", help="正文章节目录（缺省用 workspace.json 的 chapters_dir）")
    p.add_argument("--min-count", dest="min_count", type=int, default=DEFAULT_MIN_COUNT,
                   help=f"未登记清单的频次门槛（默认 {DEFAULT_MIN_COUNT}）")
    p.add_argument("--top", type=int, default=0, help="只显示前 N 项")
    p.add_argument("--no-ip", dest="no_ip", action="store_true",
                   help="不查 IP 证据库，只做「已登记 / 未登记」二分类")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_orphan)
