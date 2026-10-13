# ruff: noqa: RUF001, E501 - demo prose in Chinese and English, one line each
"""What the demo learner said and wrote, and what a model would have written back
(task 72.3). Only text: the numbers come from the engines in `seed.py`.

Each explanation is given in both languages; `Text` picks one by the learner's
explanation language.
"""

from dataclasses import dataclass
from typing import Literal

from app.adaptive.exercise.formats import Format

type Lang = Literal["zh", "en"]


@dataclass(frozen=True, slots=True)
class Text:
    zh: str
    en: str

    def __call__(self, lang: Lang) -> str:
        return self.zh if lang == "zh" else self.en


# The weak point, its confusable neighbour, one KC on its way to learned and one to
# be learned by the end. All are in `adaptive/kc/grammar.yaml`.
WEAK = "g.present_perfect_vs_past_simple"
NEIGHBOUR = "g.present_perfect_experience"
CONSOLIDATING = "g.comparatives"
LEARNED = "g.going_to_future"

PROFILE = {
    "native_language": "zh",
    "occupation": Text("产品经理", "product manager"),
    "goal": Text(
        "下半年出国参加行业会议，能用英语聊天和做简短发言",
        "Chat and give a short talk in English at a conference abroad later this year",
    ),
    "interests": [Text("电影", "films"), Text("徒步", "hiking"), Text("咖啡", "coffee")],
    "daily_minutes": 20,
}

MEMORIES: tuple[Text, ...] = (
    Text(
        "在一家做旅行 App 的公司当产品经理",
        "Works as a product manager at a company that makes a travel app",
    ),
    Text(
        "下半年要去新加坡参加行业会议，想能用英语聊天",
        "Is going to an industry conference in Singapore later this year and wants to chat in English",
    ),
    Text("周末常去杭州附近徒步", "Often goes hiking near Hangzhou at the weekend"),
    Text(
        "喜欢老电影，最近在看《罗马假日》",
        "Likes old films and is watching Roman Holiday at the moment",
    ),
    Text(
        "说过去的经历时常把现在完成时和一般过去时用混",
        "Often mixes up the present perfect and the past simple when telling past experiences",
    ),
    Text(
        "希望讲解多用中文，例句用英文",
        "Wants explanations mostly in Chinese and examples in English",
    ),
)

# Chat turns with a mistake on the weak point, newest last: (days ago, original, fix).
CHAT_MISTAKES: tuple[tuple[int, str, str], ...] = (
    (9, "I have seen that film last year", "I saw that film last year"),
    (6, "We have gone hiking yesterday", "We went hiking yesterday"),
    (4, "I have finished the report two days ago", "I finished the report two days ago"),
    (2, "Did you ever try durian?", "Have you ever tried durian?"),
)

# One finished practice set per entry: (days ago, items). An item is
# (kc, format, content, answer, response); the responses make a mix of right and wrong.
# Wrong answers are on formats the code grades by itself (choice4, cloze, find_fix).
EXPLAIN_PP = Text(
    "有明确的过去时间（yesterday、last year、ago）时用一般过去时。",
    "With a finished time in the past (yesterday, last year, ago), use the past simple.",
)
EXPLAIN_EVER = Text(
    "问“有没有过”某种经历、不说具体时间时，用现在完成时。",
    "To ask about experience at any time up to now, use the present perfect.",
)
EXPLAIN_COMP = Text(
    "单音节形容词比较级加 -er，多音节的用 more。",
    "Short adjectives take -er; longer ones take more.",
)
EXPLAIN_GOING = Text(
    "已经决定要做的事，用 be going to + 动词原形。",
    "For plans already decided, use be going to + the base form.",
)

type Item = tuple[str, Format, dict[str, object], dict[str, object], dict[str, object]]


def practice_sets(lang: Lang) -> tuple[tuple[int, tuple[Item, ...]], ...]:
    pp, ever, comp, going = (
        EXPLAIN_PP(lang),
        EXPLAIN_EVER(lang),
        EXPLAIN_COMP(lang),
        EXPLAIN_GOING(lang),
    )
    return (
        (
            8,
            (
                (
                    LEARNED,
                    "choice4",
                    {
                        "stem": "Look at those clouds. It ___ rain.",
                        "options": ["is going to", "goes to", "is go to", "going"],
                    },
                    {"correct": "is going to", "explanation": going},
                    {"choice": "is going to"},
                ),
                (
                    CONSOLIDATING,
                    "choice4",
                    {
                        "stem": "This café is ___ than the one near my office.",
                        "options": ["quieter", "more quiet", "quietest", "most quiet"],
                    },
                    {"correct": "quieter", "explanation": comp},
                    {"choice": "quieter"},
                ),
                (
                    WEAK,
                    "choice4",
                    {
                        "stem": "I ___ my keys yesterday.",
                        "options": ["lost", "have lost", "have losed", "was lose"],
                    },
                    {"correct": "lost", "explanation": pp},
                    {"choice": "have lost"},
                ),
                (
                    LEARNED,
                    "cloze",
                    {
                        "stem": "We ___ (visit) my aunt next weekend. We booked the train.",
                        "hint": "be going to",
                    },
                    {
                        "accepted": ["are going to visit", "'re going to visit"],
                        "explanation": going,
                    },
                    {"text": "are going to visit"},
                ),
            ),
        ),
        (
            3,
            (
                (
                    CONSOLIDATING,
                    "cloze",
                    {
                        "stem": "The second trail was much ___ (difficult) than the first.",
                        "hint": None,
                    },
                    {"accepted": ["more difficult"], "explanation": comp},
                    {"text": "more difficult"},
                ),
                (
                    WEAK,
                    "cloze",
                    {"stem": "She ___ (move) to Shanghai in 2019.", "hint": None},
                    {"accepted": ["moved"], "explanation": pp},
                    {"text": "has moved"},
                ),
                (
                    NEIGHBOUR,
                    "choice4",
                    {
                        "stem": "Have you ever ___ sushi?",
                        "options": ["eaten", "ate", "eat", "eating"],
                    },
                    {"correct": "eaten", "explanation": ever},
                    {"choice": "eaten"},
                ),
                (
                    LEARNED,
                    "transform",
                    {
                        "instruction": "Rewrite with be going to.",
                        "source": "I plan to learn to swim this summer.",
                    },
                    {
                        "accepted": [
                            "I am going to learn to swim this summer.",
                            "I'm going to learn to swim this summer.",
                        ],
                        "explanation": going,
                    },
                    {"text": "I'm going to learn to swim this summer."},
                ),
                (
                    WEAK,
                    "find_fix",
                    {
                        "segments": [
                            "Two years ago",
                            "I have worked",
                            "in a small",
                            "design studio.",
                        ]
                    },
                    {"wrong_segment": 1, "accepted": ["I worked"], "explanation": pp},
                    {"segment": 1, "fix": "I worked"},
                ),
            ),
        ),
    )


WRITING_DAYS_AGO = 5
WRITING_PROMPT = "Write about a trip you remember."
WRITING_TEXT = (
    "Last summer I have visited my grandmother in Hangzhou. We walked around the West Lake "
    "every evening and ate a lot of street food. The weather was more hotter than I "
    "expected, but I did not mind.\n\n"
    "I have never seen so many lotus flowers before. Next year I am going to take my "
    "sister with me, because she has never been there."
)


def writing_review(lang: Lang) -> dict[str, object]:
    """As `writing.review.Review` would parse it."""
    t = {
        "pp": EXPLAIN_PP(lang),
        "comp": Text(
            "hotter 已经是比较级，不要再加 more。", "Hotter is already a comparative; drop more."
        )(lang),
    }
    return {
        "sentences": [
            {
                "index": 0,
                "corrected": "Last summer I visited my grandmother in Hangzhou.",
                "mistakes": [
                    {
                        "kc_id": WEAK,
                        "error_type": "wrong_form",
                        "severity": "medium",
                        "original": "have visited",
                        "correction": "visited",
                        "explanation": t["pp"],
                    }
                ],
            },
            {
                "index": 2,
                "corrected": "The weather was hotter than I expected, but I did not mind.",
                "mistakes": [
                    {
                        "kc_id": CONSOLIDATING,
                        "error_type": "addition",
                        "severity": "low",
                        "original": "more hotter",
                        "correction": "hotter",
                        "explanation": t["comp"],
                    }
                ],
            },
        ],
        "scores": {
            "task": {
                "score": 4,
                "reason": Text(
                    "讲清楚了去哪、做了什么和感受。", "Says where, what and how it felt."
                )(lang),
            },
            "coherence": {
                "score": 4,
                "reason": Text(
                    "按时间顺序，两段分得清楚。", "In time order, two clear paragraphs."
                )(lang),
            },
            "vocabulary": {
                "score": 3,
                "reason": Text(
                    "用词准确，可以再多一些描写。", "Accurate words; more description would help."
                )(lang),
            },
            "grammar": {
                "score": 3,
                "reason": Text(
                    "时态大体对，有一处完成时用错。",
                    "Tenses mostly right, one present perfect misused.",
                )(lang),
            },
        },
        "summary": Text(
            "游记写得很生动，结尾用 has never been 很地道。注意有具体过去时间时用一般过去时。",
            "A lively trip story, and has never been at the end is natural. With a finished past time, use the past simple.",
        )(lang),
        "vocab_candidates": ["lotus"],
    }


READING_DAYS_AGO = 4
ARTICLE_TITLE = "Volunteers plant a million trees along an old railway"
ARTICLE_BODY = (
    "Volunteers in northern England have finished planting one million trees along a "
    "railway line that closed in the 1960s. The project started five years ago with a "
    "small group of local walkers.\n\n"
    "The new woodland links two national parks. Scientists say it gives birds and small "
    "animals a safe path between the parks, and it will store carbon for many decades.\n\n"
    "Schools joined the project in its second year. Each class looked after its own "
    "section of the line and recorded which plants and insects came back."
)
REWRITE_TITLE = "A million new trees on an old railway"
REWRITE = (
    "In the north of England, volunteers have planted one million trees. They planted "
    "them along an old railway line. Trains stopped using the line in the 1960s.",
    "The project began five years ago. At first, only a small group of local walkers "
    "worked on it. Later, schools joined. Each class took care of one part of the line.",
    "The new forest connects two national parks. Scientists say birds and small animals "
    "can now move safely between the parks. The trees will also store carbon for a long "
    "time.",
)
# (question, options with the right one first, evidence sentence); the demo answers
# the first two right and the last one wrong.
QUESTIONS: tuple[tuple[str, tuple[str, str, str, str], str], ...] = (
    (
        "Where did the volunteers plant the trees?",
        (
            "Along an old railway line",
            "Inside a city park",
            "Next to a new airport",
            "On a school field",
        ),
        "They planted them along an old railway line.",
    ),
    (
        "Who started the project?",
        (
            "A small group of local walkers",
            "A train company",
            "Scientists from a university",
            "The national parks",
        ),
        "At first, only a small group of local walkers worked on it.",
    ),
    (
        "What does the new forest do for animals?",
        (
            "It lets them move safely between two parks",
            "It gives them food in winter",
            "It keeps them away from the railway",
            "It protects them from scientists",
        ),
        "Scientists say birds and small animals can now move safely between the parks.",
    ),
)

SPEAKING_DAYS_AGO = 2
SPEAKING_SCENARIO = "self_intro"
# The learner's spoken turns, with their length in seconds.
SPEAKING_TURNS: tuple[tuple[str, float], ...] = (
    ("Hi, my name is Lin. I am a product manager in a travel app company.", 6.0),
    ("I have joined the company three years ago.", 4.0),
    ("In my free time I like hiking and watching old films.", 5.0),
    ("Last month I have climbed a mountain near Hangzhou with my friends.", 6.5),
    ("I want to speak English better because I will go to a conference in Singapore.", 7.0),
)


def speaking_summary(lang: Lang) -> dict[str, object]:
    """As `speaking.summary.SpeakingSummary` would parse it."""
    return {
        "went_well": [
            Text(
                "自我介绍清楚、自然，信息完整。",
                "A clear, natural introduction with all the key facts.",
            )(lang),
            Text("用 like + -ing 谈爱好很地道。", "Like + -ing for hobbies sounds natural.")(lang),
        ],
        "mistakes": [
            {
                "quote": "I have joined the company three years ago.",
                "correction": "I joined the company three years ago.",
                "explanation": EXPLAIN_PP(lang),
            },
            {
                "quote": "Last month I have climbed a mountain",
                "correction": "Last month I climbed a mountain",
                "explanation": EXPLAIN_PP(lang),
            },
        ],
        "more_natural": [
            {
                "quote": "I am a product manager in a travel app company.",
                "natural": "I'm a product manager at a travel app company.",
                "note": Text(
                    "说在某公司工作，介词多用 at。", "At is more usual for where you work."
                )(lang),
            }
        ],
        "next_expressions": [
            {
                "expression": "I've been with the company for three years.",
                "meaning": Text(
                    "我在这家公司三年了（比 joined ... ago 更常用）。",
                    "A natural way to say how long you have worked somewhere.",
                )(lang),
            },
            {
                "expression": "I'm really into hiking.",
                "meaning": Text("我特别喜欢徒步。", "A casual way to say you love something.")(
                    lang
                ),
            },
        ],
        "intelligibility": "mostly",
    }


DIAGNOSIS_DAYS_AGO = 1


def diagnosis(lang: Lang) -> dict[str, str]:
    return {
        "hypothesis": Text(
            "讲过去的经历时，习惯先想到“已经做过”，于是在有明确过去时间（ago、last、yesterday）的句子里也用了现在完成时。",
            "When telling past experiences, you reach for the present perfect even when the sentence has a finished time (ago, last, yesterday).",
        )(lang),
        "suggestion": Text(
            "先找句子里有没有具体的过去时间：有就用一般过去时；只问“有没有过”才用现在完成时。",
            "Look for a finished time first: if there is one, use the past simple; use the present perfect only for experience at any time.",
        )(lang),
    }
