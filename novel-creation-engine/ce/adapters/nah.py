# -*- coding: utf-8 -*-
"""nah.py —— novel-asset-hub 的只读接线。

**不做**：卡片解析、名称查重、六类审计的具体逻辑——全部在 nah 里。
**只做**：调它的 CLI，把 JSON 结果交回来。

调用形态：
    python <hub>/nah.py --ws <工作区> brief <名字…> --json
    python <hub>/nah.py --ws <工作区> check --json
    python <hub>/nah.py --ws <工作区> show <名字> --json
"""

import os

from .base import ToolUnavailable, resolve_tool_dir, run, which_python

NAME = "nah"

# 引擎目录解析：环境变量 NAH_ENGINE > 同级目录 > 用户配置 > 占位符
DEFAULT_ENGINE = os.path.join("<repo>", "novel-asset-hub")


def engine_root():
    p, _ = resolve_tool_dir(
        "NAH_ENGINE", "nah_engine",
        ["novel-asset-hub", "novel_asset_hub"],
        DEFAULT_ENGINE,
    )
    return p


def entry():
    return os.path.join(engine_root(), "nah.py")


def probe():
    """探测可用性，返回 (available: bool, detail: str)。"""
    e = entry()
    if not os.path.exists(e):
        return False, (f"未找到入口 {e}"
                       f"（设 NAH_ENGINE 指向 novel-asset-hub，"
                       f"或把它放在本项目的同级目录）")
    if not os.path.exists(os.path.join(engine_root(), "nah", "cli.py")):
        return False, f"{engine_root()} 下没有 nah/cli.py，引擎不完整"
    return True, e


def _call(args, ws=None, timeout=120):
    ok, detail = probe()
    if not ok:
        raise ToolUnavailable(f"[nah] {detail}")
    cmd = [which_python(), entry()]
    if ws:
        cmd += ["--ws", ws]
    cmd += list(args)
    res = run(cmd, cwd=engine_root(), timeout=timeout)
    if not res.ok:
        raise ToolUnavailable(
            f"[nah] 命令失败（code={res.code}）：{' '.join(res.cmd)}\n{res.err[:500]}"
        )
    return res


# ------------------------------------------------------------------ 读接口

def check(ws=None):
    """六类审计（dangling/dup_alias/asymmetric/unstable/never_used/unregistered）。

    这是 L3「设定闸」的数据源——**L3 不再自己实现任何一致性检查**。

    注意：本版 nah 的 `check` **只有人类可读输出，没有 --json**。
    所以这里返回原始文本，由调用方决定是否解析。
    （`orphan` 子命令有 --json，需要结构化数据时用它。）
    """
    res = _call(["check"], ws=ws)
    return res.out


def check_json(ws=None):
    """用 `orphan --json` 拿结构化审计结果。

    nah 的 `check` 是六类审计的人类可读汇总，其中「正文出现但未登记」一项
    等价于 `orphan`。需要机器可读时走这个接口。
    """
    return orphan(ws=ws, json_out=True)


def brief(names, ws=None):
    """按名字取卡片内容（拼装上下文用）。"""
    if isinstance(names, str):
        names = [names]
    return _call(["brief", *names], ws=ws).out


def show(name, ws=None, json_out=True):
    """看单张卡片。"""
    args = ["show", name] + (["--json"] if json_out else [])
    return _call(args, ws=ws).json()


def list_cards(ws=None):
    """列卡片。注意 nah 的 list 输出是文本还是 JSON 取决于版本，这里兜底。"""
    res = _call(["list"], ws=ws)
    return res.out


def orphan(ws=None, min_count=2, json_out=True):
    """反向扫描：正文出现但资产库未登记的专名。

    已在 nah check 里并入，但保留独立入口以便单独调（如调 min_count）。
    """
    args = ["orphan", "--min-count", str(min_count)] + (["--json"] if json_out else [])
    return _call(args, ws=ws).json()
