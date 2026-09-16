from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.processing.hierarchy import HIERARCHY_SCHEMA
from src.processing.index_store import SCHEMA
from src.query.agent_api import get_corpus_status, query_agent, search_evidence
from src.query.douluo_query import DouluoQueryEngine
from src.query.vector_index import database_fingerprint


class QueryApiTests(unittest.TestCase):
    def database_without_hierarchy(self, root: Path, empty_hierarchy: bool = False) -> Path:
        path = root / "evidence.sqlite3"
        connection = sqlite3.connect(path)
        connection.executescript(SCHEMA)
        if empty_hierarchy:
            # 模拟层级构建失败后留下表结构、但尚无 source_works 映射的状态。
            connection.executescript(HIERARCHY_SCHEMA)
        connection.execute(
            "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
            ("pdf-page-1", 1, "official_document", "ben10", "test://bible.pdf", "Ben 10 Bible", None, None),
        )
        window = ("bw1", "pdf-page-1", 0, 0, None, "The Omnitrix contains DNA samples.", "h", "{}")
        connection.execute("INSERT INTO context_windows VALUES(?,?,?,?,?,?,?,?)", window)
        connection.execute("INSERT INTO windows_fts VALUES(?,?,?,?)", ("bw1", "Ben 10 Bible", "", window[5]))
        connection.commit()
        connection.close()
        return path

    def test_search_does_not_require_work_hierarchy(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self.database_without_hierarchy(Path(temporary))
            result = search_evidence("Omnitrix", database=database, ip_domain="ben10")
            self.assertEqual(result["results"][0]["window_id"], "bw1")
            self.assertIsNone(result["results"][0]["chapter_id"])
            self.assertEqual(result["results"][0]["work_title"], "Ben 10 Bible")

    def test_search_survives_empty_optional_hierarchy(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self.database_without_hierarchy(Path(temporary), empty_hierarchy=True)
            result = search_evidence("Omnitrix", database=database, ip_domain="ben10")
            self.assertEqual(result["result_count"], 1)
            self.assertIsNone(result["results"][0]["work_id"])

    def test_corpus_status_does_not_count_derived_pages_as_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self.database_without_hierarchy(Path(temporary))
            connection = sqlite3.connect(database)
            meta = '{"source_extra_meta":{"record_role":"derived_document_unit","source_artifact_id":"pdf-original"}}'
            connection.execute(
                "INSERT INTO text_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("bu1", "pdf-page-1", 0, "paragraph", 0, None, "text", "h", 0, 4, 0, 4, meta),
            )
            connection.commit()
            connection.close()
            status = get_corpus_status(database, ip_domain="ben10")
            self.assertEqual(status["source_artifact_count"], 1)
            self.assertEqual(status["processed_source_record_count"], 1)
            self.assertEqual(status["document_unit_count"], 1)

    def database(self, root: Path) -> Path:
        path = root / "evidence.sqlite3"
        connection = sqlite3.connect(path)
        connection.executescript(SCHEMA)
        connection.executescript(HIERARCHY_SCHEMA)
        connection.executemany(
            "INSERT INTO works VALUES(?,?,?,?,?)",
            [("douluo_1", "斗罗大陆", 1, "main", "novel"),
             ("douluo_2", "绝世唐门", 2, "main", "novel")],
        )
        connection.executemany(
            "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
            [("s1", 11, "derived_transcription", "douluo", "test://one", "斗罗大陆", None, None),
             ("s2", 11, "derived_transcription", "douluo", "test://two", "绝世唐门", None, None)],
        )
        connection.executemany("INSERT INTO source_works VALUES(?,?)", [("s1", "douluo_1"), ("s2", "douluo_2")])
        connection.executemany(
            "INSERT INTO chapters VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [("c1", "s1", "douluo_1", None, 1, "第一章", "chapter", 1, 1, 1, 20),
             ("c2", "s2", "douluo_2", None, 1, "第一章", "chapter", 1, 1, 1, 20)],
        )
        windows = [
            ("w1", "s1", 1, 1, "第一章", "唐三的武魂是蓝银草。", "h1", "{}"),
            ("w2", "s2", 1, 1, "第一章", "霍雨浩的武魂是灵眸。", "h2", "{}"),
            ("w3", "s2", 2, 1, "第一章", "霍雨浩今天来到学院。", "h3", "{}"),
        ]
        connection.executemany("INSERT INTO context_windows VALUES(?,?,?,?,?,?,?,?)", windows)
        connection.executemany(
            "INSERT INTO windows_fts VALUES(?,?,?,?)",
            [(row[0], "斗罗大陆" if row[1] == "s1" else "绝世唐门", row[4], row[5]) for row in windows],
        )
        connection.commit()
        connection.close()
        return path

    def test_natural_language_query_and_work_filter(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self.database(Path(temporary))
            result = search_evidence(
                "霍雨浩的武魂是什么", works=["斗二"], top_k=5,
                max_evidence_chars=8, database=database,
            )
            self.assertEqual(result["answer_status"], "evidence_only")
            self.assertEqual(result["works"], ["douluo_2"])
            self.assertEqual(result["results"][0]["window_id"], "w2")
            self.assertTrue(result["results"][0]["evidence_truncated"])
            self.assertIn("trust_level=11", " ".join(result["warnings"]))

    def test_agent_json_operations(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self.database(Path(temporary))
            works = query_agent({"operation": "list_works"}, database=database)
            self.assertEqual(len(works["works"]), 2)
            entity = query_agent(
                {"operation": "get_entity", "name": "唐三", "top_k": 2}, database=database
            )
            self.assertEqual(entity["entity_status"], "evidence_mentions_only")
            self.assertEqual(entity["results"][0]["work_id"], "douluo_1")

    def test_rejects_unknown_work_and_missing_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self.database(Path(temporary))
            engine = DouluoQueryEngine(database)
            with self.assertRaises(ValueError):
                engine.search("唐三", works=["unknown"])
            with self.assertRaises(RuntimeError):
                DouluoQueryEngine(Path(temporary) / "missing.sqlite3")

    def test_vector_hydration_and_database_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self.database(Path(temporary))
            engine = DouluoQueryEngine(database)
            rows = engine.get_windows(["w2", "missing"])
            self.assertEqual(set(rows), {"w2"})
            self.assertEqual(rows["w2"]["work_id"], "douluo_2")
            fingerprint = database_fingerprint(database)
            self.assertEqual(fingerprint["size"], database.stat().st_size)
            self.assertIn("mtime_ns", fingerprint)


if __name__ == "__main__":
    unittest.main()
