"""Wrong meanings for listening cards (task 63, Q63c)."""

import random

from app.services.vocab.distractors import Gloss, gloss, pick


def test_gloss_takes_the_first_plain_sense_line() -> None:
    assert gloss("n. 殖民地, 移民队\n[医] 菌(集)落, 菌丛").text == "n. 殖民地, 移民队"
    # Field senses only when there is nothing else; the field tag is dropped.
    assert gloss("[计] 资源\n[经] 财力").text == "资源"
    # A few terms at most, full-width separators too.
    long = gloss("a. 宽广的\uff0c辽阔的\uff1b广大的, 显著的\nadv. 宽阔地")
    assert long.text == "a. 宽广的, 辽阔的, 广大的" and long.pos == "adj"
    assert gloss("vt. 限制").pos == gloss("vi. 散布").pos == "v"
    assert gloss("").text == ""


def test_long_glosses_are_cut() -> None:
    text = gloss("n. " + "很长很长很长很长的释义" * 2 + ", 二, 三").text
    assert len(text) <= 30 and text.endswith("…")


def test_pick_prefers_the_same_part_of_speech_and_avoids_shared_terms() -> None:
    answer = gloss("n. 界限, 限度")
    candidates = [
        gloss("v. 哀悼"),
        gloss("n. 风琴, 器官"),
        gloss("n. 主席"),
        gloss("n. 限度, 极限"),  # shares 限度 with the answer
        gloss("n. 器官"),  # shares 器官 with another pick
        gloss("n. 杰作"),
        gloss("adv. 自然地"),
    ]
    for seed in range(20):
        picked = pick(answer, candidates, random.Random(seed))
        # Nouns only, 限度 never, and not both of the two with 器官.
        assert len(picked) == 3 and {"n. 主席", "n. 杰作"} < set(picked)
        assert set(picked) - {"n. 主席", "n. 杰作"} < {"n. 风琴, 器官", "n. 器官"}


def test_pick_falls_back_to_other_parts_of_speech_and_may_come_up_short() -> None:
    answer = gloss("n. 界限")
    picked = pick(
        answer, [gloss("n. 主席"), gloss("v. 哀悼"), gloss("a. 多石的")], random.Random(1)
    )
    assert sorted(picked) == ["a. 多石的", "n. 主席", "v. 哀悼"]
    assert pick(answer, [gloss("n. 界限"), Gloss("", "", frozenset())], random.Random(1)) == []
