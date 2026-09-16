# -*- coding: utf-8 -*-
"""forbidden.py —— 总纲 V2.0 §23「一级禁则（红线）」的可执行化。

八条禁则的机器可判程度差异极大，逐条诚实标注：

| # | 禁则 | 机器可判度 | 手段 |
|---|---|---|---|
| 1 | 不是 A——是 B 句式 | **高** | 正则，几乎无假阴性 |
| 2 | 信息前置 | 低 | 需「道具尚未登场」的前置知识，只能给线索 |
| 3 | 画外音旁白总结 | 中 | 段落级句式特征（短句+句号堆叠+「跟…没关系」） |
| 4 | 关键词代替画面 | 中 | 抽象名词短语 + 缺动词 |
| 5 | 群像开场 | 中 | 仅第 1 章，判开头是否单主角视角 |
| 6 | 结尾喊口号 | 中 | 章节末尾段的短句台词特征 |
| 7 | 原主与穿越者混淆 | 中 | 前身行为动词前缺「原主」 |
| 8 | 日常加载废稿目录 | **高** | 字面检测「废稿」目录引用 |

**共同免责**：这些是句式启发式。定位与 `nah orphan` 一致——
**精度优先、召回有限，是人工复核清单，不是拦截器。**
"""

import re

from .hit import Hit, Severity

R = Severity.RED

# ------------------------------------------------------------------ 工具

# 章节首尾取样长度（字符）。禁则 5/6 只看首尾。
_HEAD_CHARS = 600
_TAIL_CHARS = 400


def _lines(text):
    """返回 [(行号, 行内容)]，行号 1-based。"""
    return [(i + 1, ln) for i, ln in enumerate(text.splitlines())]


def _ctx(text, start, end, pad=40):
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    return text[a:b]


def _para_of(text, pos):
    """取 pos 所在的段落边界（以空行分割）。"""
    a = text.rfind("\n\n", 0, pos)
    a = 0 if a < 0 else a + 2
    b = text.find("\n\n", pos)
    b = len(text) if b < 0 else b
    return a, b, text[a:b]


def _line_of(text, needle, default=1):
    """找 needle 首字符在 text 里的行号（1-based）。"""
    i = text.find(needle)
    return default if i < 0 else text[:i].count("\n") + 1


# ================================================================== 禁则 1
# 禁止「不是 A——是 B」句式
#
# 原文：包括感官对比、说教否定、描写性否定，全部禁止。
# 根因：这是在写"断句节奏"，不是在写"身体感受"。
#       要描写就直接写身体感受，不先否认再定义。
#
# 机器判据：破折号/冒号/逗号连接的「不是X，是Y」否定-定义对。
# 关键是要排除真正的叙事否定（如"他不是学生，是老师"这种纯事实陈述）。
# 实践中很难区分，故只对**破折号连接**和**句读后紧跟"而是"**的形态给 high，
# 其余给 mid。

F1_PATTERNS = [
    # 不是 A——是 B（破折号，最强信号）
    (re.compile(r"不是[^。！？\n]{1,24}?[—–─-]{1,2}\s*是[^。！？\n]{0,24}"), "high"),
    # 不是 A，是 B
    (re.compile(r"不是[^。！？\n]{1,20}?，\s*是[^。！？\n]{0,20}"), "mid"),
    # 不是 A。是 B。（断句强调）
    (re.compile(r"不是[^。！？\n]{1,20}?。\s*是[^。！？\n]{0,20}"), "mid"),
    # 不是……而是……
    (re.compile(r"不是[^。！？\n]{1,24}?而是[^。！？\n]{0,24}"), "high"),
    # 并非/不是……，不过是/只是（变体）
    (re.compile(r"并非[^。！？\n]{1,20}?[，—–─-]{1,2}\s*(?:而?是|只是)[^。！？\n]{0,20}"), "mid"),
]


def check_not_a_but_b(text, chapter_no=None):
    hits = []
    for i, (ln_no, ln) in enumerate(_lines(text)):
        for pat, conf in F1_PATTERNS:
            for m in pat.finditer(ln):
                hits.append(Hit(
                    rule_id="§23-1",
                    rule_name="禁止「不是A——是B」句式",
                    severity=R,
                    line=ln_no,
                    snippet=m.group(0),
                    basis="总纲 §23：包括感官对比、说教否定、描写性否定，全部禁止；"
                          "根因是「在写断句节奏，不是在写身体感受」。",
                    advice="删掉否定的一半，直接写身体感受或动作。"
                           "如「不是冷——是疼」→ 直接写疼的具体表现（哪块肌肉、什么反应）。",
                    confidence=conf,
                    context=ln.strip(),
                ))
                break  # 一行内同一条禁则只报一次，避免变体正则重复命中
    return hits


# ================================================================== 禁则 2
# 禁止信息前置
#
# 原文：主角尚未接触道具时，不允许脑内预演道具玩法。
# 根因：读者应和主角**同步发现**能力，不是提前被预告。
#
# 机器判据的困难：判断"道具是否已登场"需要读者状态，机器不知道。
# L3 的取巧方式——**不做主角状态推断，只标注"疑似预演"的句式**，
# 把道具名与预演动词（知道/清楚/明白/盘算/回想/印象）的同现作为线索，
# 交给 `ce review` 的设定闸（那里有 nah 卡片可知该道具首次出现章）。
# 所以这里只给 low，且建议里明写"需人工确认该道具是否已登场"。

F2_ITEM_HINT = re.compile(
    r"(小破表|超能仪|符咒|芯片|晶片|魔表|手表|变身器)"   # 已知外挂道具名（可扩展）
)
F2_FORESHADOW_VERB = re.compile(
    r"(早就知道|早就清楚|早就明白|心里清楚|心里明白|盘算着|想着等|"
    r"一会儿就|等会就|早晚要|迟早要|好像知道|隐约知道|了然于胸)"
)


def check_info_frontload(text, chapter_no=None):
    hits = []
    off = 0
    for ln_no, ln in _lines(text):
        if F2_ITEM_HINT.search(ln) and F2_FORESHADOW_VERB.search(ln):
            hits.append(Hit(
                rule_id="§23-2",
                rule_name="禁止信息前置（脑内预演道具玩法）",
                severity=R,
                line=ln_no,
                snippet=ln.strip()[:80],
                basis="总纲 §23：主角尚未接触道具时，不允许脑内预演道具玩法；"
                      "读者应和主角同步发现能力。",
                advice="确认该道具此刻是否已由主角亲手接触/触发。"
                       "若否，删掉预演，改为让主角在动作中当场试出来（试错也是看点）。",
                confidence="low",
                context=ln.strip(),
            ))
        off += len(ln) + 1
    return hits


# ================================================================== 禁则 3
# 禁止替读者做总结的画外音旁白
#
# 原文示例：「原主的事。跟陈末没关系。但如果标签洗不掉……」
# 根因：改用动作和细节传达。好作者信读者。
#
# 机器判据：**段落级**的三个特征同时出现——
#   ① 段落由多个结构性短句组成（句号密度高）
#   ② 含"跟…没关系/不关…的事/但…"这类**话外音连接词**
#   ③ 段落里没有动作动词（跑/走/攥/推/抓/拿…）
# 三个同时满足才报，否则误报会淹没作者。

F3_VOICE_CONNECTIVES = re.compile(
    r"(跟[^，。！？\n]{1,10}没关系|不关[^，。！？\n]{1,10}的事|"
    r"但与?他无关|可是[^，。！？\n]{0,8}如果|但如果|只是如果|"
    r"当然[，,]?那?是后话|那是后话|话说回来)"
)
F3_ACTION_VERBS = re.compile(
    r"(走|跑|攥|推|抓|拿|扔|拽|拉|抬|低|转|站|坐|踢|踩|按|摸|"
    r"笑|喊|吼|咬|吐|喘|咳|皱|闭眼|睁眼|抬手|回头)"
)


def _split_sentences(p):
    return [s for s in re.split(r"[。！？]", p) if s.strip()]


def check_narrator_summary(text, chapter_no=None):
    hits = []
    for i, (ln_no, ln) in enumerate(_lines(text)):
        p = ln.strip()
        if len(p) < 12 or not F3_VOICE_CONNECTIVES.search(p):
            continue
        sents = _split_sentences(p)
        # 句号密度：短句堆叠（平均句长 < 12 字）且句数 >= 3
        dense = len(sents) >= 3 and (len(p) / max(1, len(sents))) < 12
        no_action = not F3_ACTION_VERBS.search(p)
        if dense and no_action:
            hits.append(Hit(
                rule_id="§23-3",
                rule_name="禁止替读者做总结的画外音旁白",
                severity=R,
                line=ln_no,
                snippet=p[:80],
                basis="总纲 §23：「原主的事。跟陈末没关系。但如果标签洗不掉……」"
                      "即此类短句堆叠+话外音连接词的旁白。",
                advice="拆掉总结句，把同一信息塞进一个动作或一件物品里。"
                       "好作者信读者——不解释她为什么难过，写她攥着的东西。",
                confidence="mid",
                context=p,
            ))
    return hits


# ================================================================== 禁则 4
# 禁止关键词代替画面
#
# 原文示例：用「火形人影」「肌肉夸张」写降临虚影。
# 根因：要用具体动作和身体反应。
#
# 机器判据：抽象标签式名词短语（"X形人影""X夸张""X感十足""充满X"）
# + 该句无具体动作动词。

F4_LABEL = re.compile(
    r"([\u4e00-\u9fa5]{1,4}形人影|[\u4e00-\u9fa5]{1,4}状人影|"
    r"肌肉夸张|身形夸张|气势夸张|压迫感十足|存在感十足|"
    r"充满[\u4e00-\u9fa5]{1,4}感|无比[\u4e00-\u9fa5]{1,4}|"
    r"极其[\u4e00-\u9fa5]{1,4}(?:的)?[\u4e00-\u9fa5]{0,2}感|"
    r"难以形容|无法形容|说不出的[\u4e00-\u9fa5]{1,4})"
)


def check_label_over_image(text, chapter_no=None):
    hits = []
    for ln_no, ln in _lines(text):
        for m in F4_LABEL.finditer(ln):
            # 句内无动作动词 → 纯标签
            sent = ln
            a = max(ln.rfind(c, 0, m.start()) for c in "。！？")
            a = 0 if a < 0 else a + 1
            b = len(ln)
            for c in "。！？":
                p = ln.find(c, m.end())
                if p >= 0:
                    b = min(b, p)
            sent = ln[a:b]
            if F3_ACTION_VERBS.search(sent):
                continue
            hits.append(Hit(
                rule_id="§23-4",
                rule_name="禁止关键词代替画面",
                severity=R,
                line=ln_no,
                snippet=m.group(0),
                basis="总纲 §23：如用「火形人影」「肌肉夸张」写降临虚影——"
                      "关键词不能代替画面，要用具体动作和身体反应。",
                advice="把标签展开成可见的一帧：他在做什么动作、周围的东西怎么反应、"
                       "谁的身体起了什么变化。标签是给作者自己做备忘的，不是给读者的。",
                confidence="mid",
                context=sent.strip() or ln.strip(),
            ))
            break
    return hits


# ================================================================== 禁则 5
# 禁止群像开场
#
# 原文：第 1 章必须主角视角打底。主角站在人堆里，读者跟着他走。
# 机器判据：仅对 chapter_no == 1 生效，检查开篇 _HEAD_CHARS 内
#          是否出现「多人并列」的群像特征，而缺少单一视角锚点。
#
# 注意：主角"站在人堆里"本身**不违反**——违反的是视角不跟着某一具体人走。
# 所以判据是"群像词密集" **且** "无单人称代词锚点"。

F5_CROWD = re.compile(r"(人群|人堆|大家|众人|所有人|一片人|四周的人|周围的人|喧闹|嘈杂|交头接耳)")
F5_ANCHOR = re.compile(r"(我|他|她|陈末|主角)")   # 主角名单可在 ce.review 里注入


def check_crowd_opening(text, chapter_no=None):
    if chapter_no != 1:
        return []
    head = text[:_HEAD_CHARS]
    crowd_n = len(F5_CROWD.findall(head))
    anchor_n = len(F5_ANCHOR.findall(head))
    # 群像词 >= 2 且 单人称锚点密度明显偏低
    if crowd_n >= 2 and anchor_n < crowd_n * 1.5:
        first_line = head.strip().splitlines()[0] if head.strip() else ""
        return [Hit(
            rule_id="§23-5",
            rule_name="禁止群像开场（第 1 章须主角视角打底）",
            severity=R,
            line=1,
            snippet=first_line[:80],
            basis="总纲 §23：第 1 章必须主角视角打底，主角站在人堆里，读者跟着他走。",
            advice="把镜头收进一个人的感官里：他后背的汗、他排队的位置、他前面的后脑勺。"
                   "人群可以写，但必须是「他感觉到的人群」，不是上帝视角的人堆。",
            confidence="mid",
            context=f"开篇 {_HEAD_CHARS} 字内：群像词 {crowd_n} 处，单人称锚点 {anchor_n} 处",
        )]
    return []


# ================================================================== 禁则 6
# 禁止结尾喊口号
#
# 原文：章节结尾锚点必须是角色此刻真实心理/状态，不是动作片台词。
# 机器判据：取章节末尾段，检测「短句 + 台词腔」特征——
#   末句 <= 14 字，且含战斗口号词 / 感叹号 / "要你好看""等着""来吧"类。

F6_SLOGAN = re.compile(
    r"(要你好看|等着|来吧|上吧|我来了|让你见识|就凭|休想|"
    r"不死不休|走着瞧|且看|今日便是|从今天起|"
    r"我一定会|我发誓|绝不|"
    # ↓ 实测补入：网文最常见的口号前缀与句式
    r"那么[，,]?\s*[\u4e00-\u9fa5]{2,8}|"
    r"英雄登场|好戏(?:开始|开场)|是时候了|登场吧|表演(?:开始|时间)|"
    r"让我们|见证|颤抖吧|臣服|记住了|这句话我会记一辈子)"
)

# 宣告式台词：含号召/宣告语义（"上/走/来/开始/成为"等祈使或未来指向）
F6_DECLARE = re.compile(
    r"(上吧|走吧|来吧|出发|开始吧|登场|见证|记住|看着|成为|"
    r"等着|要你|让你|绝不|决不|一定会|从现在起|从今天起|"
    r"那么[，,]|这就是|将会|即将)"
)


def check_slogan_ending(text, chapter_no=None):
    """结尾喊口号。

    ⚠️ 实现要点：**扫末 4 段，不能只看最后一段**。
    实测 ep_001 真实结尾：
        …「那么，英雄登场」      ← 口号句
        …重重的对着表盘拍了下去。
        「嚎唔」                 ← 最后一段是拟声词
    只看最后一段会漏掉真正的口号。
    """
    tail = text[-_TAIL_CHARS:].rstrip()
    if not tail:
        return []
    paras = [p.strip() for p in tail.split("\n\n") if p.strip()]
    if not paras:
        return []
    window = " ".join(paras[-4:])

    m = F6_SLOGAN.search(window)
    hits = []
    if m:
        hits.append(Hit(
            rule_id="§23-6",
            rule_name="禁止结尾喊口号",
            severity=R,
            line=_line_of(text, m.group(0)),
            snippet=m.group(0),
            basis="总纲 §23：章节结尾锚点必须是角色此刻真实心理/状态，不是动作片台词。",
            advice="把口号换成一个具体到只有这个角色才会做的反应（一个小动作、一句内心嘀咕、"
                   "一个盯着的东西）。结尾停在「他此刻是什么状态」，不是「他宣告什么」。",
            confidence="mid",
            context=window[:180],
        ))
        return hits

    # 次强信号：末 3 段里存在**宣告式台词**。
    #
    # ⚠️ 早期版本「短句(<=10字)且有引号」就报，误报 3/4：
    #     "小玉，小班？"（疑问）/ "那好吧"（应答）/ "……"（省略）
    #   这些是正常对白，不是口号。
    #   收紧：必须**含号召/宣告语义**（动词祈使 + 未来指向 + 感叹），
    #   而不是任意短句。
    for p in paras[-3:]:
        core = p.strip().strip("“”\"「」")
        if len(core) > 14 or len(core) < 2:
            continue
        if not F6_DECLARE.search(core):
            continue
        if F3_ACTION_VERBS.search(core):
            continue
        # 排除纯拟声词（嚎唔/啪/叮铃铃）——它们不是"喊口号"
        if re.fullmatch(r"[嗷嚎呜啪咚叮铃咣哐嗤嗯啊哦额唔噗嗖唰嘿哈]{1,6}", core):
            continue
        hits.append(Hit(
            rule_id="§23-6",
            rule_name="禁止结尾喊口号（疑似宣告式台词收尾）",
            severity=R,
            line=_line_of(text, p),
            snippet=p,
            basis="总纲 §23：章节结尾锚点必须是角色此刻真实心理/状态，不是动作片台词。",
            advice="检查这个短句是「角色的真实状态」还是「台词腔宣告」。"
                   "若是后者，换成一个具体反应（动作、内心嘀咕、盯着的东西）。",
            confidence="low",
            context=window[:180],
        ))
        break
    return hits


# ================================================================== 禁则 7
# 禁止原主与穿越者混淆
#
# 原文：所有前身行为前加「原主」二字，避免读者混淆主人公与前身性格。
# 机器判据：检测"前身行为"的**高风险上下文**。
#
# ⚠️ 早期版本把「前身」当纯字面匹配，误报 3/4：
#   「4 臂**前身**尽力拖住机头」      ← 身体部位（前半身）
#   「变身对**原身**体影响的课题」    ← "原身体"是"原来/原本的身体"，
#                                        不是"原主"这个设定词
#   「原来二人赶到公园…」            ← "原来"是"事实上"的意思
#
# 收紧后的判据：只匹配**明确指代前一个人的词语**，不匹配可拆分/多义的词形。
# 「前身」「原身」单独出现不收；必须是「前身」+「做/是/的」等谓语语境，
# 或「原来的我/曾经的自己/身体原主」这类无歧义表述。

F7_PREV_MARK = re.compile(
    r"(身体原主|原来的?主人|上一任主人|以前的主人|"
    r"原来的我|曾经的自己|曾经的我|"
    r"前身(?:这|那|做|是|留|欠|答|曾|的?(?:事|选择|关系|身份|性格|人生|记忆|人际)|还))"
)
F7_OWNER = re.compile(r"原主")


def check_prev_owner_confusion(text, chapter_no=None):
    hits = []
    for ln_no, ln in _lines(text):
        for m in F7_PREV_MARK.finditer(ln):
            win = ln[max(0, m.start() - 10): m.end() + 30]
            if F7_OWNER.search(win):
                continue          # 已带「原主」，合规
            hits.append(Hit(
                rule_id="§23-7",
                rule_name="禁止原主与穿越者混淆",
                severity=R,
                line=ln_no,
                snippet=win.strip(),
                basis="总纲 §23：所有前身行为前加「原主」二字，"
                      "避免读者混淆主人公与前身性格。",
                advice="在此处补「原主」。凡是前身做过的事、有过的关系、欠下的人情，"
                       "一律写「原主欠的」「原主答应的」，不要用「我」。",
                confidence="mid",
                context=ln.strip(),
            ))
            break
    return hits


# ================================================================== 禁则 8
# 禁止日常加载废稿目录
#
# 原文：仅在流程需要时主动查阅，减少噪声。
# 机器判据：这是**流程性禁则**，只能在文本里检测"引用废稿"的痕迹。

F8_DRAFT = re.compile(r"(废稿|废案|旧稿|弃稿|备用稿|草稿目录|draft/)")


def check_no_draft_load(text, chapter_no=None):
    hits = []
    for ln_no, ln in _lines(text):
        for m in F8_DRAFT.finditer(ln):
            hits.append(Hit(
                rule_id="§23-8",
                rule_name="禁止日常加载废稿目录",
                severity=R,
                line=ln_no,
                snippet=m.group(0),
                basis="总纲 §23：废稿目录仅在流程需要时主动查阅，日常不得加载，减少噪声。",
                advice="正文里不应出现对废稿的引用。若这是创作笔记而非正文，"
                       "说明本文件被误判为正文——请检查 ce review 的输入路径。",
                confidence="high",
                context=ln.strip(),
            ))
            break
    return hits


CHECKS = [
    check_not_a_but_b,
    check_info_frontload,
    check_narrator_summary,
    check_label_over_image,
    check_crowd_opening,
    check_slogan_ending,
    check_prev_owner_confusion,
    check_no_draft_load,
]
