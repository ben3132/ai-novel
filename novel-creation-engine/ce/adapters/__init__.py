# -*- coding: utf-8 -*-
"""adapters —— 对三个外部项目的**只读**接线层。

铁律：本包**不含任何检索、归纳、提取、校验的实现**。
     这些能力分别属于 xs / nms / nah，L3 只负责按正确时序调用它们。
     任何在本包里出现的正则匹配外部知识的行为，都是设计事故。

| 模块 | 外部项目 | 调用方式 | 用途 |
|---|---|---|---|
| `nah.py` | novel-asset-hub | 子进程调 `nah.py` CLI | 取设定卡片 brief / 跑六类审计 check |
| `nms.py` | novel-memory-system | 子进程 `python -c` 调 `wb_tools` | 取已写章节上下文 / 校验一致性 |
| `xs.py`  | xs IP 证据库 | 子进程调 `run_ip_agent.py --request-json` | 取原作候选证据 |

全部工具**必须可缺席**：外部项目未安装时，adapter 返回 `available=False`
并给出安装提示，绝不让整个 L3 崩溃——这是"接线层"和"依赖"的区别。
"""

from . import nah, nms, xs  # noqa: F401
from .base import CmdResult, ToolUnavailable, source_of  # noqa: F401

ALL = (nah, nms, xs)


def probe_all():
    """一次性探测三个外部项目的可用性。"""
    return {mod.NAME: mod.probe() for mod in ALL}


_SOURCE_LABEL = {
    "env": "环境变量",
    "config": "用户配置",
    "sibling": "同级目录",
    "none": "未找到",
}


def describe_paths():
    """返回每个工具的解析路径与来源，供 `ce doctor` / `ce config` 显示。"""
    out = {}
    for mod, env, key, sib in (
        (nah, "NAH_ENGINE", "nah_engine", ["novel-asset-hub", "novel_asset_hub"]),
        (nms, "NMS_ROOT", "nms_root", ["novel-memory-system", "novel_memory_system"]),
    ):
        p = mod.engine_root() if mod is nah else mod.root()
        src = source_of(env, key, sib)
        out[mod.NAME] = {"path": p, "source": src, "env": env,
                         "label": _SOURCE_LABEL.get(src, src)}
    src = source_of("XS_ROOT", "xs_root", ["xs"])
    out["xs"] = {"path": xs.engine_root(), "source": src, "env": "XS_ROOT",
                 "label": _SOURCE_LABEL.get(src, src)}
    out["xs_data"] = {"path": xs.data_root(), "env": "XS_DATA", "source": "-", "label": "数据根"}
    return out
