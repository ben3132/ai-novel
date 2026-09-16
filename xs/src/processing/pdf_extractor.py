"""PDF 原件的页级文本提取。

输入必须是采集层保存的标准 JSONL 记录。原始 PDF 保持不变；本模块只在
processed/pdf_pages 下生成可重建的派生文本记录，并保留父 source_id、PDF
字节哈希、页码、解析器版本和提取方式。
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from typing import Any, Dict, Iterable, List


class PdfExtractionError(ValueError):
    """输入不是可验证的 PDF 原始记录。"""


def _decode_pdf(record: Dict[str, Any]) -> tuple[bytes, str]:
    meta = record.get("extra_meta") or {}
    if str(meta.get("content_encoding", "")).lower() != "base64":
        raise PdfExtractionError("PDF raw_content 必须使用 base64 编码")
    try:
        payload = base64.b64decode(record["raw_content"], validate=True)
    except Exception as exc:
        raise PdfExtractionError("raw_content 不是有效 Base64") from exc
    if not payload.startswith(b"%PDF-"):
        raise PdfExtractionError("解码内容不是 PDF 文件")
    digest = hashlib.sha256(payload).hexdigest()
    expected = meta.get("content_sha256") or meta.get("sha256")
    if expected and str(expected).lower() != digest:
        raise PdfExtractionError("PDF SHA-256 与采集元数据不一致")
    return payload, digest


def extract_pdf_pages(record: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """用 pypdf 按页提取文本，输出标准派生记录；不清洗或改写提取结果。"""
    payload, source_sha256 = _decode_pdf(record)
    try:
        import pypdf
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf；请安装 requirements-processing.txt") from exc

    reader = PdfReader(BytesIO(payload))
    parent_meta = dict(record.get("extra_meta") or {})
    parser_version = getattr(pypdf, "__version__", "unknown")
    results: List[Dict[str, Any]] = []
    for page_index, page in enumerate(reader.pages):
        # extract_text 的返回值原样保存；None 只规范为 JSONL 必需的字符串空值。
        text = page.extract_text()
        page_number = page_index + 1
        page_digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        page_id_seed = f"{record['source_id']}\0{page_number}\0{source_sha256}".encode("utf-8")
        page_meta = {
            **parent_meta,
            "media_type": "text/plain",
            "content_encoding": "utf-8",
            "derivation_type": "pdf_page_text_extraction",
            "record_role": "derived_document_unit",
            "source_artifact_id": record["source_id"],
            "extraction_method": "pypdf_text",
            "parser": "pypdf",
            "parser_version": parser_version,
            "parent_source_id": record["source_id"],
            "source_sha256": source_sha256,
            "page_number": page_number,
            "page_index": page_index,
            "page_text_sha256": page_digest,
            "page_has_text": bool(text),
            "requires_ocr": not bool(text),
            "evidence_coordinate": f"pdf_page:{page_number}",
        }
        results.append({
            "source_id": "pdfpage-" + hashlib.sha256(page_id_seed).hexdigest()[:32],
            "trust_level": record["trust_level"],
            # 信任等级来自父原件；source_type 保持来源性质，派生性质在 extra_meta 明示。
            "source_type": record["source_type"],
            "url": record["url"],
            "collect_ts": record["collect_ts"],
            "ip_domain": record["ip_domain"],
            "raw_content": text or "",
            "extra_meta": page_meta,
        })
    return results
