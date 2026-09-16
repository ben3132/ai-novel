# -*- coding: utf-8 -*-
"""tests/test_rules.py —— 判据离线自测。

**不依赖任何外部项目**，纯字符串进出。测的是"判据在构造样本上的行为"，
不是"判据在真实语料上的准确率"——后者只能靠人工校准（见 README §校准记录）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ce import rules  # noqa: E402
from ce.rules import forbidden as F, ironclad as I  # noqa: E402


class TestSeccion23(unittest.TestCase):
    """§23 八条一级禁则。"""

    def test_not_a_but_b_dash(self):
        """破折号形态应给 high。"""
        t = "他不是冷——是疼。"
        hits = F.check_not_a_but_b(t)
        self.assertTrue(hits)
        self.assertEqual(hits[0].rule_id, "§23-1")
        self.assertEqual(hits[0].confidence, "high")

    def test_not_a_but_b_comma(self):
        t = "他不是学生，是个混混。"
        hits = F.check_not_a_but_b(t)
        self.assertTrue(hits)
        self.assertEqual(hits[0].confidence, "mid")

    def test_not_a_but_b_clean(self):
        """正常否定句不该命中。"""
        for t in ["他不吃饭。", "这里没有人。", "他不知道这件事的来龙去脉。"]:
            self.assertFalse(F.check_not_a_but_b(t), t)

    def test_info_frontload(self):
        t = "他早就知道小破表怎么用了。"
        hits = F.check_info_frontload(t)
        self.assertTrue(hits)
        self.assertEqual(hits[0].rule_id, "§23-2")

    def test_narrator_summary(self):
        t = "原主的事。跟他没关系。但如果标签洗不掉，那就麻烦了。"
        hits = F.check_narrator_summary(t)
        self.assertTrue(hits, "短句堆叠 + 话外音连接词应命中")

    def test_label_over_image(self):
        t = "一道火形人影立在那里。"
        hits = F.check_label_over_image(t)
        self.assertTrue(hits)
        self.assertEqual(hits[0].rule_id, "§23-4")

    def test_label_with_action_ok(self):
        """有具体动作就不算关键词代替画面。"""
        t = "一道火形人影抬手攥住了他的手腕。"
        self.assertFalse(F.check_label_over_image(t))

    def test_crowd_opening_only_ch1(self):
        t = "人群喧闹，周围的人都交头接耳。" * 3
        self.assertTrue(F.check_crowd_opening(t, chapter_no=1))
        self.assertFalse(F.check_crowd_opening(t, chapter_no=2),
                         "群像开场只对第 1 章生效")

    def test_slogan_ending_zh_quote(self):
        """'那么，X' 是本文档实测出的高频口号形态。"""
        t = "他往前走了一段。\n\n“那么，英雄登场”\n\n拍下去。\n\n“嚎唔”"
        hits = F.check_slogan_ending(t)
        self.assertTrue(hits)
        self.assertIn("英雄登场", hits[0].snippet)

    def test_slogan_not_triggered_by_dialogue(self):
        """正常对白（疑问/应答）不该被当口号。"""
        t = "他们打跑了坏人。\n\n“小玉，小班？”\n\n“那好吧”\n\n于是走了。"
        self.assertFalse(F.check_slogan_ending(t))

    def test_slogan_must_scan_full_tail(self):
        """口号在第 N-1 段、末段是拟声词时仍须命中（实测踩过的坑）。"""
        t = ("他抬眼。\n\n“那么，开始吧”\n\n他按下按钮。\n\n“啪”")
        self.assertTrue(F.check_slogan_ending(t))

    def test_prev_owner_no_false_positive_on_body_part(self):
        """'4 臂前身' 是身体部位，不是穿越前身。"""
        t = "用牙齿咬紧，4臂前身尽力拖住机头。"
        self.assertFalse(F.check_prev_owner_confusion(t))

    def test_prev_owner_no_false_positive_on_yuanshen(self):
        """'原身体' = 原本的身体，不是设定词「原主」。"""
        t = "关于变身对原身体影响的课题。"
        self.assertFalse(F.check_prev_owner_confusion(t))

    def test_prev_owner_flags_real_case(self):
        t = "前身做过的事，现在都落在他头上。"
        hits = F.check_prev_owner_confusion(t)
        self.assertTrue(hits, "真正的「前身行为」应命中")

    def test_prev_owner_ok_when_marked(self):
        t = "前身做过的事，原主欠下的人情，现在都落在他头上。"
        self.assertFalse(F.check_prev_owner_confusion(t))

    def test_draft_dir(self):
        t = "参考废稿里的设定。"
        hits = F.check_no_draft_load(t)
        self.assertTrue(hits)
        self.assertEqual(hits[0].confidence, "high")


class TestSeccion24(unittest.TestCase):
    """§24 写作铁律。"""

    def test_para_too_long(self):
        t = "甲" * 400
        hits = I.check_para_too_long(t)
        self.assertTrue(hits)

    def test_setting_exposition(self):
        t = "系统提示：该道具属于A类。它拥有变身能力。"
        hits = I.check_setting_exposition(t)
        self.assertTrue(hits)

    def test_setting_exposition_ok_with_action(self):
        t = "系统提示：他抬手按下去，身上发生了变化。"
        self.assertFalse(I.check_setting_exposition(t))

    def test_scenery_cliche(self):
        t = "阳光明媚，万里无云。"
        self.assertTrue(I.check_scenery_purpose(t))

    def test_dialogue_ratio_low(self):
        t = "他走在路上。" * 50
        hits = I.check_dialogue_ratio(t)
        self.assertTrue(hits)
        self.assertEqual(hits[0].confidence, "low")

    def test_timeline_no_recall_verb_fp(self):
        """'想起' 是高频正常动词，不应算时间跳跃。"""
        t = "他突然想起自己能虚无化。"
        self.assertFalse(I.check_timeline(t), "「想起」不该被当时间跳跃")

    def test_timeline_explicit_jump(self):
        t = "三天前他还在这里。"
        self.assertTrue(I.check_timeline(t))


class TestSeccion25(unittest.TestCase):
    """§25 四层判定。"""

    def test_beat_gate_gives_metrics_not_guesses(self):
        """节拍闸必须只给客观量，不得输出推测出来的专名。"""
        t = "他走在街上。\n\n“你好”\n\n她答道。"
        hits = I.check_beat_gate(t)
        self.assertEqual(len(hits), 1)
        self.assertIn("客观量", hits[0].snippet)
        # 不得出现从前版本那种抽取出的伪专名
        self.assertNotIn("专名", hits[0].snippet)

    def test_pov_gate_broadcast(self):
        t = "他感到一阵恶心。"
        self.assertTrue(I.check_pov_gate(t))

    def test_utility_gate_decor_only(self):
        t = "微风吹落树叶挂在地上沙沙作响。"
        self.assertTrue(I.check_utility_gate(t))

    def test_utility_gate_no_fp_on_action(self):
        """含动作的句子不是纯装饰（实测踩过的坑：'抄起脚边的树枝'）。"""
        t = "小玉抄起脚边的树枝就又准备冲上去。"
        self.assertFalse(I.check_utility_gate(t))

    def test_ending_gate_closed(self):
        t = "事情终于结束了。"
        self.assertTrue(I.check_ending_gate(t))

    def test_ending_gate_open_ok(self):
        t = "他站在门口，不知道接下来会发生什么。"
        self.assertFalse(I.check_ending_gate(t))


class TestRunner(unittest.TestCase):
    """统一入口与过滤。"""

    SAMPLE = (
        "# 第一章\n\n"
        "他不是胆小——是谨慎。\n\n"
        "阳光明媚，万里无云。\n\n"
        "“那么，出发吧”\n"
    )

    def test_run_returns_sorted_hits(self):
        hits = rules.run(self.SAMPLE, chapter_no=1)
        self.assertTrue(hits)
        lines = [h.line for h in hits]
        self.assertEqual(lines, sorted(lines), "命中应按行号排序")

    def test_run_filter_by_rule_set(self):
        only23 = rules.run(self.SAMPLE, chapter_no=1, rules=["§23"])
        self.assertTrue(only23)
        self.assertTrue(all(h.rule_id.startswith("§23") for h in only23))

        only25 = rules.run(self.SAMPLE, chapter_no=1, rules=["§25"])
        self.assertTrue(all(h.rule_id.startswith("§25") for h in only25))

    def test_hit_as_dict_roundtrip(self):
        import json
        hits = rules.run(self.SAMPLE, chapter_no=1)
        d = hits[0].as_dict()
        json.dumps(d, ensure_ascii=False)   # 必须可序列化
        self.assertIn("basis", d)
        self.assertIn("advice", d)

    def test_all_rules_registered(self):
        self.assertEqual(set(rules.ALL_RULES), {"§23", "§24", "§25"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
