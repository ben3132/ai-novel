# -*- coding: utf-8 -*-
"""xs.py —— xs IP 证据库的只读接线。

**不做**：采集、切片、建窗、建库、实体发现、事实提取——全部在 xs 里。
**只做**：用 `run_ip_agent.py --request-json` 调它的 5 个 QUERY 操作。

xs 的 QUERY_OPERATIONS（只读，不动研究状态）：
    list_works        列已登记作品
    get_corpus_status 语料状态（各作品文档/窗口数）
    get_entity        某个实体的原文提及
    search_evidence   自然语言问题检索（返回带作品/章节/窗口/来源/可信等级的原文）
    search_hybrid     混合召回（词法+向量，RRF 融合，带 lexical_rank/vector_rank/fusion_score）

**不变式**（来自 xs 自己的声明，L3 必须代为传达给使用者）：
  · 所有返回的 `answer_status` 恒为 `evidence_only` —— 是**候选证据**，不是已确认设定。
  · `trust_level` 分级：1=official_primary / 11=third_party_transcription_requires_l1_cross_check
    / 2=cited_fan_reference / 3=secondary_community / 4=collect_as_lead_only_excluded_from_reasoning。
  · **trust_level == 11 必须向使用者发警告**（需回 L1 交叉核对）。
"""

import json
import os

from .base import ToolUnavailable, resolve_tool_dir, run, which_python

NAME = "xs"

# 引擎与数据目录解析：环境变量 XS_ROOT / XS_DATA > 同级目录 > 用户配置 > 占位符
DEFAULT_ROOT = os.path.join("<repo>", "xs")
DEFAULT_DATA_ROOT = os.path.join("<repo>", "xs_data")

# IP 代号（与 xs 数据目录同名）
IP_DOMAINS = ("ben10", "jackie_chan", "pacific_rim", "douluo", "lol")


def engine_root():
    p, _ = resolve_tool_dir("XS_ROOT", "xs_root", ["xs"], DEFAULT_ROOT)
    return p


def data_root():
    """xs 的数据根。

    注意：它**不在**代码仓库里（数据与代码分离），
    所以只认环境变量与用户配置，不做同级探测（避免误命中）。
    """
    v = os.environ.get("XS_DATA")
    if v and os.path.isdir(v):
        return v
    from .base import load_user_config
    v = load_user_config().get("xs_data")
    if v and os.path.isdir(v):
        return v
    # 退一步：同级有 xs_data 就用它
    cand = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "xs_data")
    if os.path.isdir(cand):
        return cand
    return DEFAULT_DATA_ROOT


def entry():
    return os.path.join(engine_root(), "run_ip_agent.py")


def evidence_path(ip):
    """证据库文件路径（仅用于探测存在性，实际调用传的是 data_root）。

    xs 的数据布局：<data_root>/data/ip/<ip_domain>/processed/index/evidence.sqlite3
    """
    return os.path.join(data_root(), "data", "ip", ip,
                        "processed", "index", "evidence.sqlite3")


def probe(ip=None):
    e = entry()
    if not os.path.exists(e):
        return False, (f"未找到入口 {e}"
                       f"（设 XS_ROOT 指向 xs 引擎，或把它放在本项目的同级目录）")
    if ip:
        db = evidence_path(ip)
        if not os.path.exists(db):
            return False, (f"未找到 {ip} 的证据库 {db}"
                           f"（设 XS_DATA 指向数据根，或把它放在同级目录 xs_data/）")
        return True, db
    return True, e


def _call(request, ip=None, timeout=300):
    """发一个 operation 请求给 xs，返回解析后的 dict。

    ip 提供时自动注入 `ip_domain` 并带上 `--database <证据库文件>`。
    ⚠️ 两个坑（已实测踩过两次）：
      1. `ip_domain` 必须显式写进 request —— query 层默认硬编码 "douluo"，
         不传就永远查到斗罗的数据（且 results 为空）。
      2. `--database` 要传 **evidence.sqlite3 的完整文件路径**。
         看 `src/query/agent_api.py::_database()`：`Path(value)` 直接当库文件用，
         只有传 None 时才回落到 IpDataPaths(...).database 推导。
         传目录会报 `Evidence database not found: <目录>`。
    """
    ok, detail = probe(ip)
    if not ok:
        raise ToolUnavailable(f"[xs] {detail}")

    req = dict(request)
    if ip:
        req.setdefault("ip_domain", ip)

    cmd = [which_python(), entry(), "--request-json",
           json.dumps(req, ensure_ascii=False), "--pretty"]
    if ip:
        cmd += ["--database", evidence_path(ip)]

    res = run(cmd, cwd=engine_root(), timeout=timeout)
    if not res.ok:
        err = res.err
        if "VectorDependencyError" in err or "faiss" in err:
            raise ToolUnavailable(
                "[xs] search_hybrid 需要向量依赖（faiss-cpu + sentence-transformers），"
                "当前未安装。改用 search_evidence（纯词法，无需依赖）。\n"
                f"原始错误：{err[:300]}"
            )
        raise ToolUnavailable(
            f"[xs] {request.get('operation')} 失败（code={res.code}）\n{err[:500]}"
        )
    try:
        return json.loads(res.out)
    except Exception as ex:
        raise ToolUnavailable(
            f"[xs] 输出不是 JSON：{ex}\n{res.out[:500]}"
        ) from ex


# ------------------------------------------------------------------ 只读接口

def guidance():
    """xs 的能力自述（含 not_implemented 列表）——用于在报告里声明能力边界。"""
    return _call({"operation": "get_agent_guidance"})


def list_works(ip):
    return _call({"operation": "list_works"}, ip=ip)


def corpus_status(ip):
    return _call({"operation": "get_corpus_status"}, ip=ip)


# 兼容别名（xs 的 operation 名是 get_corpus_status）
get_corpus_status = corpus_status


def get_entity(ip, name, works=None, top_k=10):
    """实体原文提及。

    注意：xs **不自动归纳实体档案**——返回的是原文提及集合。
    归纳成"这个角色是谁"仍然需要人（或 Agent）来读。
    """
    req = {"operation": "get_entity", "name": name, "top_k": top_k}
    if works:
        req["works"] = list(works)
    return _call(req, ip=ip)


def search_evidence(ip, question, works=None, top_k=10, trust_levels=(1, 11)):
    """自然语言问题检索（纯词法，无外部依赖）。

    默认 trust_levels=(1,11) 与 xs 自身默认一致——
    1=官方一手，11=第三方转录（带回 L1 交叉核对）。
    """
    req = {
        "operation": "search_evidence",
        "question": question,
        "top_k": top_k,
        "trust_levels": list(trust_levels),
    }
    if works:
        req["works"] = list(works)
    return _call(req, ip=ip)


def search_hybrid(ip, question, works=None, top_k=10, trust_levels=(1, 11)):
    """混合召回（词法+向量）。需要 faiss-cpu + sentence-transformers。"""
    req = {
        "operation": "search_hybrid",
        "question": question,
        "top_k": top_k,
        "trust_levels": list(trust_levels),
    }
    if works:
        req["works"] = list(works)
    return _call(req, ip=ip)


def vector_index_dir(ip):
    """向量索引目录（xs 用 IpDataPaths(...).vector 推导）。"""
    return os.path.join(data_root(), "data", "ip", ip, "processed", "vector")


def hybrid_available(ip):
    """混合召回是否真的可用。

    ⚠️ 重要：**不能靠异常判断**。`VectorDependencyError` 只在
    `build_ip_vector_index.py`（建索引）时抛；查询路径上
    `HybridIpQueryEngine.__init__` 找不到索引会**静默降级为纯词法**，
    返回 0 结果而不报错——这会把「没索引」伪装成「查不到」。

    所以这里主动检查索引目录里有没有实际文件。
    """
    d = vector_index_dir(ip)
    if not os.path.isdir(d):
        return False
    try:
        names = os.listdir(d)
    except OSError:
        return False
    # 索引文件名通常含 ip_domain，形如 jackie_chan_windows.faiss / .json
    return any(os.path.getsize(os.path.join(d, n)) > 0 for n in names)


def search_best(ip, question, **kw):
    """优先混合召回，无向量索引时自动降级到纯词法。

    返回 (payload, mode)，mode ∈ {"hybrid", "evidence"}。
    `ce brief` 用这个接口，保证在没建向量索引的机器上也能工作。
    """
    if hybrid_available(ip):
        try:
            return search_hybrid(ip, question, **kw), "hybrid"
        except ToolUnavailable:
            pass  # 索引损坏等情况，降级
    return search_evidence(ip, question, **kw), "evidence"


def search_terms(ip, terms, top_k=5, trust_levels=(1, 11)):
    """**多词分别检索再合并**——这是词法模式的正确用法。

    ⚠️ 这条是实测出来的硬约束：`search_evidence` 的词法匹配是
    **整串 LIKE（AND 语义）、不分词**。实测：
        '符咒'        -> 命中 1 条
        '十二符咒'     -> 0 条   ← 不是「符咒」没命中，是整串没匹配
        '符咒 力量'    -> 0 条   ← 空格不是分词符
        '老爹 符咒'    -> 0 条
    所以**绝不能拼多词短语**，必须把每个词单独查，再按 window_id 去重合并。

    返回：
        {
          "mode": "hybrid" | "evidence",
          "terms": {词: 结果数},
          "merged": [按 trust_level 升序、score 降序的条目],
          "empty_terms": [无命中的词],   # 提示：可能是这个词不在语料里
        }
    """
    if isinstance(terms, str):
        terms = [terms]
    terms = [t.strip() for t in terms if t and t.strip()]

    mode = "hybrid" if hybrid_available(ip) else "evidence"
    merged, seen, counts, empty = [], set(), {}, []

    for term in terms:
        try:
            if mode == "hybrid":
                r = search_hybrid(ip, term, top_k=top_k, trust_levels=trust_levels)
            else:
                r = search_evidence(ip, term, top_k=top_k, trust_levels=trust_levels)
        except ToolUnavailable:
            r = search_evidence(ip, term, top_k=top_k, trust_levels=trust_levels)
            mode = "evidence"
        hits = r.get("results") or []
        counts[term] = len(hits)
        if not hits:
            empty.append(term)
        for h in hits:
            wid = h.get("window_id")
            if wid and wid in seen:
                continue
            if wid:
                seen.add(wid)
            h = dict(h)
            h["_query_term"] = term
            merged.append(h)

    # trust_level 小的优先（1 官方 > 11 转录 > 2 引用 > 3 社区），同级按 score 降序
    merged.sort(key=lambda h: (
        h.get("trust_level") if isinstance(h.get("trust_level"), int) else 99,
        -(h.get("score") or 0),
    ))

    return {
        "mode": mode,
        "terms": counts,
        "merged": merged,
        "empty_terms": empty,
    }


# ------------------------------------------------------------------ 结果整形

# 需要向使用者发警告的可信等级
WARN_TRUST = {11: "第三方转录，需回 L1 官方来源交叉核对"}


def split_by_trust(payload):
    """把一个检索结果按 trust_level 分组，并抽出需要警告的条目。

    返回 (clean, warned)：
        clean  —— trust_level 未被标记警告的条目
        warned —— [(条目, 警告文案)]
    L3 的报告必须把 warned 单独列出来，不能混在证据里。
    """
    items = []
    if isinstance(payload, dict):
        for key in ("results", "hits", "evidence", "items", "windows"):
            v = payload.get(key)
            if isinstance(v, list):
                items = v
                break
    elif isinstance(payload, list):
        items = payload

    clean, warned = [], []
    for it in items:
        lvl = None
        if isinstance(it, dict):
            lvl = it.get("trust_level")
            if lvl is None and isinstance(it.get("source"), dict):
                lvl = it["source"].get("trust_level")
        if isinstance(lvl, int) and lvl in WARN_TRUST:
            warned.append((it, WARN_TRUST[lvl]))
        else:
            clean.append(it)
    return clean, warned
