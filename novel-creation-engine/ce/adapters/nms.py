# -*- coding: utf-8 -*-
"""nms.py —— novel-memory-system 的只读接线。

**不做**：正文 ETL、章节上下文拼装、一致性校验的实现——全部在 nms 里。
**只做**：通过子进程 import `wb_tools`，调它的 5 个函数。

nms 的接口是 async 的，所以这里用一个**内联的 async 包装脚本**通过
`python -c` 执行，把结果打成 JSON 回来。用 `python -c` 而不是写临时文件，
是为了不往用户磁盘写中间产物。

调用形态：
    python -c "<WRAPPER>"        # 环境变量传递函数名与参数
"""

import json
import os

from .base import ToolUnavailable, resolve_tool_dir, which_python, run

NAME = "nms"

# 引擎目录解析：环境变量 NMS_ROOT > 同级目录 > 用户配置 > 占位符
DEFAULT_ROOT = os.path.join("<repo>", "novel-memory-system")


def root():
    p, _ = resolve_tool_dir(
        "NMS_ROOT", "nms_root",
        ["novel-memory-system", "novel_memory_system"],
        DEFAULT_ROOT,
    )
    return p


def probe():
    r = root()
    wb = os.path.join(r, "wb_tools.py")
    if not os.path.exists(wb):
        return False, (f"未找到 {wb}"
                       f"（设 NMS_ROOT 指向 novel-memory-system，"
                       f"或把它放在本项目的同级目录）")
    if not os.path.exists(os.path.join(r, "src", "novel_memory_system")):
        return False, f"{r}/src/novel_memory_system 不存在，包结构不完整"
    miss = missing_deps()
    if miss:
        return False, (f"文件齐备但 Python 依赖缺失：{', '.join(miss)}"
                       f"（装到与当前解释器一致的环境：pip install {' '.join(miss)}）；"
                       f"另需 PostgreSQL + pgvector 在运行")
    return True, wb


# 内联包装：从环境变量读 func/args，跑 async，把结果 JSON 打到 stdout。
# 注意：wb_tools.py 自己会把 <root>/src 插进 sys.path，这里**不要重复插**，
#      否则只会掩盖真实错误。
_WRAPPER = r"""
import json, os, sys, asyncio
sys.path.insert(0, os.environ["NMS_ROOT"])
try:
    import wb_tools
except Exception as ex:
    print(json.dumps({"ok": False, "stage": "import",
                      "error": type(ex).__name__, "message": str(ex),
                      "hint": "nms 依赖未装齐（如 asyncpg / psycopg）或 PostgreSQL 未启动。"
                              "参考 novel-memory-system/README.md 的安装步骤。"},
                     ensure_ascii=False))
    sys.exit(4)
func_name = os.environ["NMS_FUNC"]
func = getattr(wb_tools, func_name, None)
if func is None:
    print(json.dumps({"ok": False, "stage": "lookup",
                      "error": "AttributeError",
                      "message": "wb_tools has no " + func_name,
                      "hint": "nms 版本与 L3 预期不符，检查 wb_tools 的 re-export 列表。"},
                     ensure_ascii=False))
    sys.exit(5)
args = json.loads(os.environ.get("NMS_ARGS", "[]"))
kwargs = json.loads(os.environ.get("NMS_KWARGS", "{}"))
async def _main():
    return await func(*args, **kwargs)
try:
    result = asyncio.run(_main())
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str))
except Exception as ex:
    print(json.dumps({"ok": False, "stage": "call",
                      "error": type(ex).__name__, "message": str(ex),
                      "hint": "多为数据库未初始化或未启动（PostgreSQL + pgvector）。"},
                     ensure_ascii=False))
    sys.exit(3)
"""


# --------------------------------------------------------------- 环境预检

def missing_deps():
    """检查 nms 的 Python 依赖是否齐（不启动数据库）。

    返回缺失的包名列表。空列表表示依赖齐备——但那不保证 PostgreSQL 在跑。
    """
    pkgs = ["asyncpg", "pgvector"]
    missing = []
    import importlib.util
    for p in pkgs:
        try:
            if importlib.util.find_spec(p) is None:
                missing.append(p)
        except (ImportError, ValueError):
            missing.append(p)
    return missing


def _call(func, args=None, kwargs=None, timeout=180):
    ok, detail = probe()
    if not ok:
        raise ToolUnavailable(f"[nms] {detail}")
    env = os.environ.copy()
    env["NMS_ROOT"] = root()
    env["NMS_FUNC"] = func
    env["NMS_ARGS"] = json.dumps(args or [], ensure_ascii=False)
    env["NMS_KWARGS"] = json.dumps(kwargs or {}, ensure_ascii=False)
    env.setdefault("PYTHONIOENCODING", "utf-8")

    cmd = [which_python(), "-c", _WRAPPER]
    # base.run 不接 env，这里直接内联一份等价的子进程调用
    import subprocess
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, cwd=root())
    except subprocess.TimeoutExpired as ex:
        raise ToolUnavailable(f"[nms] {func} 超时（{timeout}s）") from ex
    out = (p.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (p.stderr or b"").decode("utf-8", errors="replace")

    # wb_tools 可能在同一行有其它输出，只取最后一行合法 JSON
    payload = None
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                payload = json.loads(line)
                break
            except Exception:
                continue
    if payload is None:
        raise ToolUnavailable(
            f"[nms] {func} 输出无法解析为 JSON（code={p.returncode}）\n"
            f"stdout: {out[:400]}\nstderr: {err[:400]}"
        )
    if not payload.get("ok"):
        stage = payload.get("stage", "?")
        msg = (f"[nms] {func} 失败（stage={stage}）"
               f"{payload.get('error')}: {payload.get('message')}")
        if payload.get("hint"):
            msg += f"\n提示：{payload['hint']}"
        raise ToolUnavailable(msg)
    return payload["result"]


# ------------------------------------------------------------------ 读接口

def get_chapter_context(chapter_no):
    """取某一章的上下文（前文摘要、在场人物、已确立设定）。

    用于 `ce brief`：**已写内容的梳理是 nms 的职责，L3 不重做**。
    """
    return _call("get_chapter_context", [chapter_no])


def search_memory(query):
    """语义检索已写正文（"主角第一次受伤"这类问题）。"""
    return _call("search_memory", [query])


def query_character(name):
    """取某角色的档案（从哪里提取的、出现过几次、说过什么）。"""
    return _call("query_character", [name])


def validate_consistency(chapter_no):
    """校验某章与既有事实的一致性。

    这是 L3「设定闸」在**实然侧**的数据源——
    L3 不再自己拉 characters/world_settings 做三方对账（那是重复实现）。
    """
    return _call("validate_consistency", [chapter_no])
