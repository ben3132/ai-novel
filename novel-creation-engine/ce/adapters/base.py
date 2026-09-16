# -*- coding: utf-8 -*-
"""base.py —— adapter 的公共基座：子进程执行 + 可用性探测。

约定：
  · 所有外部调用一律走子进程，不 import 外部项目的模块。
    理由：xs/nms 各自有自己的依赖与副作用（数据库连接、savepoint），
    在 L3 进程里 import 它们会把生命周期耦合进来。子进程是干净边界。
  · 一律只读。写操作由各自的 CLI 负责，L3 不代理写。
"""

import json as _json
import os
import subprocess
import sys


class ToolUnavailable(RuntimeError):
    """外部项目不可用（未安装 / 路径不存在 / 命令失败）。"""


class CmdResult:
    """一次外部调用的结果。"""

    __slots__ = ("cmd", "code", "out", "err")

    def __init__(self, cmd, code, out, err):
        self.cmd = cmd
        self.code = code
        self.out = out
        self.err = err

    @property
    def ok(self):
        return self.code == 0

    def json(self):
        """把 stdout 当 JSON 解析。失败时抛 ToolUnavailable 并带上原文。"""
        try:
            return _json.loads(self.out)
        except Exception as ex:
            raise ToolUnavailable(
                f"命令输出不是合法 JSON：{' '.join(self.cmd)}\n"
                f"原因：{ex}\n输出前 500 字：\n{self.out[:500]}"
            ) from ex

    def __repr__(self):
        return f"<CmdResult code={self.code} out={self.out[:60]!r}>"


def run(cmd, cwd=None, timeout=120, encoding="utf-8"):
    """跑一个子进程，返回 CmdResult。不抛异常（除非超时）。"""
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as ex:
        raise ToolUnavailable(f"命令超时（{timeout}s）：{' '.join(map(str, cmd))}") from ex
    out = (p.stdout or b"").decode(encoding, errors="replace")
    err = (p.stderr or b"").decode(encoding, errors="replace")
    return CmdResult([str(c) for c in cmd], p.returncode, out, err)


def which_python():
    """返回当前解释器路径——用同一个解释器调外部脚本，避免多版本混乱。"""
    return sys.executable or "python"


# ------------------------------------------------------------------ 路径解析
#
# 设计：**不写死任何本机绝对路径**。
# 解析顺序（先命中先用）：
#   ① 环境变量（如 NAH_ENGINE / NMS_ROOT / XS_ROOT）
#   ② 同级目录探测——本仓库把三个项目放在同一父目录下，
#      所以 <本项目>/../<子目录名> 是最自然的默认位置
#   ③ 用户配置文件 ~/.ai-novel/config.json（可选，`ce doctor --init` 可写）
#   ④ 占位符兜底 —— 只是为了让错误信息可读，绝不指向真实路径
#
# 这样开源出去的副本不含任何个人信息，而本机又能零配置直接跑。

USER_CONFIG = os.path.join(os.path.expanduser("~"), ".ai-novel", "config.json")

# 项目根：<repo>/novel-creation-engine/ce/adapters/base.py → 上溯 3 层
_THIS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, "..", ".."))


def _load_user_config():
    try:
        import json
        with open(USER_CONFIG, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def resolve_tool_dir(env_var, config_key, sibling_names, placeholder):
    """解析外部项目的目录。

    参数：
        env_var       —— 环境变量名，如 "NAH_ENGINE"
        config_key    —— 用户配置文件里的键，如 "nah_engine"
        sibling_names —— 同级目录候选名列表（按优先级）
        placeholder   —— 全部失败时返回的占位路径（仅用于报错文案）

    返回 (path, source)：source ∈ {"env", "config", "sibling", "none"}
    """
    # ① 环境变量
    v = os.environ.get(env_var)
    if v and os.path.isdir(v):
        return v, "env"

    # ② 同级目录探测
    parent = os.path.dirname(PROJECT_ROOT)
    for nm in sibling_names:
        cand = os.path.join(parent, nm)
        if os.path.isdir(cand):
            return cand, "sibling"

    # ③ 用户配置
    cfg = _load_user_config()
    v = cfg.get(config_key)
    if v and os.path.isdir(v):
        return v, "config"

    # ④ 兜底（不指向真实路径）
    return placeholder, "none"


def load_user_config():
    """公开给 CLI 用（`ce config` 子命令）。"""
    return _load_user_config()


def source_of(env_var, config_key, sibling_names):
    """只返回来源标签，不返回路径（给 doctor/config 显示用）。"""
    _, src = resolve_tool_dir(env_var, config_key, sibling_names, "")
    return src


def save_user_config(cfg):
    """写用户配置文件。"""
    import json
    os.makedirs(os.path.dirname(USER_CONFIG), exist_ok=True)
    with open(USER_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return USER_CONFIG


def env_with_pythonpath(*paths):
    """构造一个带上 PYTHONPATH 的环境副本（给需要 import 外部包的项目用）。"""
    env = os.environ.copy()
    extra = os.pathsep.join(str(p) for p in paths if p)
    if extra:
        old = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = extra + (os.pathsep + old if old else "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env
