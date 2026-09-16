"""LLM 结构化提取（OpenAI 兼容接口占位实现 + 无 key 启发式降级）。

真实调用：向 chat 模型请求严格 JSON（response_format=json_object），
随后用 pydantic 校验并返回 :class:`ChapterExtraction`。
离线/无 key 降级：--mock 或未配置 OPENAI_API_KEY 时用启发式规则产出可用结果，
便于全流程（无真实 LLM）联调跑通。

⚠️ 本模块是"示例 LLM 调用占位符"：结构已完整，密钥与模型配置来自 .env。
"""
from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from .config import get_settings
from .schemas import ChapterExtraction, ChapterEvent, CharacterState, PlotThread, WorldSetting

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一名资深小说内容结构化引擎。给定章节原文，输出严格 JSON，字段含义：
{
  "chapter_number": 章节号(>=1, 整数),
  "title": 章节标题,
  "summary": 120~200 字中文摘要（近程记忆用，只讲本章发生的事，不剧透后续）,
  "characters": [{"name": 角色名, "current_state": {本角色本章结束时的状态快照},
                  "state_change": "本章该角色的状态变化一句话"}],
  "world_settings": [{"category": 地理|历史|文化|力量体系|组织 等, "key": 设定键名,
                      "value": 设定值, "confidence_score": 0~1 置信度}],
  "events": [{"type": combat|dialogue|travel|discovery|conflict|plot_twist|emotion|relationship|milestone|other,
              "description": "事件一句话", "related_characters": [{"name": 角色名, "role": 角色} ]}],
  "plot_threads": [{"title": 伏笔/剧情线标题, "status": open|progressing|resolved|abandoned,
                    "priority": 整数, "events": [{"event_index": 本章事件下标, "relation": 铺垫|推进|转折}]}]
}
只输出 JSON 本身，不要解释、不要 markdown 代码块。"""


class LLMClientError(RuntimeError):
    """LLM 调用失败（网络/鉴权/非 JSON）。"""


def _truncate_content(text: str, budget_chars: int = 12000) -> str:
    """占位截断：真实实现应基于 tiktoken 按 MAX_CONTEXT_TOKENS 切分。"""
    return text[:budget_chars]


def _llm_available() -> bool:
    s = get_settings()
    return bool(s.OPENAI_API_KEY) and s.OPENAI_BASE_URL != ""


def _normalize_llm_json(raw: str) -> str:
    """剥离 markdown 代码块围栏后返回干净 JSON 文本。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        return fence.group(1).strip()
    return text


async def extract_chapter(
    chapter_number: int, title: str, content: str, *, mock: bool = False
) -> ChapterExtraction:
    """对单章做结构化提取。

    :param mock: True 时强制走启发式降级（不调用 LLM）。
    :raises LLMClientError: LLM 调用层失败（网络/鉴权/响应非 JSON）。
    :raises ValidationError: LLM 输出不满足 Pydantic 模型（调用方捕获并写 etl_errors.log）。
    """
    if mock or not _llm_available():
        return _mock_extraction(chapter_number, title, content)

    # ---- 真实 LLM 调用（OpenAI 兼容占位实现）----
    try:
        from openai import AsyncOpenAI

        s = get_settings()
        client = AsyncOpenAI(api_key=s.OPENAI_API_KEY, base_url=s.OPENAI_BASE_URL)
        resp = await client.chat.completions.create(
            model=s.EXTRACT_MODEL,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"章节号: {chapter_number}\n标题: {title}\n\n"
                        f"正文:\n{_truncate_content(content)}"
                    ),
                },
            ],
        )
        raw = resp.choices[0].message.content or ""
    except Exception as exc:  # 网络/鉴权等
        raise LLMClientError(f"LLM 调用失败: {exc}") from exc

    json_text = _normalize_llm_json(raw)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise LLMClientError(f"LLM 返回非 JSON: {exc}") from exc

    payload["chapter_number"] = chapter_number
    return ChapterExtraction.model_validate(payload)


# 常见单姓（节选百家姓高频段）+ 复姓，用于离线角色名启发式
_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和"
    "穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮"
    "蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支"
    "柯管卢莫房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁荀羊"
    "甄曲封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊"
    "宫宁仇栾暴甘厉戎祖武符刘景詹束龙叶幸司韶黎薄印宿白怀蒲从鄂索咸赖卓"
    "蔺屠蒙池乔阴胥能苍双闻党翟谭贡劳姬申扶堵冉宰郦雍桑桂濮牛寿边扈燕冀"
    "浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿"
    "满弘匡国文寇广禄阙欧殳沃利蔚越隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾"
    "毋沙养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
_SURNAME_RE = re.compile(f"([{_SURNAMES}])([\u4e00-\u9fa5])")
# 引号/书名号内专名（排除句读与跨行）
_QUOTED_RE = re.compile(r"[「『《\"“]([^「『》」\"”\n，。！？；：、]{2,8})[》」』\"”]")
# 事件类型确定性轮换表（按正文句 hash 取模，保证幂等）
_MOCK_EVENT_TYPES = (
    "dialogue", "travel", "discovery", "conflict",
    "plot_twist", "emotion", "relationship", "milestone",
)


def _mock_extraction(
    chapter_number: int, title: str, content: str
) -> ChapterExtraction:
    """离线启发式降级：产出**结构完整、确定性**的演示数据供全链路联调。

    真实语义提取依赖 LLM（``mock=False`` 且有 key 时）；本函数只为让
    ETL/入库/wb_tools 在不联网环境下也能跑通端到端：
    - summary 取正文首段；
    - 角色名按「常见姓氏 + 1~2 字」在正文中重复出现 >=2 次的词粗提取；
    - 事件取含角色名的正文句子（最多 3 句），类型按句子确定性轮换；
    - 剧情线以「第 N 章线索」闭环引用本章事件；世界设定抓引号内专名。
    """
    plain = re.sub(r"[\s#*`>\-]+", " ", content).strip()
    summary = plain[:120] + ("…" if len(plain) > 120 else "")
    if not summary:
        summary = f"第{chapter_number}章 {title}"

    # 1) 角色：姓氏+1 字 出现 >=2 次的候选，最多 4 人；滤除明显非人名词尾
    _NON_NAME_TAIL = set("巷尸阁楼门街墙驿令爷官军兵火江河水山石父仆")
    counter: dict[str, int] = {}
    for m in _SURNAME_RE.finditer(content):
        word = m.group(0)
        if word[1] in _NON_NAME_TAIL:
            continue
        counter[word] = counter.get(word, 0) + 1
    names = [w for w, c in counter.items() if c >= 2][:4]

    # 2) 事件：含角色名的句子 → description；related_characters 关联句中出现角色
    sentences = [s.strip() for s in re.split(r"[。！？!?；;]", content) if len(s.strip()) >= 8]
    events: list[ChapterEvent] = []
    ev_sent: list[str] = []
    for sent in sentences:
        in_names = [n for n in names if n in sent]
        if not in_names:
            continue
        idx = sum(len(re.findall(n, s, re.IGNORECASE)) for s in ev_sent for n in names)
        etype = _MOCK_EVENT_TYPES[idx % len(_MOCK_EVENT_TYPES)]
        events.append(
            ChapterEvent(
                type=etype,
                description=sent[:60],
                related_characters=[{"name": n, "role": ""} for n in in_names[:2]],
            )
        )
        ev_sent.append(sent)
        if len(events) >= 3:
            break

    # 3) 剧情线：以「第 N 章线索」闭环引用本章全部事件（保证不产生悬空引用）
    threads = []
    if events:
        threads.append(
            PlotThread(
                title=f"第{chapter_number}章线索",
                status="open",
                priority=1,
                events=[
                    {"event_index": i, "relation": "推进"}
                    for i in range(len(events))
                ],
            )
        )

    # 4) 世界设定：抓引号/书名号内的专名（如「听风阁」），最多 2 条
    world_settings = []
    quoted = re.findall(_QUOTED_RE, content)
    for q in dict.fromkeys(quoted):  # 去重保序
        world_settings.append(
            WorldSetting(
                category="地理",
                key=q,
                value=q + "（离线演示设定）",
                confidence_score=0.5,
            )
        )
        if len(world_settings) >= 2:
            break

    extraction = ChapterExtraction(
        chapter_number=chapter_number,
        title=title,
        summary=summary,
        characters=[
            CharacterState(name=n, current_state={}, state_change="")
            for n in names
        ],
        events=events,
        world_settings=world_settings,
        plot_threads=threads,
    )
    return extraction


def fallback_plot_threads(threads: list[PlotThread]) -> None:
    """占位：为无 events 引用的线程补 relation 描述（可扩展）。"""
    return None
