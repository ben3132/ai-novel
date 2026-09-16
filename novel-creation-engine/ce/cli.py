# -*- coding: utf-8 -*-
"""cli.py —— 统一命令行入口。

    ce review <章.md|目录>          # 判据裁决，出报告（第一步，只读）
    ce brief  <名字…>               # 拼装上下文（第二步）
    ce commit <章.md>               # 落正文并触发审计（第二步）
    ce doctor                       # 探测三个外部项目的可用性

全局参数可写在任意位置：
    --root <工作区>   指定 nah 工作区（默认用 nah 注册表里的默认工作区）
    --out  <目录>     报告输出目录（默认 ./reports）
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import review as R
from .adapters import describe_paths, probe_all

GLOBAL_FLAGS = ("--root", "-C", "--out")


def _extract_globals(argv):
    root = out = None
    rest, i, n = [], 0, len(argv)
    while i < n:
        a = argv[i]
        if a in GLOBAL_FLAGS:
            if i + 1 >= n:
                print(f"[错误] {a} 后面缺少参数")
                raise SystemExit(2)
            if a in ("--root", "-C"):
                root = argv[i + 1]
            else:
                out = argv[i + 1]
            i += 2
            continue
        if a.startswith("--root="):
            root = a.split("=", 1)[1]; i += 1; continue
        if a.startswith("--out="):
            out = a.split("=", 1)[1]; i += 1; continue
        rest.append(a); i += 1
    return root, out, rest


def _add_common(_p):
    return None


def _collect(files):
    """把文件/目录参数展开成 .md 文件列表。"""
    out = []
    for f in files:
        p = Path(f)
        if p.is_dir():
            out.extend(sorted(p.glob("*.md")))
        elif p.exists():
            out.append(p)
        else:
            print(f"[跳过] 不存在：{f}")
    return out


# ------------------------------------------------------------------ review

def cmd_review(args):
    files = _collect(args.paths)
    if not files:
        print("[错误] 没有可审的 .md 文件")
        return 1

    outdir = Path(args._out or "reports")
    outdir.mkdir(parents=True, exist_ok=True)

    rule_set = None
    if args.rules:
        rule_set = [s.strip() for s in args.rules.split(",") if s.strip()]

    chapters, failures = [], 0
    for f in files:
        try:
            ch = R.review_file(
                str(f),
                rule_set=rule_set,
                with_setting_gate=not args.no_setting,
                ws=args._root,
            )
        except Exception as ex:
            print(f"[失败] {f.name}: {type(ex).__name__}: {ex}")
            failures += 1
            continue

        chapters.append(ch)

        if args.json:
            payload = {
                "path": ch["path"],
                "chapter_no": ch["chapter_no"],
                "chars": len(ch["text"]),
                "hits": [h.as_dict() for h in ch["hits"]],
                "warnings": ch["warnings"],
                "setting_error": ch["setting_error"],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            rp = outdir / f"{f.stem}.review.md"
            rp.write_text(R.render_report(ch), encoding="utf-8")
            c = {}
            for h in ch["hits"]:
                c[h.severity] = c.get(h.severity, 0) + 1
            print(f"[{f.name}] 红线 {c.get('红线', 0)} / 铁律 {c.get('铁律', 0)} "
                  f"/ 闸门 {c.get('闸门', 0)} / 提示 {c.get('提示', 0)}  -> {rp}")

    if not args.json and len(chapters) > 1:
        sp = outdir / "_SUMMARY.md"
        sp.write_text(R.render_summary(chapters), encoding="utf-8")
        print(f"[汇总] {len(chapters)} 章 -> {sp}")

    if failures:
        print(f"[注意] {failures} 章处理失败")
    return 0


# ------------------------------------------------------------------ doctor

def cmd_doctor(args):
    print(f"novel-creation-engine {__version__}")
    print()
    print("外部项目解析结果：")
    try:
        paths = describe_paths()
        for key in ("nah", "nms", "xs"):
            info = paths.get(key)
            if not info:
                continue
            ok, detail = probe_all().get(key, (False, ""))
            mark = "✓" if ok else "✗"
            print(f"  {mark} {key:<4} [{info['label']}] {info['path']}")
            if not ok:
                print(f"       {detail}")
        xd = paths.get("xs_data")
        if xd:
            import os as _os
            mark = "✓" if _os.path.isdir(xd["path"]) else "✗"
            print(f"  {mark} xs数据 {xd['path']}")
    except Exception as ex:
        print(f"  （路径解析失败：{ex}）")
    print()
    print("让程序找到外部项目，三种方式（任选其一）：")
    print("  ① 把三个项目放在本项目的同级目录（monorepo 默认布局，零配置）")
    print("  ② 设环境变量：NAH_ENGINE / NMS_ROOT / XS_ROOT / XS_DATA")
    print("  ③ 写用户配置：ce config --set nah_engine=<路径> …")
    print()
    print("三者全部缺席时 `ce review --no-setting` 仍可跑"
          "（禁则闸 + 铁律闸是纯本地的）。")
    return 0


def cmd_config(args):
    """查看/写用户配置文件（~/.ai-novel/config.json）。

    这个文件在**用户主目录**，不在仓库里——本机路径不会进版本库。
    """
    from .adapters.base import USER_CONFIG, load_user_config, save_user_config

    if args.set:
        cfg = load_user_config()
        n = 0
        for item in args.set:
            if "=" not in item:
                print(f"[跳过] 格式应为 key=value：{item}")
                continue
            k, v = item.split("=", 1)
            k, v = k.strip(), os.path.expanduser(v.strip())
            if v and not os.path.isdir(v):
                print(f"[警告] 目录不存在，仍然写入：{v}")
            cfg[k] = v
            n += 1
        p = save_user_config(cfg)
        print(f"[已写入] {n} 项 -> {p}")
        print("（该文件位于用户主目录，不在仓库内，不会进版本库）")
        return 0

    if args.unset:
        cfg = load_user_config()
        for k in args.unset:
            cfg.pop(k, None)
        p = save_user_config(cfg)
        print(f"[已删除 {', '.join(args.unset)}] -> {p}")
        return 0

    # 查看
    cfg = load_user_config()
    print(f"配置文件：{USER_CONFIG}")
    print("（不存在时为「无」，程序会回落到同级目录探测）")
    print()
    if not cfg:
        print("（当前为空）")
    else:
        for k, v in cfg.items():
            exists = "✓" if os.path.isdir(str(v)) else "✗"
            print(f"  {k} = {v}   {exists}")
    print()
    print("可设的键：nah_engine / nms_root / xs_root / xs_data")
    return 0


# ------------------------------------------------------------------ 组装

def build_parser():
    p = argparse.ArgumentParser(
        prog="ce",
        description="novel-creation-engine —— L3 创作层：不建库、不存事实、不做检索",
        epilog="示例：ce review \"D:/path/to/我的小说/processed/raw\" --no-setting",
    )
    p.add_argument("-V", "--version", action="version",
                   version=f"novel-creation-engine {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    rv = sub.add_parser("review", help="判据裁决，出「依据→命中→建议」报告")
    rv.add_argument("paths", nargs="+", help="章 .md 文件或目录（目录则批量）")
    rv.add_argument("--rules", help="只跑指定判据集，如 §23 或 §23,§25")
    rv.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown 报告")
    rv.add_argument("--no-setting", action="store_true",
                    help="跳过设定闸（不调 nah/nms，纯本地判据）")
    rv.set_defaults(func=cmd_review)

    dc = sub.add_parser("doctor", help="探测三个外部项目的解析路径与可用性")
    dc.set_defaults(func=cmd_doctor)

    cf = sub.add_parser("config", help="查看/写用户级路径配置（~/.ai-novel/config.json）")
    cf.add_argument("--set", nargs="*", metavar="KEY=VALUE",
                    help="写入配置，如 --set nah_engine=D:/code/novel-asset-hub")
    cf.add_argument("--unset", nargs="*", metavar="KEY", help="删除配置项")
    cf.set_defaults(func=cmd_config)

    return p


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = list(sys.argv[1:] if argv is None else argv)
    root_arg, out_arg, rest = _extract_globals(argv)
    if not rest:
        build_parser().print_help()
        return 0

    args = build_parser().parse_args(rest)
    args._root = root_arg
    args._out = out_arg

    # 环境变量兜底：CE_WS 指定默认工作区；都不给则让 nah 用它自己的默认值
    if not args._root:
        args._root = os.environ.get("CE_WS") or None

    return args.func(args) or 0
