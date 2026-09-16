#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli.py —— 统一命令行入口。

    nah --root "<工作区>"  <命令>      # 显式指定工作区
    nah --ws   <已登记名>  <命令>      # 用登记过的名字
    cd <工作区> && nah <命令>          # 直接进目录
    set NAH_ROOT=<工作区> && nah <命令>  # 环境变量

命令分三组：
  · 工作区：init / ws
  · 内容层：add / ingest / list / show / brief / scan / check / index / log
  · 索引层：sync / find / query / history / recent / impact / rename / dupe / info
"""
import argparse
import sys
from pathlib import Path

from . import __version__
from . import core
from . import db
from . import orphan
from . import workspace as W

GLOBAL_FLAGS = ("--root", "-C", "--workspace-dir")


def _extract_globals(argv):
    """把 --root/-C 与 --ws 从任意位置摘出来（允许写在子命令之后）。"""
    root = ws = None
    out, i, n = [], 0, len(argv)
    while i < n:
        a = argv[i]
        if a in GLOBAL_FLAGS:
            if i + 1 >= n:
                raise W.WorkspaceError(f"{a} 后面缺少目录参数")
            root = argv[i + 1]; i += 2; continue
        if a.startswith("--root=") or a.startswith("--workspace-dir="):
            root = a.split("=", 1)[1]; i += 1; continue
        if a == "--ws":
            if i + 1 >= n:
                raise W.WorkspaceError("--ws 后面缺少工作区名")
            ws = argv[i + 1]; i += 2; continue
        if a.startswith("--ws="):
            ws = a.split("=", 1)[1]; i += 1; continue
        out.append(a); i += 1
    return root, ws, out


def _add_common(_parser):
    """占位钩子：工作区参数由 _extract_globals 统一摘取，无需挂在子命令上。"""
    return None


# ---------------------------------------------------------------- 工作区命令

def cmd_ws(args):
    cfg = W.load_project_config()
    sub = args.ws_cmd
    if sub == "list" or sub is None:
        if not cfg["workspaces"]:
            print("（尚未登记任何工作区）")
            print('  登记一个：nah ws add 我的小说 "/path/to/我的小说/设定资产"')
            return 0
        print(f"已登记工作区（默认：{cfg.get('default') or '—'}）：")
        for name, path in sorted(cfg["workspaces"].items()):
            p = Path(path)
            mark = "*" if name == cfg.get("default") else " "
            if not p.exists():
                state = "✗ 路径不存在"
            elif not W.is_workspace(p):
                state = "✗ 不是工作区"
            else:
                wcfg = W.load_workspace(p)
                state = f"✓ {len(list((p / W.CARD_DIR).rglob('*.md')))} 张卡片｜类型 {len(wcfg['types'])} 类"
            print(f"  {mark} {name:<10} {path}　{state}")
        return 0

    if sub == "add":
        p = Path(args.path).expanduser().resolve()
        if not p.exists():
            print(f"[错误] 路径不存在：{p}")
            return 1
        if not W.is_workspace(p):
            print(f"[错误] 该目录不是工作区（缺 {W.CARD_DIR}/ 或 {W.WORKSPACE_MARK}）。"
                  f'先跑：nah init "{p}" --as-name {args.name}')
            return 1
        W.register(args.name, p, set_default=args.default)
        print(f"[已登记] {args.name} -> {p}" + ("（并设为默认）" if args.default else ""))
        return 0

    if sub == "use":
        if args.name not in cfg["workspaces"]:
            print(f"[错误] 未登记的工作区：{args.name}")
            return 1
        cfg["default"] = args.name
        W.save_project_config(cfg)
        print(f"[默认工作区] {args.name}")
        return 0

    if sub == "rm":
        if args.name not in cfg["workspaces"]:
            print(f"[错误] 未登记的工作区：{args.name}")
            return 1
        cfg["workspaces"].pop(args.name)
        if cfg.get("default") == args.name:
            cfg["default"] = next(iter(cfg["workspaces"]), None)
        W.save_project_config(cfg)
        print(f"[已移除登记] {args.name}（仅解除登记，磁盘文件未动）")
        return 0

    if sub == "show":
        try:
            root = W.resolve_root(explicit=args._root_arg, ws=args._ws_arg)
        except W.WorkspaceError as ex:
            print(f"[错误] {ex}")
            return 2
        wc = W.load_workspace(root)
        print(f"当前工作区：{wc['name']}")
        print(f"  路径        ：{wc['path']}")
        print(f"  配置        ：{wc['path'] / W.WORKSPACE_MARK}"
              + ("（存在）" if (wc['path'] / W.WORKSPACE_MARK).exists() else "（缺省，用内置默认）"))
        print(f"  类型集合    ：{'、'.join(wc['types'])}")
        print(f"  正文章节目录：{wc['chapters_dir'] or '（未配置，check 将跳过「正文未出现」审计）'}")
        ips = wc.get("ip_evidence") or []
        if ips:
            for i, ip in enumerate(ips):
                head = "  IP 证据库   ：" if i == 0 else "                "
                print(f"{head}{ip}" + ("" if Path(ip).exists() else "  ✗ 不存在"))
        else:
            print("  IP 证据库   ：（未配置，orphan 将无法区分原作角色）")
        cards = list((wc['path'] / W.CARD_DIR).rglob("*.md")) if (wc['path'] / W.CARD_DIR).exists() else []
        print(f"  卡片数      ：{len(cards)}")
        return 0
    return 0


# ---------------------------------------------------------------- 组装

def build_parser():
    p = argparse.ArgumentParser(
        prog="nah",
        description="novel-asset-hub —— AI 小说设定资产管理器",
        epilog="示例：nah --ws 我的小说 scan ../processed/raw/ep_090.md")
    p.add_argument("-V", "--version", action="version", version=f"novel-asset-hub {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    ws = sub.add_parser("ws", help="工作区管理（list / add / use / rm / show）")
    wsp = ws.add_subparsers(dest="ws_cmd")
    wl = wsp.add_parser("list", help="列出已登记工作区")
    wl.set_defaults(func=cmd_ws, _needs_ws=False)
    wa = wsp.add_parser("add", help="登记一个工作区")
    wa.add_argument("name")
    wa.add_argument("path")
    wa.add_argument("--default", action="store_true", help="同时设为默认")
    wa.set_defaults(func=cmd_ws, _needs_ws=False)
    wu = wsp.add_parser("use", help="设置默认工作区")
    wu.add_argument("name")
    wu.set_defaults(func=cmd_ws, _needs_ws=False)
    wr = wsp.add_parser("rm", help="解除登记（不动磁盘文件）")
    wr.add_argument("name")
    wr.set_defaults(func=cmd_ws, _needs_ws=False)
    wsx = wsp.add_parser("show", help="查看当前解析到的工作区")
    wsx.set_defaults(func=cmd_ws, _needs_ws=False)
    ws.set_defaults(func=cmd_ws, _needs_ws=False, ws_cmd="list")

    core.register_cli(sub, _add_common)
    db.register_cli(sub, _add_common)
    orphan.register_cli(sub, _add_common)
    return p


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        root_arg, ws_arg, rest = _extract_globals(argv)
    except W.WorkspaceError as ex:
        print(f"[错误] {ex}")
        return 2
    if not rest:
        build_parser().print_help()
        return 0

    parser = build_parser()
    args = parser.parse_args(rest)
    args._root_arg = root_arg
    args._ws_arg = ws_arg

    if getattr(args, "_needs_ws", True):
        try:
            root = W.resolve_root(explicit=root_arg, ws=ws_arg)
        except W.WorkspaceError as ex:
            print(f"[错误] {ex}")
            return 2
        args.root = root
        args._ws_cfg = W.load_workspace(root)
    else:
        args.root = root_arg
        args._ws_cfg = None

    try:
        return args.func(args) or 0
    finally:
        db.close_all()
