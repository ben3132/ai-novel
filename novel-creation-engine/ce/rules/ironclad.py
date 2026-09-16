# -*- coding: utf-8 -*-
"""ironclad.py —— 总纲 V2.0 §24「写作铁律」+ §25「章节四层判定」的可执行化。

**与 §23 的本质区别**：§23 是红线，机器可以给"疑似违反"；
§24/§25 是**方法要求与自问清单**，其中大量条目（"这段有戏剧作用吗？"）
机器**无法判断**。对这类条目，L3 的正确做法不是硬凑一个假判据，
而是**生成待答问题 + 附上机器能给出的客观量**，交人作答。

所以本模块分两类：
  · `IRONCLAD_CHECKS` —— 能被客观量化的铁律（段长、对话占比、设定说明书、时序词）
  · `GATE_CHECKS`     —— 四层判定，输出「问题 + 客观量 + 需要人看的段落」
"""

import re

from .hit import Hit, Severity

RULE = Severity.RULE
GATE = Severity.GATE
NOTE = Severity.NOTE

# 章节末尾取样长度（字符）。§25 结尾闸、§25 节拍闸共用。
_TAIL_CHARS = 400


def _lines(text):
    return [(i + 1, ln) for i, ln in enumerate(text.splitlines())]


def _paras(text):
    """返回 [(起行号, 段落文本)]。"""
    out, ln = [], 1
    for p in text.split("\n\n"):
        p2 = p.strip()
        if p2:
            out.append((ln, p2))
        ln += p.count("\n") + 2
    return out


def _split_sentences(p):
    return [s for s in re.split(r"[。！？]", p) if s.strip()]


# ================================================================== §24 铁律

# ------------------------------------------------------- 一章一事，一段一意
# 原文：每段只推进一个信息点。
# 客观量：段落过长（> 300 字）通常意味着塞了多个信息点。
# 这条**不是硬指标**——高潮段可以长。所以给 low，且只在极端处报。

def check_para_too_long(text, chapter_no=None):
    hits = []
    for ln, p in _paras(text):
        n = len(p)
        if n > 380:
            hits.append(Hit(
                rule_id="§24-1",
                rule_name="一章一事，一段一意（段落过长）",
                severity=NOTE,
                line=ln,
                snippet=p[:70],
                basis="总纲 §24：一章一事，一段一意，每段只推进一个信息点。",
                advice=f"本段 {n} 字，通常含多个信息点。检查能否按场景切一刀"
                       "（排队→往前走→入场），每段只留一个推进。",
                confidence="low",
                context=f"段长 {n} 字",
            ))
    return hits


# ------------------------------------------------- 开局不堆设定 / 写体验不写说明书
# 原文：身份用「短袖晒线」体现穷，不是「身世卡」三行字。
#      写具体体验，不写设定说明。
# 客观量：设定说明的典型句式——「是……级」「属于……类」「拥有……能力」
#        「按照……规则」「系统提示：」+ 连续无动作的说明段。

S_SETTING_TELL = re.compile(
    r"(系统提示|【[^】]{1,12}】|等级[:：]|品阶[:：]|"
    r"属于[\u4e00-\u9fa5]{1,6}类|是[\u4e00-\u9fa5]{1,4}级[\u4e00-\u9fa5]{0,6}|"
    r"拥有[\u4e00-\u9fa5]{1,6}(?:的)?能力|按照[\u4e00-\u9fa5]{1,8}规则|"
    r"根据[\u4e00-\u9fa5]{1,8}设定)"
)
S_ACTION = re.compile(
    r"(走|跑|攥|推|抓|拿|扔|拽|拉|抬|低|转|站|坐|踢|踩|按|摸|瞄|"
    r"笑|喊|吼|咬|吐|喘|咳|皱|闭眼|睁眼|抬手|回头|伸手|迈步|"
    r"抽|挥|砸|劈|砍|刺|挡|格|跃|跳|滚|翻|闪|躲|冲|扑|撞|扫|"
    r"调整|下令|下令|决定|开始|结束|查看|检查|交代|解释)"
)


def check_setting_exposition(text, chapter_no=None):
    """设定说明段：说明句式密集 且 句内无动作。"""
    hits = []
    for ln, p in _paras(text):
        n_tell = len(S_SETTING_TELL.findall(p))
        has_action = bool(S_ACTION.search(p))
        # 一段里 >= 2 处说明句式且无动作 → 说明书
        if n_tell >= 2 and not has_action:
            hits.append(Hit(
                rule_id="§24-2",
                rule_name="写具体体验，不写设定说明",
                severity=RULE,
                line=ln,
                snippet=p[:70],
                basis="总纲 §24：写具体体验，不写设定说明；UI 不解释功能，"
                      "在角色使用过程中自然展现。",
                advice=f"本段有 {n_tell} 处说明式表述且无动作。把规则拆成角色的一次操作："
                       "他不看说明，他直接按，然后身上发生变化——读者自己会总结规则。",
                confidence="mid",
                context=p[:120],
            ))
    return hits


# -------------------------------------------------- 环境描写必须有戏剧作用
# 原文：不写「天气好」「阳光明媚」，写对人的压迫/衬托/对照。
# 客观量：天气/风景套话 且 该段无人物反应。

S_WEATHER_CLICHE = re.compile(
    r"(阳光明媚|天气很好|天气不错|万里无云|风和日丽|鸟语花香|"
    r"天空湛蓝|白云朵朵|微风拂过|阳光正好)"
)
S_HUMAN_REACT = re.compile(
    r"(他|她|我|众人|人群|路人|对方|那人)[\u4e00-\u9fa5]{0,6}"
    r"(觉得|感到|感觉|想|怕|疼|累|渴|热|冷|紧张|难受|恶心)"
)


def check_scenery_purpose(text, chapter_no=None):
    hits = []
    for ln, p in _paras(text):
        m = S_WEATHER_CLICHE.search(p)
        if m and not S_HUMAN_REACT.search(p):
            hits.append(Hit(
                rule_id="§24-3",
                rule_name="环境描写必须有戏剧作用",
                severity=RULE,
                line=ln,
                snippet=m.group(0),
                basis="总纲 §24：不写「天气好」「阳光明媚」，写对人的压迫/衬托/对照。",
                advice="这句天气删掉，或者换成它对人做了什么：太阳把队伍晒得往前挪、"
                       "光正好打在她脸上让人看不清表情。",
                confidence="mid",
                context=p[:120],
            ))
    return hits


# ------------------------------------------------------- 信息通过对话带出
# 原文：信息通过对话和内心嘀咕带出，不通过叙事播报。
# 客观量：全章对话占比。占比过低说明全在播报。

def check_dialogue_ratio(text, chapter_no=None):
    if not text.strip():
        return []
    quoted = re.findall(r"[“\"「][^”\"」\n]{1,200}[”\"」]", text)
    n_dialogue = sum(len(q) for q in quoted)
    ratio = n_dialogue / max(1, len(text))
    if ratio < 0.10:
        return [Hit(
            rule_id="§24-4",
            rule_name="信息通过对话和内心嘀咕带出",
            severity=NOTE,
            line=1,
            snippet=f"全章对话占比 {ratio:.1%}",
            basis="总纲 §24：信息通过对话和内心嘀咕带出，不通过叙事播报。",
            advice="对话引号内容占比偏低。检查需要交代的信息，能否让某个配角"
                   "用一句犯贱的废话说出来，而不是叙事者转述。"
                   "（注意：某些章节本来就该以动作/战斗为主，占比低不必然有问题。）",
            confidence="low",
            context=f"对话 {n_dialogue} 字 / 正文 {len(text)} 字",
        )]
    return []


# ------------------------------------------------------- 时序检查
# 原文：写完任何有「时间跳跃」的段落，必须确认前后时序一致。
# 客观量：时间跳跃标记词，逐个列出请人确认。
#
# ⚠️ 早期版本把「想起」也当跳跃标记，导致误报泛滥——
# 「突然想起自己能虚无化」「这才想起一件事」是**正常高频动词**，
# 不是时间线跳跃。教训：只保留**明确指向过去时段**的词，不要收泛化的"回忆动词"。

S_TIME_JUMP = re.compile(
    r"(三天前|两天前|昨天|前天|上周|上个月|半年前|一年前|"
    r"那是[\u4e00-\u9fa5]{0,4}的时候|"
    r"不知过了多久|等到[\u4e00-\u9fa5]{1,6}(?:之?后|后)|"
    r"回过神来|若干年后|多年以前|很久以前|先前|上一次|当年|"
    r"回到[\u4e00-\u9fa5]{0,4}(?:前|以前|那天))"
)


def check_timeline(text, chapter_no=None):
    """不做判定，只**列出所有时间跳跃点**，请人确认。"""
    hits = []
    for ln_no, ln in _lines(text):
        for m in S_TIME_JUMP.finditer(ln):
            hits.append(Hit(
                rule_id="§24-5",
                rule_name="时序检查（列出跳跃点，需人确认）",
                severity=NOTE,
                line=ln_no,
                snippet=m.group(0),
                basis="总纲 §24：写完任何有「时间跳跃」的段落，必须确认前后时序一致"
                      "（回忆 vs 现在）。",
                advice="确认此处跳跃后的时态与物理细节是否自洽"
                       "（回忆里的伤 vs 现在的伤、回忆里在场的人 vs 现在在场的人）。",
                confidence="low",
                context=ln.strip(),
            ))
            break
    return hits


IRONCLAD_CHECKS = [
    check_para_too_long,
    check_setting_exposition,
    check_scenery_purpose,
    check_dialogue_ratio,
    check_timeline,
]


# ================================================================== §25 四层判定
#
# 四层判定是「写完必过」的自问清单。其中：
#   · 节拍闸 —— 可部分客观化（章末新信息量）
#   · 视角闸 —— 可部分客观化（播报句式 vs 感受句式）
#   · 效用闸 —— **不可客观化**，只能列出"疑似非戏剧段"请人读
#   · 结尾闸 —— 可部分客观化（末段是否抛出问题）
#

# ---------------------------------------------------------------- 节拍闸
# 「一章结束时，读者知道了什么新信息？」
# 机器给不了答案，但能给**新专名列表**——新信息通常伴随新名字/新名词出现。

def check_beat_gate(text, chapter_no=None):
    """节拍闸——只给客观量，**绝不猜新信息是什么**。

    ⚠️ 本条历两版失败，教训必须留在代码里：
      v1 用 `([\\u4e00-\\u9fa5]{2,4})(?=说|道|问|答)` 从章末提"专名"
         → 抽出"脸兴奋的""伴随着""跑到街"。根因：中文无词边界，
           "跑到街**道**"的"跑到街"、"兴奋**的**"这类形容词尾全被当成人名。
      v2 改为"全章首现专名" → 噪声性质相同（"在瓦龙""再怎么""龙发出疑"）。

    结论：**纯正则做中文实体识别不可行**，硬做只会产生噪声，
    而噪声比不报更糟（会淹没真问题、损害报告可信度）。

    所以本判据退回它该做的事：给客观量，把"新信息是什么"这个问题交给读的人。
    如果确实需要"本章新登场专名"，那是 **nah orphan / nms 实体提取**的职责——
    L3 不重复实现（见 creation-layer.md §1）。
    """
    lines = text.splitlines()
    tail_start = max(0, len(lines) - 12)
    tail_excerpt = " ".join(lines[tail_start:]).strip()

    quoted = re.findall(r"[“\"「][^”\"」\n]{1,200}[”\"」]", text)
    n_dialogue = sum(len(q) for q in quoted)
    ratio = n_dialogue / max(1, len(text))
    paras = [p for p in text.split("\n\n") if p.strip()]

    metrics = (f"客观量：{len(text)} 字 / {len(paras)} 段 / "
               f"对话占比 {ratio:.1%} / 章末节选 {len(tail_excerpt)} 字")

    return [Hit(
        rule_id="§25-1",
        rule_name="节拍闸：一章结束时读者知道了什么新信息？",
        severity=GATE,
        line=1,
        snippet=metrics,
        basis="总纲 §25 节拍闸：一章结束时，读者知道了什么新信息？"
              "（机器无法回答此问，故只给客观量，避免用启发式猜出噪声。）",
        advice="请人回答：读完本章，读者新增的**一条**最重要信息是什么？"
               "说不出来，说明本章没有推进节拍。"
               "新信息不一定是新角色，也可以是一个新规则、一个新代价、一个新敌人。"
               "若需「本章新登场专名」清单，请调 `nah orphan` 或 nms 的实体提取——"
               "L3 不做实体识别。",
        confidence="low",
        context=tail_excerpt[:220],
    )]


# ---------------------------------------------------------------- 视角闸
# 「这段是角色感受，还是叙事播报？必须是前者。」
# 可部分客观化：播报句式（他感到一阵X / 一种X涌上心头 / 不由得X）

V_BROADCAST = re.compile(
    r"(他感到一阵|她感到一阵|一种[\u4e00-\u9fa5]{1,4}(?:涌上心头|蔓延开来|油然而生)|"
    r"不由得|情不自禁|不由自主地|内心充满了|心中涌起|"
    r"他知道[，,]|他明白[，,]|他清楚[，,]|"
    r"仿佛整个世界|时间仿佛静止)"
)


def check_pov_gate(text, chapter_no=None):
    hits = []
    for ln_no, ln in _lines(text):
        for m in V_BROADCAST.finditer(ln):
            hits.append(Hit(
                rule_id="§25-2",
                rule_name="视角闸：角色感受还是叙事播报？",
                severity=GATE,
                line=ln_no,
                snippet=m.group(0),
                basis="总纲 §25 视角闸：这段是角色感受，还是叙事播报？必须是前者。",
                advice="「他感到一阵X」是播报。换成身体的具体位置与动作——"
                       "不要写「他觉得心慌」，写「手心先出了汗，他把手在裤子上蹭了蹭」。",
                confidence="mid",
                context=ln.strip(),
            ))
            break
    return hits


# ---------------------------------------------------------------- 效用闸
# 「这段描写构成了什么压力/对照/推进？」
# **完全不可客观化**。只列出疑似"纯装饰"的段。
#
# ⚠️ 早期版本只用"段里含景/形容词 + 不含冲突词"就报，
# 结果把「小玉抄起脚边的树枝就又准备冲上去」也报成纯装饰（含"树"）。
# 那是**动作推进**，完全有效用。教训：**描写词必须处于主语/谓语位置**，
# 仅仅出现在状语或宾语里（脚边的树枝）不构成装饰段。
#
# 收紧后的判据：一段**以景/形容起头**（前 6 字内出现），
# 且整段无人物动作、无冲突词、无人称主体做主语。

U_DECOR = re.compile(
    r"^(?:[“\"「])?(?P<dec>阳光|月光|星光|微风|空气|天空|云|雨|雪|风|"
    r"景色|风景|阳光明媚|天气|夜色|晨光)"
)
U_CONFLICT = re.compile(
    r"(喊|吼|争|吵|骂|打|撞|推|抓|跑|逃|追|眼红|难看|笑他|"
    r"不对|不行|凭什么|为什么|怎么办|必须|来不及)"
)
# 段落主体：有人称代词/人名做主语
U_SUBJECT = re.compile(
    r"(我|他|她|它|你|小玉|小班|成龙|老爹|特鲁|龙叔|众人|大家)"
)


def check_utility_gate(text, chapter_no=None):
    hits = []
    for ln, p in _paras(text):
        # 收紧①：描写词必须在段首 6 字内（处于主位），不是随便出现在句中
        if not U_DECOR.search(p[:8]):
            continue
        # 收紧②：有任何人物动作/冲突就不报
        if U_CONFLICT.search(p) or S_ACTION.search(p):
            continue
        # 收紧③：句子里有主体做主语（说明是在写人看到什么，不是纯景物）
        if U_SUBJECT.search(p) and len(p) < 60:
            continue
        hits.append(Hit(
            rule_id="§25-3",
            rule_name="效用闸：这段描写构成了什么压力/对照/推进？",
            severity=GATE,
            line=ln,
            snippet=p[:70],
            basis="总纲 §25 效用闸：这段描写构成了什么压力/对照/推进？",
            advice="请人回答：删掉这段，后文有没有损失？若无，删。"
                   "若有，则它必须承担压力/对照/推进中的至少一项——把那一项写实。",
            confidence="low",
            context=p[:120],
        ))
    return hits


# ---------------------------------------------------------------- 结尾闸
# 「止于"下一个问题被提出"，而不是"事件完结"。」
# 客观量：末段是否以「问题/悬念标记」结尾。

E_QUESTION = re.compile(
    r"([？?]|不知道|会不会|能不能|是不是|为什么|到底|究竟|"
    r"还得|接下来|下一步|麻烦|问题|麻烦大了|要出事了)"
)
E_CLOSED = re.compile(
    r"(终于|总算|结束了|解决了|平息|圆满|松了[一口]?气|落幕|尘埃落定)")

# 结尾口号句：动作片台词腔（与 forbidden.py 的 §23-6 同源，此处用于 §25 结尾闸）
E_SLOGAN_SENT = re.compile(
    r"(那么[，,]?\s*[\u4e00-\u9fa5]{2,8}|要你好看|等着|来吧|上吧|我来了|"
    r"让你见识|就凭|休想|不死不休|走着瞧|且看|今日便是|从今天起|"
    r"我一定会|我发誓|绝不|英雄登场|好戏(?:开始|开场)|是时候了)"
)


def _line_of(text, needle, default=1):
    """找 needle 首字符在 text 里的行号。"""
    i = text.find(needle)
    return default if i < 0 else text[:i].count("\n") + 1


def check_ending_gate(text, chapter_no=None):
    """结尾闸。

    ⚠️ 关键实现细节：**必须扫末 N 段，不能只看最后一段**。
    实测 ep_001 的真实结尾是：
        …「那么，英雄登场」        ← 这是 §23-6 喊口号
        …重重的对着表盘拍了下去。
        「嚎唔」                   ← 最后一段是这个拟声词
    只取最后一段就会漏掉真正的口号句。所以取末 4 段合并后统一判定。
    """
    tail = text[-_TAIL_CHARS:].rstrip()
    paras = [p.strip() for p in tail.split("\n\n") if p.strip()]
    if not paras:
        return []
    window = " ".join(paras[-4:])          # 末 4 段

    hit_slogan = E_SLOGAN_SENT.search(window)
    hit_closed = E_CLOSED.search(window)
    hit_question = E_QUESTION.search(window)

    if hit_closed and not hit_question:
        return [Hit(
            rule_id="§25-4",
            rule_name="结尾闸：止于「下一个问题被提出」",
            severity=GATE,
            line=_line_of(text, window),
            snippet=hit_closed.group(0),
            basis="总纲 §25 结尾闸：止于「下一个问题被提出」，而不是「事件完结」。",
            advice="章末出现「终于/结束了/解决了」这类收束词且无悬念标记。"
                   "把最后一句换成：事情办完的同时，一个**更麻烦的新事实**浮出来"
                   "（代价、后果、旁观者的反应、下一个人物入场）。",
            confidence="mid",
            context=window[:180],
        )]
    return []


GATE_CHECKS = [
    check_beat_gate,
    check_pov_gate,
    check_utility_gate,
    check_ending_gate,
]
