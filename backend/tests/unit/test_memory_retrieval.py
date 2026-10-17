"""Picking conversation summaries without embeddings (ADR 0052 §4)."""

from datetime import UTC, datetime, timedelta

from app.memory.retrieval import Candidate, bm25, overlap, pick, tokens

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def episode(key: str, text: str, *, days_ago: float = 0, title: str = "") -> Candidate[str]:
    return Candidate(key, text, title, NOW - timedelta(days=days_ago))


def test_tokens_split_english_words_and_chinese_pairs() -> None:
    assert tokens("Practised MUST and don't-have-to, 2 times") == [
        "practised",
        "must",
        "and",
        "don't",
        "have",
        "to",
        "2",
        "times",
    ]
    assert tokens("练习主语加动词") == ["练习", "习主", "主语", "语加", "加动", "动词"]
    assert tokens("读 SpaceX 新闻") == ["spacex", "读", "新闻"]


def test_bm25_scores_shared_words_and_favours_rare_ones() -> None:
    docs = [tokens("article about rockets"), tokens("article about cats"), tokens("cats")]
    rockets, cats, only_cats = bm25(tokens("rockets"), docs)
    assert rockets > 0 and cats == 0 and only_cats == 0
    # "article" is in two docs, "rockets" in one: the rarer word counts more.
    by_article = bm25(tokens("article"), docs)[0]
    assert rockets > by_article > 0
    assert bm25(tokens("anything"), []) == []


def test_pick_ranks_by_the_query_then_fills_with_the_newest() -> None:
    episodes = [
        episode("must", "练习 must 和 have to 表示必须", days_ago=16),
        episode("news", "读了一篇关于 SpaceX 火箭发射的新闻", days_ago=2),
        episode("book", "选了 Oxford 3000 词书, 标记认识的词", days_ago=3),
        episode("quiz", "出题测试主语加动词, 测试未完成", days_ago=1),
    ]

    assert pick("我上次读的那篇火箭新闻", episodes, 2, now=NOW) == ["news", "quiz"]
    # Nothing in common with the query: the newest.
    assert pick("hello", episodes, 2, now=NOW) == ["quiz", "news"]
    assert pick("", episodes, 2, now=NOW) == ["quiz", "news"]


def test_the_title_counts_and_recency_breaks_close_scores() -> None:
    episodes = [
        episode("old", "Practised articles.", days_ago=30, title="Articles"),
        episode("new", "Practised articles.", days_ago=1),
        episode("other", "Small talk about the weekend.", days_ago=0),
    ]
    # Same text: the title puts the old one ahead.
    assert pick("articles", episodes, 1, now=NOW) == ["old"]
    # Without titles, the newer one wins the tie.
    plain = [Candidate(e.key, e.text, "", e.updated_at) for e in episodes]
    assert pick("articles", plain, 1, now=NOW) == ["new"]


def test_repeats_are_left_out_wherever_they_come_from() -> None:
    episodes = [
        episode("a", "学习者要求出题测试主语加动词, 测试尚未完成", days_ago=0.1),
        episode("b", "学习者要求出题测试主语加动词, 测试尚未完成, 待跟进", days_ago=0.5),
        episode("c", "学习者要求出题测试自己的主语加动词, 测试尚未完成", days_ago=1),
        episode("d", "练习 must 和 have to", days_ago=10),
        episode("e", "读了 SpaceX 新闻", days_ago=12),
    ]

    assert pick("", episodes, 3, now=NOW) == ["a", "d", "e"]
    assert pick("主语", episodes, 3, now=NOW) == ["a", "d", "e"]
    # Nearest by embedding first, repeats still left out.
    assert pick("x", episodes, 3, now=NOW, first=["b", "c", "e"]) == ["b", "e", "d"]
    # Fewer than the limit when that's all there is.
    assert pick("", episodes[:3], 3, now=NOW) == ["a"]


def test_overlap() -> None:
    assert overlap({"a", "b"}, {"a", "b"}) == 1.0
    assert overlap({"a", "b"}, {"c"}) == 0.0
    assert overlap(set(), set()) == 1.0
