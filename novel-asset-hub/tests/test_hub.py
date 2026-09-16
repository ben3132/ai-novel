#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-asset-hub 单元测试。

全部用例在临时目录里跑，不触碰任何真实工作区。
运行：
    python -m unittest discover -s tests -v
    python -m pytest tests -q
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nah import cli, core, db, workspace as W  # noqa: E402


def run(argv):
    """跑一次 CLI，返回 (退出码, stdout)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nah_test_"))
        self.ws = self.tmp / "小说" / "设定资产"
        self.ws.mkdir(parents=True)
        (self.ws / "chapters").mkdir()
        W.scaffold(self.ws, name="测试书", chapters_dir="chapters")
        # 隔离项目级配置，避免污染真实 nah.config.json
        self._proj = W.PROJECT_ROOT
        W.PROJECT_ROOT = self.tmp / "engine"

    def tearDown(self):
        W.PROJECT_ROOT = self._proj
        shutil.rmtree(self.tmp, ignore_errors=True)

    # 便捷封装
    def nah(self, *args):
        return run(["--root", str(self.ws), *args])

    def card(self, etype, name):
        return self.ws / "cards" / etype / f"{name}.md"


class TestWorkspace(Base):
    def test_scaffold_creates_skeleton(self):
        self.assertTrue((self.ws / W.WORKSPACE_MARK).exists())
        self.assertTrue((self.ws / W.CARD_DIR).is_dir())
        for t in W.DEFAULT_TYPES:
            self.assertTrue((self.ws / W.CARD_DIR / t).is_dir())
        self.assertTrue((self.ws / W.LOG_NAME).exists())
        self.assertTrue((self.ws / "README.md").exists())

    def test_workspace_config_roundtrip(self):
        cfg = W.load_workspace(self.ws)
        self.assertEqual(cfg["name"], "测试书")
        self.assertEqual(os.path.normpath(cfg["chapters_dir"]),
                         os.path.normpath(self.ws / "chapters"))
        self.assertEqual(cfg["types"], W.DEFAULT_TYPES)

    def test_chapters_dir_is_normalized(self):
        """chapters_dir 里的 ../ 应被规整，不留下 `..\\` 这种脏路径。"""
        p = self.tmp / "书A" / "设定资产"
        p.mkdir(parents=True)
        W.scaffold(p, name="书A", chapters_dir="../正文")
        cfg = W.load_workspace(p)
        self.assertNotIn("..", str(cfg["chapters_dir"]))
        self.assertEqual(Path(cfg["chapters_dir"]), self.tmp / "书A" / "正文")

    def test_custom_types(self):
        p = self.tmp / "定制"
        W.scaffold(p, name="定制书", types=["角色", "组织"])
        cfg = W.load_workspace(p)
        self.assertEqual(cfg["types"], ["角色", "组织"])
        code, _ = run(["--root", str(p), "add", "--type", "角色", "--name", "甲"])
        self.assertEqual(code, 0)
        code, out = run(["--root", str(p), "add", "--type", "人物", "--name", "乙"])
        self.assertEqual(code, 1)
        self.assertIn("未知类型", out)

    def test_defaults_when_no_marker(self):
        p = self.tmp / "裸目录"
        (p / W.CARD_DIR).mkdir(parents=True)
        cfg = W.load_workspace(p)
        self.assertEqual(cfg["name"], "裸目录")
        self.assertEqual(cfg["types"], W.DEFAULT_TYPES)
        self.assertIsNone(cfg["chapters_dir"])

    def test_resolve_root_priority(self):
        env_ws = self.tmp / "envws"
        W.scaffold(env_ws)
        import os
        os.environ["NAH_ROOT"] = str(env_ws)
        try:
            self.assertEqual(W.resolve_root(), env_ws.resolve())
            # 显式参数优先于环境变量
            self.assertEqual(W.resolve_root(explicit=str(self.ws)), self.ws.resolve())
        finally:
            os.environ.pop("NAH_ROOT", None)

    def test_resolve_root_rejects_non_workspace(self):
        plain = self.tmp / "普通目录"
        plain.mkdir()
        with self.assertRaises(W.WorkspaceError):
            W.resolve_root(explicit=str(plain))

    def test_resolve_root_named_workspace(self):
        W.register("测试书", self.ws, set_default=True)
        self.assertEqual(W.resolve_root(ws="测试书"), self.ws.resolve())
        with self.assertRaises(W.WorkspaceError):
            W.resolve_root(ws="不存在的书")


class TestDedupe(Base):
    def test_add_and_hard_conflict(self):
        code, _ = self.nah("add", "--type", "人物", "--name", "陈末")
        self.assertEqual(code, 0)
        self.assertTrue(self.card("人物", "陈末").exists())
        # 同名 -> 硬拦
        code, out = self.nah("add", "--type", "人物", "--name", "陈末")
        self.assertEqual(code, 1)
        self.assertIn("[拦截]", out)
        # 别名撞车 -> 硬拦
        code, out = self.nah("add", "--type", "势力", "--name", "末班", "--alias", "陈末")
        self.assertEqual(code, 1)
        self.assertIn("[拦截]", out)

    def test_soft_conflict_chinese_shortname(self):
        self.nah("add", "--type", "人物", "--name", "唐雅")
        code, out = self.nah("add", "--type", "人物", "--name", "唐娅")
        self.assertEqual(code, 1)
        self.assertIn("[疑似重复]", out)
        self.assertIn("唐雅", out)

    def test_force_bypasses(self):
        self.nah("add", "--type", "人物", "--name", "陈末")
        code, _ = self.nah("add", "--type", "人物", "--name", "陈末", "--force")
        self.assertEqual(code, 0)

    def test_blank_body_gets_placeholder(self):
        self.nah("add", "--type", "设定", "--name", "空设定")
        txt = self.card("设定", "空设定").read_text(encoding="utf-8")
        self.assertIn("（待补充）", txt)

    def test_relations_parsed(self):
        self.nah("add", "--type", "人物", "--name", "陈末", "--rel", "所属:蔷薇会")
        ents = core.load_entities(self.ws)
        rels = ents[0]["relations"]
        self.assertEqual(rels[0]["kind"], "所属")
        self.assertEqual(rels[0]["target"], "蔷薇会")


class TestDetectAndBrief(Base):
    def setUp(self):
        super().setUp()
        self.nah("add", "--type", "人物", "--name", "陈末", "--alias", "小末")
        self.nah("add", "--type", "势力", "--name", "蔷薇会")
        self.chap = self.ws / "chapters" / "ep_001.md"
        self.chap.write_text(
            "# 第一章\n[[陈末]] 走进 [[蔷薇会]]，遇到 [[夜枭]]。\n小末 点了点头。\n",
            encoding="utf-8")

    def test_scan_hits_and_alias(self):
        _, out = self.nah("scan", str(self.chap))
        self.assertIn("陈末", out)
        self.assertIn("x2", out)          # 陈末 + 别名「小末」
        self.assertIn("蔷薇会", out)
        self.assertIn("[[夜枭]]", out)
        self.assertIn("未登记引用 1 个", out)

    def test_scan_json(self):
        _, out = self.nah("scan", str(self.chap), "--json")
        data = json.loads(out)
        names = {h["name"]: h["count"] for h in data["hits"]}
        self.assertEqual(names["陈末"], 2)
        self.assertEqual(data["unresolved"], ["夜枭"])

    def test_brief_writes_package(self):
        out_path = self.ws / "_资料包.md"
        self.nah("brief", str(self.chap), "--out", str(out_path))
        md = out_path.read_text(encoding="utf-8")
        self.assertIn("写作资料包", md)
        self.assertIn("未登记引用", md)
        self.assertIn("陈末", md)

    def test_single_char_alias_ignored(self):
        self.nah("add", "--type", "人物", "--name", "王五", "--alias", "五")
        ents = core.load_entities(self.ws)
        res = core.detect(ents, "五五五五五五")
        self.assertEqual(res["hits"], [])   # 单字别名不参与自动命中


class TestIndex(Base):
    def setUp(self):
        super().setUp()
        self.nah("add", "--type", "人物", "--name", "陈末")
        self.nah("add", "--type", "道具", "--name", "小破表")

    def test_index_files(self):
        reg = core.build_index(self.ws)
        self.assertEqual(reg["count"], 2)
        self.assertEqual(reg["project"], "测试书")
        self.assertTrue((self.ws / W.INDEX_NAME).exists())
        human = (self.ws / W.HUMAN_INDEX_NAME).read_text(encoding="utf-8")
        self.assertIn("测试书", human)
        self.assertIn("小破表", human)

    def test_registry_project_not_from_parent_dir(self):
        """项目名取自 workspace.json，而不是上级文件夹名（解耦点回归）。"""
        reg = json.loads((self.ws / W.INDEX_NAME).read_text(encoding="utf-8"))
        self.assertEqual(reg["project"], "测试书")
        self.assertNotEqual(reg["project"], self.ws.parent.name)


class TestVersionLayer(Base):
    def setUp(self):
        super().setUp()
        self.nah("add", "--type", "人物", "--name", "陈末", "--rel", "所属:蔷薇会")
        self.nah("add", "--type", "势力", "--name", "蔷薇会")
        self.nah("sync", "--note", "首次建库")

    def test_sync_and_info(self):
        code, out = self.nah("info")
        self.assertEqual(code, 0)
        self.assertIn("实体 2", out)
        self.assertIn("索引与卡片同步", out)

    def test_history_records_update(self):
        p = self.card("人物", "陈末")
        p.write_text(p.read_text(encoding="utf-8").replace("（待补充）", "外卖员出身"),
                     encoding="utf-8")
        self.nah("sync", "--note", "补出身")
        _, out = self.nah("history", "人物/陈末")
        self.assertIn("补出身", out)
        self.assertIn("正文", out)

    def test_history_by_alias(self):
        _, out = self.nah("history", "陈末")
        self.assertIn("变更史", out)

    def test_impact(self):
        _, out = self.nah("impact", "蔷薇会")
        self.assertIn("陈末", out)          # 陈末 的 [[蔷薇会]] 引用
        self.assertIn("影响面", out)

    def test_find_by_world_and_grep(self):
        _, out = self.nah("find", "--grep", "蔷薇")
        self.assertIn("蔷薇会", out)
        _, out = self.nah("find", "--world", "不存在的世界")
        self.assertIn("无匹配", out)

    def test_query_select_only(self):
        code, out = self.nah("query", "DELETE FROM entities")
        self.assertEqual(code, 1)
        self.assertIn("只允许 SELECT", out)
        code, out = self.nah("query", "SELECT name FROM entities ORDER BY name")
        self.assertEqual(code, 0)
        self.assertIn("陈末", out)

    def test_dupe(self):
        _, out = self.nah("dupe")
        self.assertIn("无", out)

    def test_rename_propagation(self):
        self.nah("rename", "蔷薇会", "玫瑰会", "--note", "作者改名")
        # 卡片内引用被改写
        self.assertIn("[[玫瑰会]]", self.card("人物", "陈末").read_text(encoding="utf-8"))
        self.assertFalse(self.card("势力", "蔷薇会").exists())
        self.assertTrue(self.card("势力", "玫瑰会").exists())
        # 旧名降级为 retired 别名 -> 正文里的旧写法仍可命中
        self.nah("sync", "--note", "改名后重建")
        ents = core.load_entities(self.ws)
        reg = {e["name"]: e for e in ents}
        self.assertIn("蔷薇会", reg["玫瑰会"]["aliases"])
        self.assertIn("蔷薇会", reg["玫瑰会"]["retired"])
        res = core.detect(ents, "他们去了 [[蔷薇会]]。")
        self.assertEqual([h["entity"]["name"] for h in res["hits"]], ["玫瑰会"])
        self.assertEqual(res["unresolved"], [])

    def test_rename_rejects_existing_target(self):
        code, out = self.nah("rename", "蔷薇会", "陈末")
        self.assertEqual(code, 1)
        self.assertIn("已存在", out)

    def test_rename_no_duplicate_create_record(self):
        """改名后 sync 不应再记一条多余的「新建」；且历史能回溯到改名前的 id。"""
        self.nah("rename", "蔷薇会", "玫瑰会")
        self.nah("sync", "--note", "改名后重建")
        _, out = self.nah("history", "玫瑰会")
        self.assertEqual(out.count("＋ 新建"), 1)      # 只有最初那一条，没有多余新建
        self.assertIn("改名", out)
        self.assertIn("含前身", out)                    # 链条接回了 势力/蔷薇会
        self.assertIn("势力/蔷薇会", out)


class TestCheck(Base):
    def setUp(self):
        super().setUp()
        self.nah("add", "--type", "人物", "--name", "陈末", "--rel", "所属:不存在的帮")
        self.nah("add", "--type", "人物", "--name", "顾青", "--status", "待确认")

    def test_check_reports_all_categories(self):
        _, out = self.nah("check")
        self.assertIn("断链引用", out)
        self.assertIn("[[不存在的帮]]", out)
        self.assertIn("非稳定状态", out)
        self.assertIn("待确认", out)
        self.assertIn("正文未出现", out)

    def test_check_skips_missing_chapters_dir(self):
        p = self.tmp / "无章节"
        W.scaffold(p, name="无章节书", chapters_dir="../不存在")
        run(["--root", str(p), "add", "--type", "人物", "--name", "甲"])
        _, out = run(["--root", str(p), "check"])
        self.assertIn("跳过", out)

    def test_check_json(self):
        _, out = self.nah("check", "--json")
        self.assertIn('"dangling"', out)

    def test_meta_tag_exempts_never_used(self):
        """tag 含「元设定」的卡片不入正文，不该进「已登记但正文未出现」清单。"""
        self.nah("add", "--type", "设定", "--name", "写作口径", "--tag", "元设定")
        self.nah("add", "--type", "设定", "--name", "普通设定")
        code, out = self.nah("check")
        self.assertEqual(code, 0)
        # 取「已登记但正文未出现」这一节的内容（到下一个 【 小节为止）
        sec = out.split("【已登记但正文未出现")[1].split("【")[0]
        self.assertIn("普通设定", sec)
        self.assertNotIn("写作口径", sec)     # 元设定被豁免
        self.assertIn("已豁免", out)

    def test_meta_card_flagged_when_instances_not_landed(self):
        """元设定卡片若连「档案」段里写的实例名都没进正文，仍要提示。"""
        self.nah("add", "--type", "设定", "--name", "世界配置", "--tag", "元设定",
                 "--body", "## 档案\n- 落点＝某个不存在的世界\n")
        _, out = self.nah("check")
        self.assertIn("实例未落地", out)
        meta_sec = out.split("实例未落地")[1].split("【")[0]
        self.assertIn("世界配置", meta_sec)


class TestCli(Base):
    def test_global_flag_after_subcommand(self):
        """--root 写在子命令之后也应生效。"""
        code, _ = run(["add", "--root", str(self.ws), "--type", "人物", "--name", "甲"])
        self.assertEqual(code, 0)
        self.assertTrue(self.card("人物", "甲").exists())

    def test_ws_command_group(self):
        code, out = run(["ws", "add", "测试书", str(self.ws), "--default"])
        self.assertEqual(code, 0)
        code, out = run(["ws", "list"])
        self.assertIn("测试书", out)
        code, out = run(["ws", "show", "--ws", "测试书"])
        self.assertIn("测试书", out)
        code, out = run(["ws", "rm", "测试书"])
        self.assertEqual(code, 0)
        self.assertTrue(self.ws.exists())     # 只解除登记，不动磁盘

    def test_init_scaffolds_and_registers(self):
        target = self.tmp / "新书" / "设定资产"
        code, out = run(["init", str(target), "--name", "新书", "--as-name", "新书"])
        self.assertEqual(code, 0)
        self.assertTrue((target / W.WORKSPACE_MARK).exists())
        self.assertEqual(W.load_project_config()["workspaces"]["新书"], str(target.resolve()))

    def test_missing_workspace_message(self):
        code, out = run(["list"])
        self.assertEqual(code, 2)
        self.assertIn("无法确定工作区", out)

    def test_no_args_prints_help(self):
        code, out = run([])
        self.assertEqual(code, 0)
        self.assertIn("novel-asset-hub", out)


class TestOrphan(Base):
    """反向扫描：正文出现但未登记的名称（含 IP 证据库三分类）。"""

    def _corpus(self, spec):
        """把 {名字: 次数} 写成若干章正文。"""
        lines = []
        for name, n in spec.items():
            lines += [f"对{name}说。“别动。”" for _ in range(n)]
        (self.ws / "chapters" / "ep_001.md").write_text("\n".join(lines), encoding="utf-8")

    def _fake_evidence(self, text, ip="fakeip"):
        """造一个最小 evidence.sqlite3（只有 context_windows）。"""
        import sqlite3
        d = self.tmp / "ip" / ip / "processed" / "index"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "evidence.sqlite3"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE context_windows(window_id INTEGER, text TEXT)")
        con.execute("INSERT INTO context_windows VALUES(1, ?)", (text,))
        con.commit()
        con.close()
        return p

    # ---- 抽取规则 ----

    def test_extract_prep_pattern(self):
        from nah import orphan
        got = orphan.raw_candidates("成龙对小玉说道。“别动。”")
        self.assertIn("小玉", got)

    def test_extract_takes_center_noun_after_de(self):
        from nah import orphan
        got = orphan.raw_candidates("他对已经走进柜台的成龙说道。")
        self.assertIn("成龙", got)
        self.assertNotIn("已经走进", got)

    def test_extract_title_pattern_strips_title(self):
        from nah import orphan
        self.assertIn("小玉", orphan.raw_candidates("小玉姐，你看。"))

    def test_extract_title_pattern_rejects_verb_glue(self):
        from nah import orphan
        self.assertNotIn("看到龙", orphan.raw_candidates("他看到了看到龙叔的脸。"))

    def test_plausible_filters_noise(self):
        from nah import orphan
        self.assertFalse(orphan.plausible("他们"))    # 代词打头
        self.assertFalse(orphan.plausible("对方"))    # 常见名词
        self.assertFalse(orphan.plausible("一"))      # 太短
        self.assertTrue(orphan.plausible("黄静"))

    # ---- 三分类 ----

    def test_scan_gap_three_way(self):
        self.nah("add", "--type", "人物", "--name", "陈末")
        self._corpus({"陈末": 5, "夜枭": 5, "成龙": 5})
        ev = self._fake_evidence("成龙 是一名考古学家")

        from nah import orphan
        cfg = W.load_workspace(self.ws)
        res = orphan.scan_gap(self.ws, cfg, db_paths=[ev])

        self.assertEqual([x["name"] for x in res["unregistered"]], ["夜枭"])
        self.assertIn("成龙", [x["name"] for x in res["from_ip"]])
        self.assertIn("陈末", [x["name"] for x in res["registered"]])
        self.assertEqual(res["unregistered"][0]["first_seen"], "ep_001.md")

    def test_scan_gap_without_ip_db_degrades(self):
        self._corpus({"陈末": 5, "夜枭": 5})
        from nah import orphan
        cfg = W.load_workspace(self.ws)
        res = orphan.scan_gap(self.ws, cfg, db_paths=[])
        self.assertEqual(res["ip_sources"], [])
        self.assertIn("夜枭", [x["name"] for x in res["unregistered"]])
        self.assertEqual(res["from_ip"], [])

    def test_scan_gap_min_count(self):
        # 「夜枭」全文出现 4 次（够 shrink 的词频门槛），但只有 1 次落在句式锚点上
        (self.ws / "chapters" / "ep_001.md").write_text(
            "夜枭站在那里。\n夜枭笑了。\n夜枭走了。\n对夜枭说。“别动。”", encoding="utf-8")
        from nah import orphan
        cfg = W.load_workspace(self.ws)
        got1 = [x["name"] for x in orphan.scan_gap(self.ws, cfg, min_count=1, db_paths=[])["unregistered"]]
        got2 = [x["name"] for x in orphan.scan_gap(self.ws, cfg, min_count=2, db_paths=[])["unregistered"]]
        self.assertIn("夜枭", got1)
        self.assertNotIn("夜枭", got2)

    def test_scan_gap_missing_chapters(self):
        from nah import orphan
        cfg = W.load_workspace(self.ws)
        with self.assertRaises(orphan.OrphanError):
            orphan.scan_gap(self.ws, {**cfg, "chapters_dir": None})

    # ---- 命令与集成 ----

    def test_orphan_command(self):
        self.nah("add", "--type", "人物", "--name", "陈末")
        self._corpus({"陈末": 5, "夜枭": 5})
        code, out = self.nah("orphan")
        self.assertEqual(code, 0)
        self.assertIn("未登记", out)
        self.assertIn("夜枭", out)
        self.assertIn("陈末", out)

    def test_check_includes_reverse_scan(self):
        self._corpus({"夜枭": 5})
        code, out = self.nah("check")
        self.assertEqual(code, 0)
        self.assertIn("正文出现但未登记", out)
        self.assertIn("夜枭", out)

    def test_workspace_config_reads_ip_evidence(self):
        import json
        d = self.tmp / "ip" / "ben10" / "processed" / "index"
        d.mkdir(parents=True, exist_ok=True)
        (d / "evidence.sqlite3").write_bytes(b"")
        (self.ws / W.WORKSPACE_MARK).write_text(json.dumps({
            "name": "测试书", "chapters_dir": "chapters",
            "ip_evidence": ["../../ip/ben10/processed/index/evidence.sqlite3"],
        }, ensure_ascii=False), encoding="utf-8")
        cfg = W.load_workspace(self.ws)
        self.assertEqual(len(cfg["ip_evidence"]), 1)
        self.assertEqual(os.path.normpath(cfg["ip_evidence"][0]),
                         os.path.normpath(d / "evidence.sqlite3"))

    def test_orphan_label_from_path(self):
        from nah import orphan
        ev = self._fake_evidence("成龙", ip="jackie_chan")
        self.assertEqual(orphan._label(ev), "jackie_chan")


if __name__ == "__main__":
    unittest.main(verbosity=2)
