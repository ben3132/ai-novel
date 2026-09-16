from __future__ import annotations

import html
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.collector.local_derived_text_collector import DERIVED_NOTE, LocalDerivedTextCollector
from src.collector.derived_document_collector import DerivedDocumentCollector
from src.processing.segmenter import segment_record
from src.processing.index_store import SCHEMA, build_index, search
from src.processing.hierarchy import build_hierarchy
from src.processing.candidate_store import map_candidates
from src.processing.rule_candidates import compile_terms, extract_candidates
from src.processing.window_classifier import classify_window
from src.processing.evidence_validator import validate_evidence
from src.processing.window_builder import build_context_windows


def record(raw: str, source_type: str = "local_text", **meta):
    return {
        "source_id": "source-1",
        "trust_level": 1,
        "source_type": source_type,
        "ip_domain": "douluo",
        "url": "test://source",
        "collect_ts": "2026-08-14T00:00:00Z",
        "raw_content": raw,
        "extra_meta": meta,
    }


class SegmenterTests(unittest.TestCase):
    def test_unfamiliar_ip_is_allowed_and_derived_document_trust_is_fixed(self):
        task = {
            "source_key": "slime_pdf_copy", "ip_domain": "tensei_slime",
            "trust_level": 11, "url": "https://example.test/copy.pdf",
        }
        collector = DerivedDocumentCollector(task, ".")
        self.assertEqual(collector.trust_level, 11)
        with self.assertRaises(ValueError):
            DerivedDocumentCollector({**task, "trust_level": 1}, ".")

    def test_plain_offsets_and_stable_ids(self):
        raw = "第一章 开始\n\n唐三来到村口。\n\n这是第二段。"
        first = list(segment_record(record(raw), max_chars=200))
        second = list(segment_record(record(raw), max_chars=200))
        self.assertEqual([unit.unit_id for unit in first], [unit.unit_id for unit in second])
        for unit in first:
            self.assertEqual(raw[unit.raw_start:unit.raw_end], unit.text)

    def test_windows_crlf_chapter_heading(self):
        raw = "第一章 开始\r\n\r\n唐三来到村口。\r\n\r\n第二章 相遇\r\n\r\n小舞出现。"
        units = list(segment_record(record(raw), max_chars=200))
        chapter_units = [unit for unit in units if unit.unit_type == "chapter"]
        self.assertEqual(len(chapter_units), 2)
        self.assertEqual(chapter_units[0].extra_meta["chapter_title"], "第一章 开始")
        self.assertEqual(chapter_units[1].extra_meta["chapter_title"], "第二章 相遇")

    def test_html_visible_text_and_raw_span(self):
        raw = "<html><script>bad()</script><p>唐三&amp;小舞</p><p>魂师资料</p></html>"
        units = list(segment_record(record(raw, "official_web_html", media_type="text/html")))
        self.assertEqual([unit.text for unit in units], ["唐三&小舞", "魂师资料"])
        for unit in units:
            fragment = html.unescape(raw[unit.raw_start:unit.raw_end])
            self.assertIn(unit.text, fragment)

    def test_base64_binary_is_skipped(self):
        units = list(segment_record(record("JVBERi0=", "official_document", media_type="application/pdf", content_encoding="base64")))
        self.assertEqual(units, [])

    def test_trust_level_is_not_promoted(self):
        item = record("第一章\n\n正文")
        item["trust_level"] = 11
        units = list(segment_record(item))
        self.assertTrue(units)
        self.assertTrue(all(unit.trust_level == 11 for unit in units))

    def test_local_derived_import_is_always_trust_11(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "data" / "ip" / "douluo" / "raw" / "source_material" / "derived_text" / "douluo.txt"
            source.parent.mkdir(parents=True)
            source.write_text("第一章\n\n测试正文", encoding="utf-8")
            expected_raw = source.read_bytes().decode("utf-8")
            task = {
                "name": "test",
                "source_key": "test_local_derived",
                "trust_level": 11,
                "ip_domain": "douluo",
                "path": "source_derived/douluo.txt",
                "encoding": "utf-8",
            }
            imported = LocalDerivedTextCollector(task, str(root)).collect()
            self.assertEqual(imported.trust_level, 11)
            self.assertEqual(imported.raw_content, expected_raw)
            self.assertEqual(imported.extra_meta["note"], DERIVED_NOTE)

    def test_windows_stay_inside_chapter_and_preserve_spans(self):
        paragraph = "唐三进行测试。" * 12
        raw = f"第一章 开始\r\n\r\n{paragraph}\r\n\r\n{paragraph}\r\n\r\n第二章 继续\r\n\r\n{paragraph}"
        item = record(raw)
        item["trust_level"] = 11
        units = list(segment_record(item, max_chars=200))
        payloads = [unit.model_dump() if hasattr(unit, "model_dump") else unit.dict() for unit in units]
        first = list(build_context_windows(payloads, target_chars=200, max_chars=320, overlap_units=1))
        second = list(build_context_windows(payloads, target_chars=200, max_chars=320, overlap_units=1))
        self.assertEqual([window.window_id for window in first], [window.window_id for window in second])
        self.assertTrue(all(window.trust_level == 11 for window in first))
        self.assertTrue(all(len(window.text) <= 320 for window in first))
        self.assertEqual({window.chapter_index for window in first}, {0, 1})
        for window in first:
            for span in window.unit_spans:
                evidence = window.text[span.window_start:span.window_end]
                source_unit = next(unit for unit in units if unit.unit_id == span.unit_id)
                self.assertEqual(evidence, source_unit.text)

    def test_sqlite_index_and_chinese_search(self):
        paragraph = "唐三获得蓝银草武魂。" * 20
        raw = f"第一章 觉醒\n\n{paragraph}"
        source_record = record(raw)
        source_record["extra_meta"]["work_title"] = "测试作品"
        units = list(segment_record(source_record, max_chars=300))
        unit_payloads = [unit.model_dump() if hasattr(unit, "model_dump") else unit.dict() for unit in units]
        windows = list(build_context_windows(unit_payloads, target_chars=200, max_chars=400, overlap_units=1))
        window_payloads = [window.model_dump() if hasattr(window, "model_dump") else window.dict() for window in windows]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            units_file = root / "units.jsonl"
            windows_file = root / "windows.jsonl"
            units_file.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in unit_payloads), encoding="utf-8")
            windows_file.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in window_payloads), encoding="utf-8")
            database = root / "index.sqlite3"
            counts = build_index(database, [units_file], [windows_file])
            self.assertEqual(counts["units"], len(units))
            self.assertEqual(counts["windows"], len(windows))
            self.assertTrue(search(database, "唐三", 5))
            self.assertTrue(search(database, "蓝银草", 5))
            hierarchy = build_hierarchy(database, {
                "测试作品": {"work_id": "test_work", "sequence": 1, "continuity": "test", "kind": "novel"}
            })
            self.assertEqual(hierarchy["works"], 1)
            candidate_rows = list(extract_candidates(window_payloads[0], {
                "entities": {"person": {"唐三": ["唐三"]}}, "domain_terms": {},
                "event_triggers": {}, "noise_markers": [],
            }))
            candidate_file = root / "candidates.jsonl"
            candidate_file.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in candidate_rows), encoding="utf-8")
            mapped = map_candidates(database, [candidate_file])
            self.assertGreater(mapped["mapped"], 0)
            self.assertEqual(mapped["invalid_evidence"], 0)
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            window_row = connection.execute(
                """SELECT w.window_id,w.text,sw.work_id,c.chapter_id,s.trust_level
                   FROM context_windows w JOIN source_works sw ON sw.source_id=w.source_id
                   JOIN chapters c ON c.source_id=w.source_id AND c.chapter_index=w.chapter_index
                   JOIN sources s ON s.source_id=w.source_id LIMIT 1"""
            ).fetchone()
            span = connection.execute(
                "SELECT unit_id FROM window_units WHERE window_id=? ORDER BY ordinal LIMIT 1",
                (window_row["window_id"],),
            ).fetchone()
            connection.close()
            start = window_row["text"].index("唐三")
            validation = validate_evidence(database, {
                "fact_id": "fact-test", "subject": "唐三", "predicate": "拥有武魂", "object": "蓝银草",
                "fact_type": "possession", "work_id": window_row["work_id"], "chapter_id": window_row["chapter_id"],
                "window_id": window_row["window_id"], "evidence_text": window_row["text"],
                "evidence_window_start": 0, "evidence_window_end": len(window_row["text"]),
                "evidence_unit_ids": [], "trust_level": window_row["trust_level"],
                "extraction_method": "test", "status": "candidate",
            })
            self.assertEqual(validation.grounding_status, "grounded")
            self.assertTrue(validation.evidence_exact)

    def test_hierarchy_supports_multiple_sources_for_one_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "index.sqlite3"
            connection = sqlite3.connect(database)
            connection.executescript(SCHEMA)
            connection.executemany(
                "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                [
                    ("page-1", 1, "official_document", "ben10", "test://bible.pdf", "Bible", None, None),
                    ("page-2", 1, "official_document", "ben10", "test://bible.pdf", "Bible", None, None),
                ],
            )
            connection.executemany(
                "INSERT INTO text_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    ("u1", "page-1", 0, "paragraph", 0, None, "one", "h1", 0, 3, 0, 3, "{}"),
                    ("u2", "page-2", 0, "paragraph", 0, None, "two", "h2", 0, 3, 0, 3, "{}"),
                ],
            )
            connection.commit()
            connection.close()
            counts = build_hierarchy(database, {
                "Bible": {"work_id": "ben10_bible", "sequence": 1, "continuity": "development", "kind": "document"}
            })
            self.assertEqual(counts["chapters"], 2)
            connection = sqlite3.connect(database)
            ids = [row[0] for row in connection.execute("SELECT chapter_id FROM chapters")]
            connection.close()
            self.assertEqual(len(ids), len(set(ids)))

    def test_rule_candidates_are_exact_and_non_assertive(self):
        config = {
            "entities": {"person": {"唐三": ["唐三"]}},
            "domain_terms": {"martial_soul": ["武魂", "蓝银草"]},
            "event_triggers": {"acquire": ["获得"]},
            "noise_markers": ["笔趣阁"],
        }
        window = {
            "window_id": "window-1", "source_id": "source-1", "trust_level": 11,
            "ip_domain": "douluo", "chapter_index": 0, "chapter_title": "第一章",
            "text": "唐三获得蓝银草武魂。",
        }
        candidates = list(extract_candidates(window, config, compile_terms(config)))
        self.assertTrue(candidates)
        self.assertTrue(all(item["status"] == "candidate" for item in candidates))
        for item in candidates:
            self.assertEqual(window["text"][item["window_start"]:item["window_end"]], item["mention_text"])

    def test_model_classification_remains_candidate(self):
        class FakeClient:
            provider = "ollama"
            model = "test-model"

            def generate_json(self, system, user, schema):
                return {
                    "relevant": True,
                    "topics": ["能力设定"],
                    "contains_explicit_event": True,
                    "should_extract_facts": True,
                }

        window = {
            "window_id": "window-1", "source_id": "source-1",
            "chapter_index": 0, "chapter_title": "第一章", "text": "唐三觉醒武魂。",
        }
        result = classify_window(window, FakeClient())
        self.assertEqual(result["status"], "model_candidate")
        self.assertNotIn("facts", result)


if __name__ == "__main__":
    unittest.main()
