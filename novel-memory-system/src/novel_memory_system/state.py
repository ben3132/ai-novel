"""ETL 断点状态与错误日志：etl_state.json 原子写 + 进程文件锁。

etl_state.json 结构：
{
  "schema_version": 1,
  "chapters": {
    "12": {"status": "done", "last_updated": "...", "failed_attempts": 0},
    "13": {"status": "failed", "last_updated": "...", "failed_attempts": 2}
  },
  "meta": {"last_run": "...", "processed": 12}
}
status ∈ pending | in_progress | done | failed。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ETLState:
    """etl_state.json 的读写封装；所有写操作均原子替换，防中断损坏。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings().STATE_FILE
        self.data: dict[str, Any] = {
            "schema_version": 1,
            "chapters": {},
            "meta": {},
        }

    # ---------- 读写 ----------
    def load(self) -> "ETLState":
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = {
                "schema_version": raw.get("schema_version", 1),
                "chapters": raw.get("chapters", {}),
                "meta": raw.get("meta", {}),
            }
        return self

    def save(self) -> None:
        """原子写：先写同目录临时文件，再 os.replace 覆盖。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["meta"]["last_run"] = _now_iso()
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)  # 原子替换
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------- 章节状态查询/更新 ----------
    def get_chapter_status(self, number: int) -> dict[str, Any]:
        return self.data["chapters"].get(str(number), {})

    def is_done(self, number: int) -> bool:
        return self.get_chapter_status(number).get("status") == "done"

    def failed_attempts(self, number: int) -> int:
        return int(self.get_chapter_status(number).get("failed_attempts", 0))

    def mark_in_progress(self, number: int) -> None:
        self.data["chapters"][str(number)] = {
            **self.get_chapter_status(number),
            "status": "in_progress",
            "last_updated": _now_iso(),
        }

    def mark_done(self, number: int) -> None:
        self.data["chapters"][str(number)] = {
            "status": "done",
            "last_updated": _now_iso(),
            "failed_attempts": 0,
        }

    def mark_failed(self, number: int, error: str) -> None:
        cur = self.get_chapter_status(number)
        self.data["chapters"][str(number)] = {
            "status": "failed",
            "last_updated": _now_iso(),
            "failed_attempts": int(cur.get("failed_attempts", 0)) + 1,
            "error": error[:200],
        }

    def reset_chapter(self, number: int) -> None:
        """清空某章状态（--reprocess-chapter 用）。"""
        self.data["chapters"].pop(str(number), None)

    def processed_count(self) -> int:
        return sum(
            1 for s in self.data["chapters"].values() if s.get("status") == "done"
        )


class FileLock:
    """跨平台进程文件锁（防同一 state 目录下并跑两个 ETL）。"""

    def __init__(self, path: Path | None = None, timeout: float = 30.0) -> None:
        self.path = path or get_settings().LOCK_FILE
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        # O_CREAT|O_EXCL 的"锁文件"方案：创建成功即持锁
        while True:
            try:
                self._fd = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                os.write(self._fd, f"pid={os.getpid()}\n".encode())
                return self
            except FileExistsError:
                if time.monotonic() > deadline:
                    stale = self._is_stale()
                    raise TimeoutError(
                        f"无法获取 ETL 文件锁 {self.path}"
                        + (f"（检测到残留锁文件，pid={stale}）" if stale else "")
                    )
                time.sleep(0.3)

    def __exit__(self, *_: Any) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        # 竞态安全：仅删除属于当前 pid 的锁文件
        try:
            if self.path.exists():
                content = self.path.read_text(encoding="utf-8", errors="ignore")
                if f"pid={os.getpid()}" in content:
                    self.path.unlink()
        except OSError:
            pass

    def _is_stale(self) -> str | None:
        """粗略判定锁文件是否残留（进程已退出但文件在）。"""
        try:
            content = self.path.read_text(encoding="utf-8", errors="ignore")
            pid = int(content.replace("pid=", "").strip())
            # Windows 上不查 /proc；仅返回 pid 供人工判断
            return str(pid)
        except Exception:
            return None


class ErrorLogger:
    """etl_errors.log 追加写入（UTF-8，线程安全由单进程保证）。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings().ERROR_LOG

    def log(
        self,
        chapter: int | None,
        error_fields: str,
        raw_output: str,
        message: str = "",
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw_truncated = (raw_output or "")[:500].replace("\n", "\\n")
        line = (
            f"{_now_iso()} | chapter={chapter if chapter is not None else '-'} "
            f"| fields={error_fields or '-'} | {message} | raw={raw_truncated}"
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
