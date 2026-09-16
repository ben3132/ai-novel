"""官方出版物扫描图片 OCR 采集器（L1，保留 PaddleOCR 原始识别结果与置信度）。"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from .base_collector import BaseCollector, RawRecord, TRUST_L1
from src.storage.ip_paths import IpDataPaths


def _json_safe(value: Any) -> Any:
    """仅将 OCR 返回对象转换为可无损落入 JSON 字符串的基础类型，不清洗识别文本。"""
    json_value = getattr(value, "json", None)
    if json_value is not None:
        return _json_safe(json_value() if callable(json_value) else json_value)
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class OcrL1Collector(BaseCollector):
    trust_level = TRUST_L1
    source_type = "ocr_scan_original"

    def collect(self) -> RawRecord:
        paths = IpDataPaths(self.project_root, self.task["ip_domain"])
        path = paths.source_material(self.task["path"], "official_scans").resolve(strict=True)
        allowed_root = (paths.raw / "source_material" / "official_scans").resolve()
        if allowed_root not in path.parents:
            raise ValueError(f"OCR L1 图片必须位于该 IP 的 raw/source_material/official_scans 下: {path}")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            raise ValueError(f"不支持的扫描图片格式: {path.suffix}")

        from paddleocr import PaddleOCR  # 延迟导入，使非 OCR 任务无需加载大模型依赖。

        options = dict(self.task.get("ocr", {}))
        lang = options.pop("lang", "ch")
        use_angle_cls = bool(options.pop("use_angle_cls", True))
        try:
            # PaddleOCR 3.x 接口。
            ocr = PaddleOCR(
                lang=lang,
                use_doc_orientation_classify=use_angle_cls,
                use_doc_unwarping=False,
                use_textline_orientation=use_angle_cls,
                **options,
            )
            result = list(ocr.predict(input=str(path)))
            api_version = "3.x-predict"
        except (TypeError, AttributeError):
            # 兼容仍广泛使用的 PaddleOCR 2.x，不对 OCR 结果做任何内容加工。
            ocr = PaddleOCR(lang=lang, use_angle_cls=use_angle_cls, **options)
            result = ocr.ocr(str(path), cls=use_angle_cls)
            api_version = "2.x-ocr"
        safe_result = _json_safe(result)
        # raw_content 保存完整 OCR 引擎输出（坐标、逐行原文、置信度），不拼接/纠错/清洗。
        raw_content = json.dumps(safe_result, ensure_ascii=False, separators=(",", ":"))
        input_bytes = path.read_bytes()
        return self.make_record(
            url=str(path),
            raw_content=raw_content,
            extra_meta={
                "ocr_engine": "paddleocr",
                "ocr_api": api_version,
                "lang": lang,
                "use_angle_cls": use_angle_cls,
                "input_file_size_bytes": path.stat().st_size,
                "input_file_sha256": hashlib.sha256(input_bytes).hexdigest(),
                "media_type": f"image/{path.suffix.lower().lstrip('.')}",
                "content_encoding": "utf-8-json",
                "acquisition_method": "local_ocr",
                "confidence_preserved_in_raw_content": True,
            },
        )
