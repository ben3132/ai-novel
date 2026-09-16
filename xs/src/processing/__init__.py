"""可追溯的数据处理层；永远不修改 data/raw。"""

from .segmenter import segment_record
from .window_builder import build_context_windows

__all__ = ["segment_record", "build_context_windows"]
