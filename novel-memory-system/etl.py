"""novel-memory-system ETL 根入口（薄封装）。

用法：
    python etl.py                     # 首次全量导入（自动跳过已 done）
    python etl.py --resume            # 断点续传（跳过已 done 章节）
    python etl.py --reprocess-chapter 12   # 强制重跑第 12 章
    python etl.py --mock              # 离线降级：不调用 LLM/embedding API
    python etl.py --dir path/to/chapters --log-level DEBUG
"""
import sys
from pathlib import Path

# 允许以 "python etl.py" 直跑（无需 pip install -e .）
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from novel_memory_system.etl_runner import main  # noqa: E402

if __name__ == "__main__":
    main()
