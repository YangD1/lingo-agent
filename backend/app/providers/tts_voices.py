# ruff: noqa: RUF001 - the vendor's voice notes are Chinese, punctuation included
"""Voices a read-aloud model offers, for picking one in settings (task 64.2b, Q64q).

Built so a learner can pick later too (task 66): each option says who the voice is
(name, gender, accent) and which of the app's languages it suits; the route's `voices`
still store only the id. Models not listed here offer nothing: their voice is typed in
(or, for Azure, picked from the connection's model list).
"""

from dataclasses import dataclass
from typing import Literal

from app.providers.config import ResolvedModel
from app.providers.tts import (
    QWEN_AUDIO_VOICES,
    Language,
    is_qwen_audio,
    is_qwen_tts,
)

type Gender = Literal["female", "male"]

ENGLISH: tuple[Language, ...] = ("en-US", "en-GB")


@dataclass(frozen=True)
class VoiceOption:
    id: str  # what the vendor takes: a name, or for qwen-audio a description
    name: str  # what the vendor calls it, for people
    gender: Gender | None  # None: the vendor doesn't say
    languages: tuple[Language, ...]  # the app's languages it reads well
    accent: str | None = None  # e.g. "en-US", when the vendor names one
    note: str = ""  # the vendor's own description, in Chinese


def _flash(
    id: str,
    name: str,
    gender: Gender,
    note: str,
    *,
    mandarin: bool = True,
    accent: str | None = None,
) -> VoiceOption:
    # Every voice reads English; dialect voices read Chinese in their dialect, which a
    # learner of Mandarin shouldn't be taught by.
    languages = (*ENGLISH, "zh-CN") if mandarin else ENGLISH
    return VoiceOption(id, name, gender, languages, accent, note)


# qwen3-tts-flash's non-realtime voices (Model Studio's Qwen-TTS voice list, 2026-10-12;
# notes shortened from it). None is British.
QWEN_TTS_FLASH: tuple[VoiceOption, ...] = (
    _flash("Cherry", "芊悦", "female", "阳光积极、亲切自然的小姐姐"),
    _flash("Serena", "苏瑶", "female", "温柔小姐姐"),
    _flash("Ethan", "晨煦", "male", "阳光、温暖、活力，略带北方口音"),
    _flash("Chelsie", "千雪", "female", "二次元虚拟女友"),
    _flash("Momo", "茉兔", "female", "撒娇搞怪，逗你开心"),
    _flash("Vivian", "十三", "female", "拽拽的、可爱的小暴躁"),
    _flash("Moon", "月白", "male", "率性帅气"),
    _flash("Maia", "四月", "female", "知性与温柔的碰撞"),
    _flash("Kai", "凯", "male", "耳朵的一场 SPA"),
    _flash("Nofish", "不吃鱼", "male", "不会翘舌音的设计师"),
    _flash("Bella", "萌宝", "female", "小萝莉"),
    _flash("Jennifer", "詹妮弗", "female", "品牌级、电影质感的美语女声", accent="en-US"),
    _flash("Ryan", "甜茶", "male", "节奏拉满，戏感炸裂"),
    _flash("Katerina", "卡捷琳娜", "female", "御姐，韵律回味十足"),
    _flash("Aiden", "艾登", "male", "精通厨艺的美语大男孩", accent="en-US"),
    _flash("Eldric Sage", "沧明子", "male", "沉稳睿智的老者"),
    _flash("Mia", "乖小妹", "female", "温顺乖巧"),
    _flash("Mochi", "沙小弥", "male", "聪明伶俐的小大人"),
    _flash("Bellona", "燕铮莺", "female", "声音洪亮，吐字清晰"),
    _flash("Vincent", "田叔", "male", "沙哑烟嗓"),
    _flash("Bunny", "萌小姬", "female", "萌属性爆棚的小萝莉"),
    _flash("Neil", "阿闻", "male", "平直、字正腔圆的新闻主持人"),
    _flash("Elias", "墨讲师", "female", "严谨、会讲故事的讲师"),
    _flash("Arthur", "徐大爷", "male", "讲乡村奇闻的老人"),
    _flash("Nini", "邻家妹妹", "female", "又软又黏的邻家妹妹"),
    _flash("Seren", "小婉", "female", "温和舒缓，助眠"),
    _flash("Pip", "顽屁小孩", "male", "调皮捣蛋的小孩"),
    _flash("Stella", "少女阿月", "female", "甜美迷糊的少女"),
    _flash("Bodega", "博德加", "male", "热情的西班牙大叔"),
    _flash("Sonrisa", "索尼莎", "female", "热情开朗的拉美大姐"),
    _flash("Alek", "阿列克", "male", "外冷内热的战斗民族"),
    _flash("Dolce", "多尔切", "male", "慵懒的意大利大叔"),
    _flash("Sohee", "素熙", "female", "温柔的韩国欧尼"),
    _flash("Ono Anna", "小野杏", "female", "鬼灵精怪的青梅竹马"),
    _flash("Lenn", "莱恩", "male", "理性、暗藏叛逆的德国青年"),
    _flash("Emilien", "埃米尔安", "male", "浪漫的法国大哥哥"),
    _flash("Andre", "安德雷", "male", "声音磁性、自然沉稳"),
    _flash("Radio Gol", "拉迪奥·戈尔", "male", "足球解说"),
    _flash("Jada", "上海-阿珍", "female", "风风火火的沪上阿姐（上海话）", mandarin=False),
    _flash("Dylan", "北京-晓东", "male", "北京胡同少年（北京话）", mandarin=False),
    _flash("Li", "南京-老李", "male", "耐心的瑜伽老师（南京话）", mandarin=False),
    _flash("Marcus", "陕西-秦川", "male", "面宽话短的老陕（陕西话）", mandarin=False),
    _flash("Roy", "闽南-阿杰", "male", "诙谐直爽的台湾哥仔（闽南语）", mandarin=False),
    _flash("Peter", "天津-李彼得", "male", "天津相声捧哏（天津话）", mandarin=False),
    _flash("Sunny", "四川-晴儿", "female", "甜到心里的川妹子（四川话）", mandarin=False),
    _flash("Eric", "四川-程川", "male", "跳脱的成都男子（四川话）", mandarin=False),
    _flash("Rocky", "粤语-阿强", "male", "幽默风趣的阿强（粤语）", mandarin=False),
    _flash("Kiki", "粤语-阿清", "female", "甜美的港妹闺蜜（粤语）", mandarin=False),
)

# qwen-audio takes any description; these are starting points (Q64i), the defaults first.
QWEN_AUDIO: tuple[VoiceOption, ...] = (
    VoiceOption(QWEN_AUDIO_VOICES["en-US"], "美式女老师", "female", ("en-US",), "en-US"),
    VoiceOption(QWEN_AUDIO_VOICES["en-GB"], "英式女老师", "female", ("en-GB",), "en-GB"),
    VoiceOption(QWEN_AUDIO_VOICES["zh-CN"], "普通话女老师", "female", ("zh-CN",), "zh-CN"),
    VoiceOption(
        "A calm, friendly male American English teacher", "美式男老师", "male", ("en-US",), "en-US"
    ),
    VoiceOption(
        "A calm, friendly male British English teacher", "英式男老师", "male", ("en-GB",), "en-GB"
    ),
    VoiceOption(
        "A calm, friendly male Mandarin Chinese teacher",
        "普通话男老师",
        "male",
        ("zh-CN",),
        "zh-CN",
    ),
)


def voice_options(model: ResolvedModel) -> tuple[VoiceOption, ...]:
    if is_qwen_audio(model):
        return QWEN_AUDIO
    if is_qwen_tts(model):
        return QWEN_TTS_FLASH
    return ()
