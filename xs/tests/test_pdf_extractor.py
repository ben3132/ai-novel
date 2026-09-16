import base64
import hashlib
import unittest
from io import BytesIO

from src.processing.pdf_extractor import PdfExtractionError, extract_pdf_pages
from src.processing.segmenter import segment_record


def _record(payload: bytes) -> dict:
    return {
        "source_id": "official-document-parent",
        "trust_level": 1,
        "source_type": "official_document",
        "url": "https://example.test/source.pdf",
        "collect_ts": "2026-01-01T00:00:00Z",
        "ip_domain": "ben10",
        "raw_content": base64.b64encode(payload).decode("ascii"),
        "extra_meta": {
            "media_type": "application/pdf",
            "content_encoding": "base64",
            "content_sha256": hashlib.sha256(payload).hexdigest(),
        },
    }


class PdfExtractorTests(unittest.TestCase):
    def test_extract_blank_pdf_preserves_page_provenance(self):
        try:
            import pypdf
        except ImportError:
            self.skipTest("pypdf is not installed")
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=100, height=100)
        output = BytesIO()
        writer.write(output)

        pages = list(extract_pdf_pages(_record(output.getvalue())))
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["raw_content"], "")
        self.assertEqual(pages[0]["extra_meta"]["parent_source_id"], "official-document-parent")
        self.assertEqual(pages[0]["extra_meta"]["page_number"], 1)
        self.assertTrue(pages[0]["extra_meta"]["requires_ocr"])

    def test_pdf_hash_mismatch_is_rejected(self):
        record = _record(b"%PDF-fake")
        record["extra_meta"]["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(PdfExtractionError, "SHA-256"):
            list(extract_pdf_pages(record))

    def test_page_metadata_reaches_text_units(self):
        record = {
            "source_id": "pdfpage-test",
            "trust_level": 1,
            "source_type": "official_document",
            "url": "https://example.test/source.pdf",
            "collect_ts": "2026-01-01T00:00:00Z",
            "ip_domain": "ben10",
            "raw_content": "Page text.",
            "extra_meta": {
                "content_encoding": "utf-8",
                "media_type": "text/plain",
                "parent_source_id": "official-document-parent",
                "page_number": 7,
                "source_sha256": "abc",
                "extraction_method": "pypdf_text",
            },
        }
        units = list(segment_record(record))
        self.assertEqual(units[0].extra_meta["source_extra_meta"]["page_number"], 7)
        self.assertEqual(
            units[0].extra_meta["source_extra_meta"]["parent_source_id"],
            "official-document-parent",
        )

    def test_page_text_with_trailing_newline_is_segmented(self):
        record = {
            "source_id": "pdfpage-newline",
            "trust_level": 1,
            "source_type": "official_document",
            "url": "https://example.test/source.pdf",
            "collect_ts": "2026-01-01T00:00:00Z",
            "ip_domain": "ben10",
            "raw_content": "First line\nSecond line\n",
            "extra_meta": {"content_encoding": "utf-8", "media_type": "text/plain"},
        }
        self.assertEqual(len(list(segment_record(record))), 1)


if __name__ == "__main__":
    unittest.main()
