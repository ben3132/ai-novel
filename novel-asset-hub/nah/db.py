#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""db.py —— 索引与版本层（SQLite）。

定位：**卡片（`<工作区>/cards/*.md`）仍是唯一真相源**，本层是它的派生索引。
加这一层，是为了两件文件系统给不了的能力：

  1) 结构化查询 —— 资产膨胀后，「找出符合条件的资产」；
  2) 变更历史   —— 旧设定会被修改，必须能追溯「谁在何时因何改了什么」；
  3) 影响面分析 —— 改一个名字/设定，哪些卡片要跟着动（反向引用）。

命令：
  sync                 从卡片重建索引库，并记录本次变更（append-only）
  find                 按条件筛选（--type/--world/--status/--tag/--grep/--alias）
  query "<SELECT...>"  直接跑 SQL（仅 SELECT）
  history <名字>       某资产的完整变更史
  recent [N]           全库最近 N 条变更
  impact <名字>        谁引用了它（反向引用 / 影响面）
  rename <旧> <新>     改名并全库传播：旧名降级为 retired 别名，正文 [[旧]]→[[新]]
  dupe                 列出别名冲突（同一别名被多个资产占用）
  info                 索引概况 + 新鲜度检查
"""
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from . import core as A
from . import workspace as W

DB_NAME = W.DB_NAME

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities(
  id TEXT PRIMARY KEY, type TEXT, name TEXT, status TEXT, world TEXT,
  first_seen TEXT, file TEXT, updated TEXT, body TEXT,
  aliases_json TEXT, retired_json TEXT, relations_json TEXT, links_json TEXT,
  content_hash TEXT, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS aliases(
  alias TEXT, entity_id TEXT, kind TEXT,
  PRIMARY KEY(alias, entity_id)
);
CREATE TABLE IF NOT EXISTS relations(
  src TEXT, kind TEXT, dst TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS links(
  src TEXT, dst TEXT
);
CREATE TABLE IF NOT EXISTS revisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, entity_id TEXT, action TEXT, field TEXT, old TEXT, new TEXT, note TEXT
);
CREATE INDEX IF NOT EXISTS idx_alias     ON aliases(alias);
CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst);
CREATE INDEX IF NOT EXISTS idx_rel_dst   ON relations(dst);
CREATE INDEX IF NOT EXISTS idx_rev_ent   ON revisions(entity_id);
"""

TRACKED_FIELDS = [("name", "名称"), ("status", "状态"), ("world", "所属世界"),
                  ("first_seen", "首次出现"), ("body", "正文"), ("file", "文件"),
                  ("aliases", "别名"), ("relations", "关系")]


# ---------------------------------------------------------------- 基础

def db_path(root):
    return Path(root) / DB_NAME


_OPEN_CONNS = []


def connect(root):
    con = sqlite3.connect(db_path(root))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _OPEN_CONNS.append(con)
    return con


def close_all():
    """统一收口：CLI 退出前关闭所有连接，避免 ResourceWarning 与文件句柄泄漏。"""
    while _OPEN_CONNS:
        try:
            _OPEN_CONNS.pop().close()
        except Exception:
            pass


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def entity_hash(e):
    payload = json.dumps({
        "name": e["name"], "type": e["type"], "status": e["status"],
        "world": e["world"], "first_seen": e["first_seen"], "file": e["file"],
        "aliases": sorted(e["aliases"]), "relations": e["relations"], "body": e["body"],
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def add_revision(con, entity_id, action, field, old, new, note=""):
    con.execute("INSERT INTO revisions(ts,entity_id,action,field,old,new,note) "
                "VALUES(?,?,?,?,?,?,?)", (_now(), entity_id, action, field,
                                          str(old)[:4000], str(new)[:4000], note))


def _body_delta(old, new):
    """正文变更只记「增删行摘要」，不把整篇灌进历史。"""
    ol = [l.strip() for l in (old or "").splitlines() if l.strip()]
    nl = [l.strip() for l in (new or "").splitlines() if l.strip()]
    added = [l for l in nl if l not in ol]
    removed = [l for l in ol if l not in nl]
    fmt = lambda xs: " ／ ".join(x[:36] for x in xs[:3]) + (" …" if len(xs) > 3 else "") if xs else "—"
    return fmt(removed), fmt(added)


# ---------------------------------------------------------------- sync

def _upsert_entity(con, e, h):
    eid = e["id"]
    con.execute("DELETE FROM entities WHERE id=?", (eid,))
    con.execute(
        "INSERT INTO entities(id,type,name,status,world,first_seen,file,updated,body,"
        "aliases_json,retired_json,relations_json,links_json,content_hash,synced_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, e["type"], e["name"], e["status"], e["world"], e["first_seen"],
         e["file"], e["updated"], e["body"],
         json.dumps(e["aliases"], ensure_ascii=False),
         json.dumps(e.get("retired", []), ensure_ascii=False),
         json.dumps(e["relations"], ensure_ascii=False),
         json.dumps(e["links"], ensure_ascii=False), h, _now()))

    con.execute("DELETE FROM aliases WHERE entity_id=?", (eid,))
    con.execute("INSERT INTO aliases VALUES(?,?,?)", (e["name"], eid, "name"))
    for al in e["aliases"]:
        if al == e["name"]:
            continue
        kind = "retired" if al in (e.get("retired") or []) else "alias"
        con.execute("INSERT OR REPLACE INTO aliases VALUES(?,?,?)", (al, eid, kind))

    con.execute("DELETE FROM relations WHERE src=?", (e["name"],))
    for r in e["relations"]:
        con.execute("INSERT INTO relations VALUES(?,?,?,?)",
                    (e["name"], r.get("kind", ""), r.get("target", ""), r.get("note", "")))

    con.execute("DELETE FROM links WHERE src=?", (e["name"],))
    for lk in set(e["links"]):
        con.execute("INSERT INTO links VALUES(?,?)", (e["name"], lk))


def cmd_sync(args):
    root = Path(args.root)
    con = connect(root)
    ents = A.load_entities(root)
    old = {r["id"]: dict(r) for r in con.execute("SELECT * FROM entities")}
    seen, created, updated, deleted = set(), 0, 0, 0

    for e in ents:
        eid = e["id"]
        seen.add(eid)
        h = entity_hash(e)
        prev = old.get(eid)

        if prev is None:
            add_revision(con, eid, "create", "资产", "", e["name"], args.note or "新建")
            created += 1
        elif prev["content_hash"] != h:
            prev_meta = dict(prev)
            for f in ("aliases", "retired", "relations", "links"):
                prev_meta[f] = json.loads(prev.get(f + "_json") or "[]")
            for field, label in TRACKED_FIELDS:
                if field in ("aliases", "relations"):
                    a = sorted(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in prev_meta[field])
                    b = sorted(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in e[field])
                    if a != b:
                        add_revision(con, eid, "update", label,
                                     "、".join(x if isinstance(x, str) else x.get("target", str(x)) for x in prev_meta[field]),
                                     "、".join(x if isinstance(x, str) else x.get("target", str(x)) for x in e[field]),
                                     args.note)
                    continue
                if (prev.get(field) or "") != (e.get(field) or ""):
                    if field == "body":
                        rem, add = _body_delta(prev.get(field) or "", e.get(field) or "")
                        add_revision(con, eid, "update", "正文", rem, add, args.note)
                    else:
                        add_revision(con, eid, "update", label, prev.get(field) or "",
                                     e.get(field) or "", args.note)
            updated += 1

        _upsert_entity(con, e, h)

    for eid in set(old) - seen:
        add_revision(con, eid, "delete", "资产", old[eid]["name"], "", args.note or "卡片已移除")
        con.execute("DELETE FROM entities WHERE id=?", (eid,))
        con.execute("DELETE FROM aliases WHERE entity_id=?", (eid,))
        con.execute("DELETE FROM relations WHERE src=?", (eid,))
        con.execute("DELETE FROM links WHERE src=?", (eid,))
        deleted += 1

    A.build_index(root, args._ws_cfg)
    with (root / W.LOG_NAME).open("a", encoding="utf-8") as f:
        f.write(f"- {_now()}　[sync] 新建 {created}｜更新 {updated}｜移除 {deleted}\n")
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    print(f"[sync] 新建 {created}｜更新 {updated}｜移除 {deleted}　索引共 {total} 项 -> {DB_NAME}")
    return 0


# ---------------------------------------------------------------- 查询

def _rows(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params)]


def cmd_find(args):
    root = Path(args.root)
    con = connect(root)
    sql = "SELECT * FROM entities WHERE 1=1"
    p = []
    if args.type:
        sql += " AND type=?"; p.append(args.type)
    if args.world:
        sql += " AND world LIKE ?"; p.append(f"%{args.world}%")
    if args.status:
        sql += " AND status=?"; p.append(args.status)
    if args.grep:
        sql += " AND (body LIKE ? OR name LIKE ? OR aliases_json LIKE ?)"
        p += [f"%{args.grep}%"] * 3
    if args.alias:
        sql += " AND id IN (SELECT entity_id FROM aliases WHERE alias LIKE ?)"
        p.append(f"%{args.alias}%")
    rows = _rows(con, sql + " ORDER BY type, name", p)
    if args.tag:
        tagmap = {e["name"]: (e.get("tags") or []) for e in A.load_entities(root)}
        rows = [r for r in rows if args.tag in tagmap.get(r["name"], [])]
    if not rows:
        print("（无匹配）")
        return 0
    print(f"命中 {len(rows)} 项：")
    for r in rows:
        al = "、".join(a for a in json.loads(r["aliases_json"] or "[]") if a != r["name"]) or "—"
        print(f"  [{r['type']}] {r['name']:<14} 状态:{r['status']:<5} 世界:{r['world'] or '—':<10} 别名:{al}")
    return 0


def cmd_query(args):
    root = Path(args.root)
    con = connect(root)
    sql = args.sql.strip()
    if not re.match(r"^\s*(select|with)\b", sql, re.I):
        print("[拒绝] 只允许 SELECT / WITH 查询（本层不写业务数据，写入走卡片）")
        return 1
    try:
        rows = _rows(con, sql)
    except sqlite3.Error as ex:
        print(f"[SQL 错误] {ex}")
        return 1
    if not rows:
        print("（无结果）")
        return 0
    cols = list(rows[0].keys())
    print(" | ".join(cols))
    print("-" * 60)
    for r in rows[:200]:
        print(" | ".join(str(r[c])[:40] for c in cols))
    print(f"\n{len(rows)} 行")
    return 0


def history_lineage(con, eid):
    """顺着 rename 记录回溯，返回该资产的完整 id 链（旧 → 新）。

    改名会把实体 id 从「类型/旧名」换成「类型/新名」，若不回溯，改名前
    的历史就会查不到——这条链把断掉的历史接回来。
    """
    chain, seen, cur = [eid], {eid}, eid
    while True:
        prev = None
        for r in _rows(con, "SELECT * FROM revisions WHERE entity_id=? AND action='rename' ORDER BY id",
                       (cur,)):
            if r["old"] and r["new"]:
                prev = f"{cur.split('/')[0]}/{r['old']}"
                break
        if not prev or prev in seen:
            break
        chain.append(prev)
        seen.add(prev)
        cur = prev
    return list(reversed(chain))


def cmd_history(args):
    root = Path(args.root)
    con = connect(root)
    eid = args.name
    if con.execute("SELECT 1 FROM entities WHERE id=?", (eid,)).fetchone() is None:
        hit = con.execute("SELECT entity_id FROM aliases WHERE alias=?", (eid,)).fetchone()
        if hit:
            eid = hit[0]
    chain = history_lineage(con, eid)
    marks = ",".join("?" * len(chain))
    rows = _rows(con, f"SELECT * FROM revisions WHERE entity_id IN ({marks}) ORDER BY id", chain)
    if not rows:
        print(f"（{args.name} 无变更记录；试试先跑 sync）")
        return 0
    suffix = f"｜含前身：{' → '.join(chain)}" if len(chain) > 1 else ""
    print(f"== {eid} 的变更史（{len(rows)} 条）{suffix} ==")
    for r in rows:
        if r["action"] == "create":
            print(f"  #{r['id']:<4} {r['ts']}  ＋ 新建")
        elif r["action"] == "delete":
            print(f"  #{r['id']:<4} {r['ts']}  － 移除（原名 {r['old']}）")
        else:
            old, new = r["old"] or "—", r["new"] or "—"
            if len(old) > 40: old = old[:40] + "…"
            if len(new) > 40: new = new[:40] + "…"
            print(f"  #{r['id']:<4} {r['ts']}  ~ {r['field']}：{old}  →  {new}")
        if r["note"]:
            print(f"          备注：{r['note']}")
    return 0


def cmd_recent(args):
    root = Path(args.root)
    con = connect(root)
    rows = _rows(con, "SELECT * FROM revisions ORDER BY id DESC LIMIT ?", (args.n,))
    if not rows:
        print("（无记录）")
        return 0
    for r in rows:
        tgt = r["entity_id"].split("/")[-1]
        old = (r["old"] or "")[:24]
        new = (r["new"] or "")[:24]
        if r["action"] == "create":
            desc = "＋新建"
        elif r["action"] == "delete":
            desc = "－移除"
        else:
            desc = f"~{r['field']} {old} → {new}"
        note = f"　[{r['note']}]" if r["note"] else ""
        print(f"  {r['ts']}  {tgt:<12} {desc}{note}")
    return 0


def cmd_impact(args):
    """改这个资产，会影响哪些地方 —— 反向引用分析。"""
    root = Path(args.root)
    con = connect(root)
    name = args.name
    eid = name
    row = con.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
    if row is None:
        hit = con.execute("SELECT entity_id FROM aliases WHERE alias=?", (name,)).fetchone()
        if hit:
            eid = hit[0]
            row = con.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
    if row is None:
        print(f"未找到资产：{name}")
        return 1
    print(f"== 改动「{row['name']}」的影响面 ==")
    lk = _rows(con, "SELECT src FROM links WHERE dst=? AND src<>?", (row["name"], row["name"]))
    rel = _rows(con, "SELECT src,kind,note FROM relations WHERE dst=? AND src<>?", (row["name"], row["name"]))
    alias_hit = _rows(con, "SELECT entity_id,alias,kind FROM aliases WHERE alias=? AND entity_id<>?",
                      (row["name"], eid))
    print(f"\n【正文中引用它（[[{row['name']}]]）】{len(lk)} 处")
    for r in lk:
        print(f"  ← {r['src']}")
    print(f"\n【关系指向它】{len(rel)} 处")
    for r in rel:
        print(f"  ← {r['src']}　（{r['kind']}）{'　' + r['note'] if r['note'] else ''}")
    if alias_hit:
        print(f"\n【别名撞车】{len(alias_hit)} 处（改名/合并时要一并处理）")
        for r in alias_hit:
            print(f"  ! {r['entity_id']} 也用「{r['alias']}」（{r['kind']}）")
    print("\n→ 以上卡片在本资产变更后需要人工复核。设定类改动无法自动传播，只能靠这张清单。")
    return 0


def cmd_dupe(args):
    root = Path(args.root)
    con = connect(root)
    rows = _rows(con, """
        SELECT alias, GROUP_CONCAT(entity_id, '、') AS owners, COUNT(*) AS n
        FROM aliases GROUP BY alias HAVING n > 1 ORDER BY n DESC""")
    if not rows:
        print("[别名冲突] 无")
        return 0
    print(f"[别名冲突] {len(rows)} 条")
    for r in rows:
        print(f"  「{r['alias']}」被 {r['owners']} 共用")
    return 0


# ---------------------------------------------------------------- 改名传播

def _update_front_matter(path, updates):
    raw = Path(path).read_text(encoding="utf-8")
    m = A.FM_RE.match(raw)
    if not m:
        return False
    lines = m.group(1).splitlines()
    body = m.group(2)
    done, out = set(), []
    for line in lines:
        k = line.split(":", 1)[0].strip() if ":" in line else None
        if k in updates:
            out.append(f"{k}: {updates[k]}")
            done.add(k)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in done:
            out.append(f"{k}: {v}")
    Path(path).write_text("---\n" + "\n".join(out) + "\n---\n" + body, encoding="utf-8")
    return True


def cmd_rename(args):
    root = Path(args.root)
    old, new = args.old, args.new
    ents = A.load_entities(root)
    by_name = {e["name"]: e for e in ents}
    by_alias = {a: e for e in ents for a in e["aliases"]}
    src = by_name.get(old) or by_alias.get(old)
    if src is None:
        print(f"未找到资产：{old}")
        return 1
    if new in by_name:
        print(f"[拒绝] 「{new}」已存在，请先合并或换名")
        return 1

    old_name = src["name"]
    card = root / src["file"]
    aliases = [a for a in src["aliases"] if a != old_name]
    if old_name != new and old_name not in aliases:
        aliases.append(old_name)
    retired = sorted(set((src.get("retired") or []) + [old_name]))
    _update_front_matter(card, {
        "name": new,
        "aliases": "[" + ", ".join([new] + aliases) + "]",
        "retired": "[" + ", ".join(retired) + "]",
        "updated": A._today(),
    })
    card.rename(card.with_name(f"{new}.md"))

    touched = []
    pat = re.compile(r"\[\[\s*" + re.escape(old_name) + r"\s*\]\]")
    for p in sorted((root / W.CARD_DIR).rglob("*.md")):
        txt = p.read_text(encoding="utf-8")
        if pat.search(txt):
            p.write_text(pat.sub(f"[[{new}]]", txt), encoding="utf-8")
            touched.append(p.name)

    con = connect(root)
    add_revision(con, f"{src['type']}/{new}", "rename", "名称", old_name, new,
                 args.note or "改名，旧名降级为 retired 别名")
    old_eid = src["id"]
    con.execute("DELETE FROM entities WHERE id=?", (old_eid,))
    con.execute("DELETE FROM aliases WHERE entity_id=?", (old_eid,))
    con.execute("DELETE FROM relations WHERE src=?", (old_name,))
    con.execute("DELETE FROM links WHERE src=?", (old_name,))
    fresh = [x for x in A.load_entities(root) if x["name"] == new]
    if fresh:
        _upsert_entity(con, fresh[0], entity_hash(fresh[0]))
    con.commit()
    with (root / W.LOG_NAME).open("a", encoding="utf-8") as f:
        f.write(f"- {_now()}　[rename] {old_name} → {new}；改动引用 {len(touched)} 处\n")

    print(f"[改名] {old_name} → {new}")
    print("  旧名已降级为别名（kind=retired），正文里的旧写法仍可被检索命中")
    print(f"  卡片内 [[{old_name}]] → [[{new}]]：{len(touched)} 处"
          + (f"（{'、'.join(touched[:8])}）" if touched else ""))
    print("  → 请再跑 `sync` 重建索引")
    return 0


# ---------------------------------------------------------------- info

def cmd_info(args):
    root = Path(args.root)
    con = connect(root)
    n = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    na = con.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
    nr = con.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
    nl = con.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    nv = con.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]
    print(f"工作区：{args._ws_cfg['name']}　({root})")
    print(f"索引库：{db_path(root)}")
    print(f"  实体 {n}｜别名 {na}｜关系 {nr}｜引用 {nl}｜变更记录 {nv}")
    for r in _rows(con, "SELECT type AS t, COUNT(*) AS c FROM entities GROUP BY type ORDER BY c DESC"):
        print(f"    {r['t']}: {r['c']}")

    cards = sorted((root / W.CARD_DIR).rglob("*.md")) if (root / W.CARD_DIR).exists() else []
    if cards:
        newest = max(p.stat().st_mtime for p in cards)
        dbf = db_path(root)
        if not dbf.exists():
            print("\n  ⚠ 尚无索引库——请跑 `sync`")
        else:
            dbm = dbf.stat().st_mtime
            if newest > dbm:
                lag = int(newest - dbm)
                print(f"\n  ⚠ 有卡片比索引新（落后约 {lag} 秒）——请跑 `sync` 重建索引")
            else:
                print("\n  ✓ 索引与卡片同步")
    return 0


# ---------------------------------------------------------------- CLI 挂载

def register_cli(sub, add_common):
    """把索引与版本层命令挂到统一 CLI 上。"""
    s = sub.add_parser("sync", help="从卡片重建索引并记录变更")
    add_common(s)
    s.add_argument("--note", default="")
    s.set_defaults(func=cmd_sync)

    f = sub.add_parser("find", help="按条件筛选资产")
    add_common(f)
    f.add_argument("--type")
    f.add_argument("--world")
    f.add_argument("--status")
    f.add_argument("--tag")
    f.add_argument("--grep", help="正文/名称/别名 包含关键词")
    f.add_argument("--alias")
    f.set_defaults(func=cmd_find)

    q = sub.add_parser("query", help="跑 SQL（仅 SELECT）")
    add_common(q)
    q.add_argument("sql")
    q.set_defaults(func=cmd_query)

    h = sub.add_parser("history", help="某资产的变更史")
    add_common(h)
    h.add_argument("name")
    h.set_defaults(func=cmd_history)

    rc = sub.add_parser("recent", help="全库最近变更")
    add_common(rc)
    rc.add_argument("n", nargs="?", type=int, default=15)
    rc.set_defaults(func=cmd_recent)

    im = sub.add_parser("impact", help="改它的影响面（反向引用）")
    add_common(im)
    im.add_argument("name")
    im.set_defaults(func=cmd_impact)

    rn = sub.add_parser("rename", help="改名并全库传播")
    add_common(rn)
    rn.add_argument("old")
    rn.add_argument("new")
    rn.add_argument("--note", default="")
    rn.set_defaults(func=cmd_rename)

    d = sub.add_parser("dupe", help="别名冲突")
    add_common(d)
    d.set_defaults(func=cmd_dupe)

    i = sub.add_parser("info", help="索引概况 + 新鲜度检查")
    add_common(i)
    i.set_defaults(func=cmd_info)
