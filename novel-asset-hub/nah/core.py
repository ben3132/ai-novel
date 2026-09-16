#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core.py —— 内容层：卡片读写、查重、扫描、资料包、一致性审计。

解决的问题：
  1) AI 写情节时随手造新角色/新设定  -> `add` 做重名/别名/相似度查重拦截
  2) AI 忘记自己之前设定过的内容      -> `brief` 在动笔前把相关资产原文喂回去
  3) 设定散落各处、前后矛盾           -> `check` 做断链/孤岛/双向标注/未使用审计

设计原则：**卡片是唯一真相源**，`_registry.json` 与 `00_索引.md` 都是派生缓存。
  卡片位置：`<工作区>/cards/<类型>/<名字>.md`
  跨实体引用语法：`[[实体名]]`（工具据此做断链检测与双向标注检查）

本模块不持有任何小说数据；工作区根目录由 `nah.workspace.resolve_root()` 解析。
"""
import argparse
import difflib
import json
import re
from datetime import datetime
from pathlib import Path

from . import workspace as W

CARD_DIR = W.CARD_DIR
LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)

# 打上此 tag 的卡片是「元设定」：约束的是**怎么写**（写作口径、配置表、修订台账），
# 而不是**世界里有什么**。这类卡片的整卡名不该出现在正文里，因此 `check` 对它
# 不做「已登记但正文未出现」判定，改为校验「其内部引用的实例是否已在正文落地」。
META_TAG = "元设定"


# ---------------------------------------------------------------- 基础工具

def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_front_matter(block):
    data = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            data[key] = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
        else:
            data[key] = val.strip("\"'")
    return data


def _fm_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if str(x).strip()]
    return [str(val)]


def parse_card(path):
    """读取一张卡片，返回 (meta, body, raw)。"""
    raw = Path(path).read_text(encoding="utf-8")
    m = FM_RE.match(raw)
    if not m:
        return {}, raw, raw
    return _parse_front_matter(m.group(1)), m.group(2).strip(), raw


def parse_relations(body):
    """从 '## 关系' 段落解析关系列表。[['kind','target','note'], ...]"""
    out = []
    m = re.search(r"^##\s*关系\s*$(.*?)(?=^##\s|\Z)", body, re.S | re.M)
    if not m:
        return out
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        line = line[1:].strip()
        lm = LINK_RE.search(line)
        if not lm:
            continue
        target = lm.group(1).split(":")[-1].split("：")[-1].strip()
        head = line[: lm.start()].strip(" -—:")
        kind = head.rstrip("：:") or "关联"
        note = line[lm.end():].strip(" -—:：")
        out.append({"kind": kind, "target": target, "note": note})
    return out


def body_links(body):
    return [x.split(":")[-1].split("：")[-1].strip() for x in LINK_RE.findall(body)]


def load_entities(root):
    """扫描 <root>/cards 目录，返回实体列表（卡片即真相源）。"""
    root = Path(root)
    entities = []
    cards_dir = root / CARD_DIR
    if not cards_dir.exists():
        return entities
    for path in sorted(cards_dir.rglob("*.md")):
        meta, body, _ = parse_card(path)
        if not meta.get("name"):
            continue
        etype = meta.get("type") or path.parent.name
        entities.append({
            "name": meta.get("name"),
            "type": etype,
            "status": meta.get("status", "稳定"),
            "aliases": _fm_list(meta.get("aliases")) or [meta.get("name")],
            "retired": _fm_list(meta.get("retired")),
            "tags": _fm_list(meta.get("tags")),
            "world": meta.get("world", ""),
            "first_seen": meta.get("first_seen", ""),
            "updated": meta.get("updated", ""),
            "file": str(path.relative_to(root)).replace("\\", "/"),
            "relations": parse_relations(body),
            "links": body_links(body),
            "body": body,
            "id": f"{etype}/{meta.get('name')}",
        })
    return entities


def normalize(s):
    return re.sub(r"[\s·・\-—_]", "", s or "")


# ---------------------------------------------------------------- 查重

def find_conflicts(entities, name, aliases, etype, exclude=None):
    """返回 (hard, soft)：hard=必须拦（同名/同别名），soft=疑似重复（相似度高）。"""
    hard, soft = [], []
    keys = [normalize(name)] + [normalize(a) for a in aliases]
    for e in entities:
        if exclude and e["name"] == exclude:
            continue
        ekeys = [normalize(e["name"])] + [normalize(a) for a in e["aliases"]]
        inter = set(keys) & set(ekeys)
        if inter:
            hard.append({"target": e["name"], "type": e["type"], "hit": sorted(inter)})
            continue
        ratio = 0.0
        for k in keys:
            for ek in ekeys:
                if not k or not ek:
                    continue
                ratio = max(ratio, difflib.SequenceMatcher(None, k, ek).ratio())
                # 中文短名：difflib 对「唐娅 vs 唐雅」只给 0.5，需按逐位重合率补判
                if len(k) == len(ek) and 2 <= len(k) <= 8:
                    same = sum(1 for a, b in zip(k, ek) if a == b)
                    if same / len(k) >= 0.5:
                        ratio = max(ratio, 0.65)
        if ratio >= 0.6:
            soft.append({"target": e["name"], "type": e["type"], "ratio": round(ratio, 2)})
    soft.sort(key=lambda x: -x["ratio"])
    return hard, soft


# ---------------------------------------------------------------- 写卡片

CARD_TMPL = """---
name: {name}
type: {type}
status: {status}
aliases: [{aliases}]
tags: [{tags}]
world: {world}
first_seen: {first_seen}
updated: {updated}
---

# {name}

## 一句话
{one_line}

## 档案
{body}

## 关系
{relations}

## 写作注意
{notes}
"""


def render_card(name, etype, status, aliases, tags, world, first_seen,
                one_line, body, relations, notes):
    rel_lines = ["- "]
    if relations:
        rel_lines = []
        for r in relations:
            kind = (r.get("kind") or "关联").rstrip("：:")
            note = (r.get("note") or "").strip()
            line = f"- {kind}：[[{r['target']}]]"
            if note:
                line += f"（{note}）"
            rel_lines.append(line)
    note_lines = [f"- {n}" for n in notes] if notes else ["- "]
    return CARD_TMPL.format(
        name=name, type=etype, status=status,
        aliases=", ".join(aliases), tags=", ".join(tags),
        world=world, first_seen=first_seen, updated=_today(),
        one_line=one_line or "",
        body=(body or "").strip() or "（待补充）",
        relations="\n".join(rel_lines),
        notes="\n".join(note_lines),
    )


def add_entity(root, name, etype, one_line="", body="", aliases=None, tags=None,
               world="", status="稳定", first_seen="", relations=None, notes=None,
               force=False, types=None):
    root = Path(root)
    types = list(types or W.DEFAULT_TYPES)
    if etype not in types:
        raise ValueError(f"未知类型：{etype}（本工作区可选：{'/'.join(types)}）")
    aliases = [a for a in (aliases or []) if a and a != name]
    entities = load_entities(root)
    hard, soft = find_conflicts(entities, name, aliases, etype)
    if (hard or soft) and not force:
        raise ValueError(json.dumps({"hard": hard, "soft": soft}, ensure_ascii=False))

    card_dir = root / CARD_DIR / etype
    card_dir.mkdir(parents=True, exist_ok=True)
    path = card_dir / f"{name}.md"
    text = render_card(name, etype, status, [name] + aliases,
                       tags or [], world, first_seen, one_line, body,
                       relations or [], notes or [])
    path.write_text(text, encoding="utf-8")
    return path, {"hard": hard, "soft": soft}


# ---------------------------------------------------------------- 索引

def build_index(root, cfg=None):
    root = Path(root)
    cfg = cfg or W.load_workspace(root)
    types = cfg["types"]
    entities = load_entities(root)
    reg = {
        "project": cfg["name"],
        "root": str(root),
        "generated_at": _now(),
        "count": len(entities),
        "entities": [
            {
                "id": e["id"], "type": e["type"], "name": e["name"],
                "aliases": e["aliases"], "status": e["status"], "tags": e["tags"],
                "world": e["world"], "first_seen": e["first_seen"],
                "file": e["file"], "relations": e["relations"],
            }
            for e in entities
        ],
    }
    (root / W.INDEX_NAME).write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# {cfg['name']} · 设定资产索引", "",
             f"> 自动生成于 {_now()}　共 **{len(entities)}** 项　"
             f"请勿手改，改动请编辑 `cards/` 下卡片后重跑 `index`", ""]
    known = set(types) | {e["type"] for e in entities}
    for t in list(types) + sorted(known - set(types)):
        group = [e for e in entities if e["type"] == t]
        if not group:
            continue
        lines += [f"## {t}（{len(group)}）", "",
                  "| 名称 | 别名 | 状态 | 所属世界 | 首次出现 | 一句话 / 关系 |",
                  "|---|---|---|---|---|---|"]
        for e in sorted(group, key=lambda x: x["name"]):
            al = "、".join(a for a in e["aliases"] if a != e["name"]) or "—"
            rel = "／".join(f"{r['kind']}·{r['target']}" for r in e["relations"]) or "—"
            tags = "、".join(e["tags"])
            note = (e["body"].split("## 一句话")[-1].split("##")[0].strip()
                    if "## 一句话" in e["body"] else "")
            cell = note.splitlines()[0] if note else ""
            if tags:
                cell = f"[{tags}] {cell}"
            if rel != "—":
                cell = f"{cell}　↔ {rel}" if cell else f"↔ {rel}"
            lines.append(f"| **{e['name']}** | {al} | {e['status']} | "
                         f"{e['world'] or '—'} | {e['first_seen'] or '—'} | {cell.strip() or '—'} |")
        lines.append("")
    (root / W.HUMAN_INDEX_NAME).write_text("\n".join(lines), encoding="utf-8")
    return reg


# ---------------------------------------------------------------- 命中检测

def detect(entities, text):
    """返回 {'hits':[{entity,count,spans}], 'unresolved':[名字,...]}"""
    lower_map = {}
    for e in entities:
        for a in set(e["aliases"]) | {e["name"]}:
            if len(a) >= 2:          # 单字别名噪声太大，不参与自动命中
                lower_map[a] = e
    spans_by_entity = {}
    for alias, e in sorted(lower_map.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(re.escape(alias), text):
            spans_by_entity.setdefault(e["name"], []).append((m.start(), m.end()))

    hits = []
    for e in entities:
        spans = spans_by_entity.get(e["name"], [])
        if not spans:
            continue
        merged = []
        for s, t in sorted(spans):
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], t))
            else:
                merged.append((s, t))
        hits.append({"entity": e, "count": len(merged), "spans": merged})
    hits.sort(key=lambda h: (-h["count"], h["entity"]["name"]))

    known = {e["name"] for e in entities}
    known |= {a for e in entities for a in e["aliases"]}
    unresolved = []
    for link in LINK_RE.findall(text):
        nm = link.split(":")[-1].split("：")[-1].strip()
        if nm not in known and nm not in unresolved:
            unresolved.append(nm)
    return {"hits": hits, "unresolved": unresolved}


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 命令

def cmd_init(args):
    p = W.scaffold(args.path, name=args.name, types=args.type,
                   chapters_dir=args.chapters, force=args.force)
    build_index(p)
    if args.as_name:
        W.register(args.as_name, p, set_default=args.default)
    print(f"[已初始化工作区] {p}")
    if args.as_name:
        print(f"[已登记] 名字「{args.as_name}」-> nah --ws {args.as_name} <命令>")
    print("  骨架：cards/<类型>/ + workspace.json + _log.md + README.md")
    print("  下一步：`nah add --type 人物 --name <名字> ...` 登记第一个资产")


def cmd_add(args):
    rels = []
    for r in args.rel or []:
        if ":" in r or "：" in r:
            kind, target = re.split(r"[:：]", r, maxsplit=1)
            rels.append({"kind": kind.strip(), "target": target.strip()})
        else:
            rels.append({"kind": "关联", "target": r.strip()})
    try:
        path, warn = add_entity(
            args.root, args.name, args.type, one_line=args.one_line or "",
            body=args.body or "", aliases=args.alias or [], tags=args.tag or [],
            world=args.world or "", status=args.status, first_seen=args.first_seen or "",
            relations=rels, notes=args.note or [], force=args.force,
            types=args._ws_cfg["types"])
    except ValueError as ex:
        try:
            data = json.loads(str(ex))
        except Exception:
            print(f"[错误] {ex}")
            return 1
        if data.get("hard"):
            print("[拦截] 名称/别名与已有资产冲突，拒绝登记：")
            for h in data["hard"]:
                print(f"  ✗ {h['target']}（{h['type']}）已占用：{'、'.join(h['hit'])}")
        if data.get("soft"):
            print("[疑似重复] 语义相近的既有资产，请先确认是不是同一个人/势力：")
            for s in data["soft"][:5]:
                print(f"  ? {s['target']}（{s['type']}）相似度 {s['ratio']}")
        print("\n确认确为新资产请加 --force 重跑。")
        return 1
    build_index(args.root, args._ws_cfg)
    print(f"[已登记] {args.type}/{args.name}  ->  {path}")
    if warn.get("soft"):
        print("[提示] 相似资产（已按 --force 放行）：")
        for s in warn["soft"][:5]:
            print(f"  ? {s['target']}（{s['type']}）相似度 {s['ratio']}")
    return 0


def cmd_ingest(args):
    """批量导入 JSON。格式：[{name,type,one_line,body,aliases,tags,world,status,relations,notes}]"""
    data = json.loads(read_text(args.file))
    if isinstance(data, dict):
        data = data.get("entities", [])
    ok, blocked, skipped = 0, [], 0
    types = args._ws_cfg["types"]
    for item in data:
        name = item.get("name")
        etype = item.get("type")
        if not name or not etype:
            skipped += 1
            continue
        rels = item.get("relations") or []
        rels = [{"kind": r, "target": ""} if isinstance(r, str) else r for r in rels]
        try:
            add_entity(args.root, name, etype,
                       one_line=item.get("one_line", ""), body=item.get("body", ""),
                       aliases=item.get("aliases") or [], tags=item.get("tags") or [],
                       world=item.get("world", ""), status=item.get("status", "稳定"),
                       first_seen=item.get("first_seen", ""), relations=rels,
                       notes=item.get("notes") or [], force=args.force, types=types)
            ok += 1
        except ValueError as ex:
            try:
                d = json.loads(str(ex))
                blocked.append((name, d))
            except Exception:
                blocked.append((name, {"hard": [{"target": str(ex), "type": "-", "hit": []}], "soft": []}))
    build_index(args.root, args._ws_cfg)
    print(f"[批量导入] 成功 {ok}｜冲突 {len(blocked)}｜跳过 {skipped}")
    for name, d in blocked[:10]:
        if d.get("hard"):
            print(f"  ✗ {name}：与 {'、'.join(h['target'] for h in d['hard'])} 冲突")
        elif d.get("soft"):
            print(f"  ? {name}：疑似 {'、'.join(s['target'] for s in d['soft'][:3])}")
    if blocked:
        print("  以上未写入，确认后用 --force 重跑或手工处理。")
    return 0


def cmd_list(args):
    entities = load_entities(args.root)
    types = args._ws_cfg["types"]
    if args.type:
        entities = [e for e in entities if e["type"] == args.type]
    if args.json:
        print(json.dumps(entities, ensure_ascii=False, indent=2))
        return 0
    if not entities:
        print("（空）")
        return 0
    order = {t: i for i, t in enumerate(types)}
    cur = None
    for e in sorted(entities, key=lambda x: (order.get(x["type"], 99), x["name"])):
        if e["type"] != cur:
            cur = e["type"]
            print(f"\n== {cur} ==")
        al = "、".join(a for a in e["aliases"] if a != e["name"])
        print(f"  {e['name']:<10} [{e['status']}] {('别名:' + al) if al else ''}")
    print(f"\n合计 {len(entities)} 项")
    return 0


def cmd_show(args):
    entities = load_entities(args.root)
    hit = [e for e in entities if e["name"] == args.name or args.name in e["aliases"]]
    if not hit:
        print(f"未找到资产：{args.name}")
        return 1
    print(read_text(Path(args.root) / hit[0]["file"]))
    return 0


def _render_brief(hits, unresolved, title, types):
    out = [f"# 写作资料包 · {title}", f"> 生成于 {_now()}｜命中 {len(hits)} 项已登记资产", ""]
    if unresolved:
        out += ["## ⚠ 未登记引用（请先登记或确认是否笔误）", ""]
        for u in unresolved:
            out.append(f"- `[[{u}]]` —— 库中无此资产")
        out.append("")
    if not hits:
        out += ["（本章未检测到已登记资产，请确认是否需要新登记）", ""]
        return "\n".join(out)
    by_type = {}
    for h in hits:
        by_type.setdefault(h["entity"]["type"], []).append(h)
    for t in types:
        group = by_type.get(t)
        if not group:
            continue
        out.append(f"## {t}")
        out.append("")
        for h in group:
            e = h["entity"]
            flag = "" if e["status"] == "稳定" else f"　⚠ {e['status']}"
            out.append(f"### {e['name']}（正文出现 {h['count']} 次）{flag}")
            out.append("")
            out.append(e["body"])
            out.append("")
    return "\n".join(out)


def cmd_brief(args):
    entities = load_entities(args.root)
    text = read_text(args.file)
    res = detect(entities, text)
    title = Path(args.file).stem
    md = _render_brief(res["hits"], res["unresolved"], title, args._ws_cfg["types"])
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"[资料包] 已写出 {args.out}（命中 {len(res['hits'])} 项）")
    else:
        print(md)
    return 0


def cmd_scan(args):
    entities = load_entities(args.root)
    text = read_text(args.file)
    res = detect(entities, text)
    if args.json:
        print(json.dumps({
            "file": args.file,
            "hits": [{"name": h["entity"]["name"], "type": h["entity"]["type"],
                      "status": h["entity"]["status"], "count": h["count"]} for h in res["hits"]],
            "unresolved": res["unresolved"],
        }, ensure_ascii=False, indent=2))
        return 0
    print(f"== 扫描 {Path(args.file).name} ==")
    print(f"命中已登记资产 {len(res['hits'])} 项：")
    for h in res["hits"]:
        e = h["entity"]
        mark = "" if e["status"] == "稳定" else f"  ⚠{e['status']}"
        print(f"  {e['type']:<4} {e['name']:<12} x{h['count']}{mark}")
    if res["unresolved"]:
        print(f"\n⚠ 未登记引用 {len(res['unresolved'])} 个（大纲里写了但库里没有）：")
        for u in res["unresolved"]:
            print(f"  [[{u}]]")
        print("  → 这是「AI 现编设定」的入口，动笔前必须先 add 或确认笔误。")
    else:
        print("\n未登记引用：无")
    return 0


def cmd_check(args):
    root = Path(args.root)
    entities = load_entities(root)
    by_name = {}
    for e in entities:
        by_name[e["name"]] = e
    alias_owner = {}
    for e in entities:
        for a in set(e["aliases"]) | {e["name"]}:
            alias_owner.setdefault(normalize(a), []).append(e["name"])

    problems = {"dangling": [], "dup_alias": [], "asymmetric": [], "unstable": [],
                "never_used": [], "meta_never_used": []}

    for e in entities:
        for lk in e["links"]:
            if lk not in by_name and not any(normalize(lk) == normalize(a) for a in alias_owner):
                problems["dangling"].append((e["name"], lk))
        if e["status"] != "稳定":
            problems["unstable"].append((e["name"], e["status"]))
        for r in e["relations"]:
            tgt = r["target"]
            other = by_name.get(tgt)
            if other is None:
                cand = [n for a, ns in alias_owner.items() if a == normalize(tgt) for n in ns]
                other = by_name.get(cand[0]) if cand else None
            if other is None:
                problems["dangling"].append((e["name"], tgt))
                continue
            back = any(normalize(rr["target"]) in {normalize(e["name"])} | {normalize(a) for a in e["aliases"]}
                       for rr in other["relations"])
            if not back:
                problems["asymmetric"].append((e["name"], tgt))

    for key, owners in alias_owner.items():
        if len(set(owners)) > 1:
            problems["dup_alias"].append((key, sorted(set(owners))))

    chapters = Path(args.chapters).resolve() if args.chapters else None
    if chapters is None:
        chapters = args._ws_cfg.get("chapters_dir")
    if chapters is not None:
        chapters = Path(chapters)
    if chapters and chapters.exists():
        corpus = "\n".join(read_text(p) for p in sorted(chapters.glob("*.md")))
        for e in entities:
            # 元设定豁免：tag 含「元设定」的卡片约束的是「怎么写」，其整卡名本就不该
            # 出现在正文里（正文用的是具体角色的具体说法）。这类卡片只需校验其
            # 内部引用的实例名是否已在正文落地，整卡名不入 never_used。
            tags = set(e.get("tags") or [])
            if META_TAG in tags:
                exposed = [a for a in set(e["aliases"]) | {e["name"]} if len(a) >= 2]
                # 只看「档案」段（=卡片的事实正文），不把「关系」段的卡片间引用
                # 当作正文实例——那不是「世界里有什么」的声明。
                body_txt = e.get("body") or ""
                m = re.search(r"^##\s*档案\s*$(.*?)(?=^##\s|\Z)", body_txt, re.M | re.S)
                decl = m.group(1) if m else body_txt
                inst = [w for w in re.findall(r"[\u4e00-\u9fa5A-Za-z·×0-9]{2,}", decl)
                        if w not in exposed]
                if not any(re.search(re.escape(a), corpus) for a in exposed + inst):
                    problems["meta_never_used"].append(e["name"])
                continue
            if not any(re.search(re.escape(a), corpus)
                       for a in set(e["aliases"]) | {e["name"]} if len(a) >= 2):
                problems["never_used"].append(e["name"])
    elif chapters:
        print(f"[提示] 正文章节目录不存在，跳过「正文未出现」审计：{chapters}")

    # 反方向闭环：正文出现了、但资产库没登记（AI 现编设定的入口）
    problems["unregistered"] = []
    if chapters and Path(chapters).exists():
        try:
            from . import orphan as _orphan
            gap = _orphan.scan_gap(args.root, args._ws_cfg, chapters_dir=chapters,
                                   use_ip=not getattr(args, "no_ip", False))
            problems["unregistered"] = gap["unregistered"]
            if not gap["ip_sources"]:
                print("[提示] 未配置 IP 证据库（workspace.json 的 ip_evidence），"
                      "反向扫描无法区分原作角色，结果会包含原作人物")
        except Exception as ex:
            print(f"[提示] 反向扫描跳过：{ex}")

    print("=" * 56)
    print(f"{args._ws_cfg['name']} · 设定资产一致性审计　共 {len(entities)} 项资产")
    print("=" * 56)

    def sec(title, rows, fmt):
        print(f"\n【{title}】{len(rows)} 项")
        if not rows:
            print("  ✓ 无")
            return
        for r in rows[:40]:
            print("  " + fmt(r))
        if len(rows) > 40:
            print(f"  … 另有 {len(rows)-40} 项")

    sec("断链引用（卡片引用了不存在的资产）", problems["dangling"],
        lambda r: f"✗ {r[0]}  →  [[{r[1]}]] 未登记")
    sec("别名冲突（多个资产共用同一名字/别名）", problems["dup_alias"],
        lambda r: f"✗ 「{r[0]}」被 {'、'.join(r[1])} 共用")
    sec("单向关系（A 引用了 B，但 B 未反向标注）", problems["asymmetric"],
        lambda r: f"? {r[0]} → {r[1]}（{r[1]} 未回标）")
    sec("非稳定状态（重判中/待确认，写作时需留意）", problems["unstable"],
        lambda r: f"⚠ {r[0]}：{r[1]}")
    sec("已登记但正文未出现（可能是冗余登记，或别名没挂对）", problems["never_used"],
        lambda r: f"- {r}")
    if problems["meta_never_used"]:
        sec("元设定且其实例未落地（tag=元设定的卡，连内部引用的实例名都没进正文）",
            problems["meta_never_used"], lambda r: f"- {r}")
    sec("正文出现但未登记（AI 现编设定的入口）", problems["unregistered"],
        lambda r: (f"✗ {r['name']}（x{r['count']}，首次 {r['first_seen']}）"
                   + ("  [双链]" if r.get("via") == "links" else "")))

    total = sum(len(v) for v in problems.values())
    print(f"\n合计问题 {total} 项。断链/别名冲突必须处理；单向关系可选补全；"
          f"未登记项逐条确认（新增则 add，笔误则改正文）。")
    meta_n = sum(1 for e in entities if META_TAG in set(e.get("tags") or []))
    if meta_n:
        print(f"（已豁免 {meta_n} 项元设定卡片——tag 为「{META_TAG}」的卡片不入正文，"
              f"不做「正文未出现」判定）")
    if args.json:
        print(json.dumps(problems, ensure_ascii=False, indent=2))
    return 0


def cmd_index(args):
    reg = build_index(args.root, args._ws_cfg)
    print(f"[索引已重建] {reg['count']} 项 -> {W.INDEX_NAME} / {W.HUMAN_INDEX_NAME}")


def cmd_log(args):
    log = Path(args.root) / W.LOG_NAME
    with log.open("a", encoding="utf-8") as f:
        f.write(f"- {_now()}　{args.text}\n")
    print(f"[已记录] {args.text}")


# ---------------------------------------------------------------- CLI 挂载

def register_cli(sub, add_common):
    """把内容层命令挂到统一 CLI 上。add_common(parser) 用于注入工作区解析。"""

    p = sub.add_parser("init", help="把一个目录初始化为工作区骨架")
    p.add_argument("path", help="工作区目录（不存在会自动创建）")
    p.add_argument("--name", help="小说名（默认取目录名）")
    p.add_argument("--type", action="append", help="自定义类型，可重复；缺省用内置 7 类")
    p.add_argument("--chapters", help="正文章节目录（相对工作区，供 check 审计）")
    p.add_argument("--as-name", dest="as_name", help="同时登记进项目配置，便于 --ws 引用")
    p.add_argument("--default", action="store_true", help="登记为默认工作区")
    p.add_argument("--force", action="store_true", help="目录已是工作区时强制重建骨架")
    p.set_defaults(func=cmd_init, _needs_ws=False)

    a = sub.add_parser("add", help="登记新资产（含三层查重）")
    add_common(a)
    a.add_argument("--name", required=True)
    a.add_argument("--type", required=True)
    a.add_argument("--alias", action="append")
    a.add_argument("--tag", action="append")
    a.add_argument("--world", default="")
    a.add_argument("--status", default="稳定")
    a.add_argument("--first-seen", dest="first_seen", default="")
    a.add_argument("--one-line", dest="one_line", default="")
    a.add_argument("--body", default="")
    a.add_argument("--rel", action="append", help="关系，形如 所属:蔷薇会")
    a.add_argument("--note", action="append")
    a.add_argument("--force", action="store_true")
    a.set_defaults(func=cmd_add)

    i = sub.add_parser("ingest", help="批量导入 JSON")
    add_common(i)
    i.add_argument("file")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_ingest)

    l = sub.add_parser("list", help="列出资产")
    add_common(l)
    l.add_argument("--type")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="查看卡片原文")
    add_common(s)
    s.add_argument("name")
    s.set_defaults(func=cmd_show)

    b = sub.add_parser("brief", help="写作前：输出资料包")
    add_common(b)
    b.add_argument("file")
    b.add_argument("--out")
    b.set_defaults(func=cmd_brief)

    sc = sub.add_parser("scan", help="写作前：扫描命中资产与未登记引用")
    add_common(sc)
    sc.add_argument("file")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=cmd_scan)

    c = sub.add_parser("check", help="全库一致性审计（含反向扫描）")
    add_common(c)
    c.add_argument("--chapters", help="正文章节目录（缺省用 workspace.json 的 chapters_dir）")
    c.add_argument("--no-ip", dest="no_ip", action="store_true",
                   help="反向扫描时不查 IP 证据库（只做二分类）")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_check)

    ix = sub.add_parser("index", help="重建 _registry.json 与 00_索引.md")
    add_common(ix)
    ix.set_defaults(func=cmd_index)

    g = sub.add_parser("log", help="追加一条工作区变更日志")
    add_common(g)
    g.add_argument("text")
    g.set_defaults(func=cmd_log)
