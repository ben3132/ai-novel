#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace.py —— 工作区（小说设定数据）的发现、配置与脚手架。

【引擎与数据分离】
  · 引擎 = 本项目（`nah/` 里的代码），只管逻辑，不存任何小说数据；
  · 工作区 = 某部小说的资产数据目录，里面是 `cards/` 与派生索引；
  · 一部小说一个工作区，同一个引擎可以同时管多部小说。

【工作区识别】
  目录下存在 `cards/` 或 `workspace.json` 即视为工作区。

【工作区配置】`<工作区>/workspace.json`（可选，缺省用内置默认值）
    {
      "name": "我的小说",
      "types": ["人物", "势力", "能力", "道具", "地点", "设定", "剧情线"],
      "chapters_dir": "../processed/raw"
    }
  · `chapters_dir` 相对工作区目录解析，供 `check` 的「已登记但正文未出现」审计使用。

【项目级配置】`<引擎根>/nah.config.json`（建议加入 .gitignore，不入版本库）
    {
      "default": "我的小说",
      "workspaces": { "我的小说": "/path/to/我的小说/设定资产" }
    }

【根目录解析优先级】
  --root/-C 参数  >  NAH_ROOT 环境变量  >  --ws 指定名  >  项目配置的 default
  >  当前工作目录（若它本身是工作区）
"""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CARD_DIR = "cards"
WORKSPACE_MARK = "workspace.json"
CONFIG_NAME = "nah.config.json"
DB_NAME = "assets.db"
INDEX_NAME = "_registry.json"
HUMAN_INDEX_NAME = "00_索引.md"
LOG_NAME = "_log.md"

DEFAULT_TYPES = ["人物", "势力", "能力", "道具", "地点", "设定", "剧情线"]
DEFAULT_STATUSES = ["稳定", "重判中", "已变更", "待确认", "草稿"]


class WorkspaceError(Exception):
    """无法确定工作区，或工作区结构不合法。"""


# ---------------------------------------------------------------- 项目级配置

def project_config_path():
    return PROJECT_ROOT / CONFIG_NAME


def load_project_config():
    p = project_config_path()
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                cfg.setdefault("workspaces", {})
                cfg.setdefault("default", None)
                return cfg
        except Exception:
            pass
    return {"workspaces": {}, "default": None}


def save_project_config(cfg):
    p = project_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------- 工作区

def is_workspace(path):
    p = Path(path)
    return (p / CARD_DIR).is_dir() or (p / WORKSPACE_MARK).exists()


def load_workspace(root):
    """读取工作区配置，缺省项以默认值补齐。返回 dict。"""
    p = Path(root).resolve()
    meta = {}
    wf = p / WORKSPACE_MARK
    if wf.exists():
        try:
            meta = json.loads(wf.read_text(encoding="utf-8")) or {}
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}

    types = meta.get("types") or list(DEFAULT_TYPES)
    statuses = meta.get("statuses") or list(DEFAULT_STATUSES)

    chapters = meta.get("chapters_dir")
    if chapters:
        cp = Path(chapters)
        raw = cp if cp.is_absolute() else (p / cp)
        chapters_abs = Path(os.path.normpath(raw))
    else:
        chapters_abs = None

    # 外部 IP 证据库（只读）。用于 `orphan` 把「原作既有角色」与「本书原创」区分开：
    # 名字命中 IP 证据库 => 属 L1（IP 知识层），无需登记进本工作区的资产库。
    ip_evidence = []
    for item in (meta.get("ip_evidence") or []):
        ipath = Path(str(item))
        if not ipath.is_absolute():
            ipath = p / ipath
        ip_evidence.append(Path(os.path.normpath(ipath)))

    return {
        "path": p,
        "name": meta.get("name") or p.name,
        "types": list(types),
        "statuses": list(statuses),
        "chapters_dir": Path(chapters_abs) if chapters_abs else None,
        "ip_evidence": ip_evidence,
        "config": meta,
    }


def register(name, path, set_default=False):
    """把一个工作区登记进项目级配置。"""
    cfg = load_project_config()
    cfg["workspaces"][name] = str(Path(path).resolve())
    if set_default or not cfg.get("default"):
        cfg["default"] = name
    save_project_config(cfg)
    return cfg


def resolve_root(explicit=None, ws=None, cwd=None):
    """按优先级确定工作区根目录。"""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            raise WorkspaceError(f"目录不存在：{p}")
        if not is_workspace(p):
            raise WorkspaceError(
                f"该目录不像工作区（缺 {CARD_DIR}/ 或 {WORKSPACE_MARK}）：{p}\n"
                f"  用 `nah init \"{p}\"` 把它初始化成工作区。")
        return p

    env = os.environ.get("NAH_ROOT")
    if env:
        return resolve_root(explicit=env, cwd=cwd)

    cfg = load_project_config()

    if ws:
        hit = cfg["workspaces"].get(ws)
        if not hit:
            known = "、".join(cfg["workspaces"]) or "（无）"
            raise WorkspaceError(f"未登记的工作区：{ws}\n  已登记：{known}")
        return resolve_root(explicit=hit, cwd=cwd)

    default = cfg.get("default")
    if default and cfg["workspaces"].get(default):
        try:
            return resolve_root(explicit=cfg["workspaces"][default], cwd=cwd)
        except WorkspaceError:
            pass

    cur = Path(cwd or os.getcwd())
    if is_workspace(cur):
        return cur.resolve()

    known = "、".join(cfg["workspaces"]) or "（无）"
    raise WorkspaceError(
        "无法确定工作区。请任选一种方式指定：\n"
        "  · 加参数：      nah --root \"<工作区目录>\" <命令>\n"
        "  · 用已登记名：  nah --ws <名字> <命令>\n"
        "  · 设环境变量：  set NAH_ROOT=<工作区目录>\n"
        "  · 直接 cd 到工作区目录再执行\n"
        f"当前已登记的工作区：{known}")


# ---------------------------------------------------------------- 脚手架

WORKSPACE_README = """# {name} · 设定资产工作区

本目录是小说《{name}》的**设定资产数据**，由 `novel-asset-hub` 引擎管理。

- 日常只改 `cards/<类型>/<名字>.md` —— 卡片是**唯一真相源**；
- `{db}` / `{index}` / `{human}` / `{log}` 全部是派生文件，勿手改（可由命令重建）；
- 工作区配置见 `{mark}`：项目名、类型集合、正文章节目录、以及可选的 `ip_evidence`
  （外部 IP 证据库路径，供 `orphan` 区分「原作既有角色」与「本书原创」）。

引擎与数据的边界：**引擎不在这里**，代码在 novel-asset-hub 项目内。
"""


def scaffold(path, name=None, types=None, chapters_dir=None, force=False):
    """把 path 初始化为一个工作区骨架。返回工作区路径。"""
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    marker = p / WORKSPACE_MARK
    if marker.exists() and not force:
        raise WorkspaceError(f"该目录已是工作区（存在 {WORKSPACE_MARK}）：{p}\n"
                             f"  如需重建骨架，加 --force。")

    types = list(types or DEFAULT_TYPES)
    meta = {"name": name or p.name, "types": types}
    if chapters_dir:
        meta["chapters_dir"] = chapters_dir
    marker.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    (p / CARD_DIR).mkdir(exist_ok=True)
    for t in types:
        (p / CARD_DIR / t).mkdir(exist_ok=True)

    log = p / LOG_NAME
    if not log.exists():
        log.write_text(f"# {meta['name']} · 设定资产变更日志\n\n", encoding="utf-8")

    readme = p / "README.md"
    if not readme.exists():
        readme.write_text(WORKSPACE_README.format(
            name=meta["name"], db=DB_NAME, index=INDEX_NAME,
            human=HUMAN_INDEX_NAME, log=LOG_NAME, mark=WORKSPACE_MARK), encoding="utf-8")
    return p
