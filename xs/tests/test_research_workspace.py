from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.agent.ip_agent import run_ip_agent
from src.processing.hierarchy import HIERARCHY_SCHEMA
from src.processing.index_store import SCHEMA
from src.query.agent_api import search_evidence


class ResearchWorkspaceTests(unittest.TestCase):
    def test_agent_guidance_defines_decision_boundary(self):
        guidance = run_ip_agent({"operation": "get_agent_guidance"})
        self.assertFalse(guidance["embedded_llm_required"])
        self.assertEqual(guidance["decision_owner"], "connected_agent")
        self.assertIn("discover_dynamic_sources", guidance["agent_responsibilities"])
        self.assertEqual(guidance["trust_rules"]["11"], "third_party_transcription_requires_l1_cross_check")
        self.assertIn("search_hybrid", guidance["implemented_agent_operations"])
        self.assertNotIn("collect", guidance["implemented_agent_operations"])
        self.assertEqual(guidance["cli_commands"]["collect"], "run_l1_collect.py")
        self.assertIn("coverage_report_operation", guidance["not_implemented"])

    def test_agent_handoff_workflow_and_trust_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = run_ip_agent({
                "operation": "initialize_ip", "ip_domain": "sample_ip",
                "name": "Sample IP", "aliases": ["示例IP"],
            }, research_root=root)
            self.assertEqual(created["counts"]["works"], 0)
            self.assertEqual({row["action"] for row in created["next_actions"]}, {"discover_sources", "discover_work_tree"})
            self.assertTrue(all(row["kind"] == "agent_task" for row in created["next_actions"]))
            self.assertTrue(all(not row["directly_executable"] for row in created["next_actions"]))
            run_ip_agent({
                "operation": "register_work", "ip_domain": "sample_ip",
                "work": {"work_id": "sample_main", "title": "Sample", "continuity_id": "main"},
            }, research_root=root)
            source = run_ip_agent({
                "operation": "register_source", "ip_domain": "sample_ip",
                "source": {"url": "https://example.test/wiki", "trust_level": 4, "work_id": "sample_main"},
            }, research_root=root)
            self.assertFalse(source["eligible_for_reasoning"])
            self.assertTrue(source["requires_cross_check"])
            status = run_ip_agent({"operation": "get_research_status", "ip_domain": "sample_ip"}, research_root=root)
            self.assertEqual(status["counts"]["sources"], 1)
            self.assertTrue((root / "data" / "ip" / "sample_ip" / "processed" / "research" / "events.jsonl").is_file())

    def test_claim_requires_evidence_and_marks_cross_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_ip_agent({"operation": "initialize_ip", "ip_domain": "sample_ip", "name": "Sample"}, research_root=root)
            with self.assertRaises(ValueError):
                run_ip_agent({
                    "operation": "save_claim_candidate", "ip_domain": "sample_ip",
                    "claim": {"subject": "A", "predicate": "is", "object": "B", "work_id": "w"},
                }, research_root=root)
            claim = run_ip_agent({
                "operation": "save_claim_candidate", "ip_domain": "sample_ip",
                "claim": {"subject": "A", "predicate": "is", "object": "B", "work_id": "w", "evidence_window_ids": ["window-1"], "trust_levels": [2]},
            }, research_root=root)
            self.assertTrue(claim["needs_l1_cross_check"])
            self.assertEqual(claim["status"], "candidate")

    def test_query_isolates_ip_domains(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "evidence.sqlite3"
            connection = sqlite3.connect(database)
            connection.executescript(SCHEMA)
            connection.executescript(HIERARCHY_SCHEMA)
            connection.executemany("INSERT INTO works VALUES(?,?,?,?,?)", [
                ("work_a", "作品A", 1, "main", "novel"), ("work_b", "作品B", 2, "main", "manga")])
            connection.executemany("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)", [
                ("s_a", 11, "text", "alpha", "test://a", "作品A", None, None),
                ("s_b", 2, "wiki", "beta", "test://b", "作品B", None, None)])
            connection.executemany("INSERT INTO source_works VALUES(?,?)", [("s_a", "work_a"), ("s_b", "work_b")])
            connection.executemany("INSERT INTO chapters VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
                ("c_a", "s_a", "work_a", None, 1, "一", "chapter", 1, 1, 1, 10),
                ("c_b", "s_b", "work_b", None, 1, "一", "chapter", 1, 1, 1, 10)])
            windows = [
                ("wa", "s_a", 1, 1, "一", "共同名字属于甲世界", "ha", "{}"),
                ("wb", "s_b", 1, 1, "一", "共同名字属于乙世界", "hb", "{}")]
            connection.executemany("INSERT INTO context_windows VALUES(?,?,?,?,?,?,?,?)", windows)
            connection.executemany("INSERT INTO windows_fts VALUES(?,?,?,?)", [
                ("wa", "作品A", "一", windows[0][5]), ("wb", "作品B", "一", windows[1][5])])
            connection.commit()
            connection.close()
            result = search_evidence("共同名字", ip_domain="beta", trust_levels=[2], database=database)
            self.assertEqual([row["window_id"] for row in result["results"]], ["wb"])
            self.assertEqual(result["ip_domain"], "beta")


if __name__ == "__main__":
    unittest.main()
