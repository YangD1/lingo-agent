"""Reading senses out of Simple English Wiktionary wikitext (ADR 0062)."""

import io

from app.services.vocab.simplewiktionary import Sense, parse_page, read_pages

RUN = """{{BE850}}
{{BNC1HW}}

=== Pronunciation ===
* {{IPA|/rʌn/}}

== Verb ==
{{verb2|run|runs|ran|run|running}}
[[File:Woman running.jpg|225px|thumb|A woman '''running''' on a [[beach]]]]
# If you '''run''', you go [[quickly]], with [[foot|feet]] up. {{syn|hurry}} {{ant|stroll|walk}}
#: ''I must '''run'''.''
#: ''I like to '''run''' in the afternoon.''
#* 1850, someone, ''A Book'': a quotation that is not an example
# {{transitive}} If you '''run''' a place, you [[manage]] it.<ref>A source.</ref>
#: ''He '''ran''' the [[hotel]].''
## A sub-sense, not kept.

=== Related words ===
* [[runner]]

== Noun 2 ==
{{noun}}
# {{context|baseball|sports}} A '''run''' in baseball is when a batter touches home plate.
# {{plural of|runs}}
"""


def test_senses_by_part_of_speech_with_examples_labels_and_synonyms() -> None:
    assert parse_page("run", RUN) == [
        Sense(
            pos="verb",
            gloss="If you run, you go quickly, with feet up.",
            examples=("I must run.", "I like to run in the afternoon."),
            synonyms=("hurry",),
            antonyms=("stroll", "walk"),
        ),
        Sense(
            pos="verb",
            gloss="If you run a place, you manage it.",
            labels=("transitive",),
            examples=("He ran the hotel.",),
        ),
        Sense(
            pos="noun",
            gloss="A run in baseball is when a batter touches home plate.",
            labels=("baseball", "sports"),
        ),
    ]


def test_templates_turned_into_text_or_labels() -> None:
    page = """== Noun ==
# {{cu noun}} or {{singular}} '''Relief''' is the good feeling when something bad is over.
# {{lc|Mutual}}; shared by many {{r|countr|ies}}, like {{w|Wikipedia|this}}.
# {{colorbox|#000}} A colour.
"""
    relief, mutual, colour = parse_page("relief", page)
    assert relief.gloss == "Relief is the good feeling when something bad is over."
    assert relief.labels == ("countable", "uncountable", "singular")
    assert mutual.gloss == "Mutual; shared by many countries, like this."
    assert colour.gloss == "A colour." and colour.labels == ()


def test_senses_that_only_point_elsewhere_or_are_broken_are_dropped() -> None:
    page = """== Verb ==
# {{past tense of|run}}
# {{third person|run}}
# The formula is x\\ \\mathrm{kg}.
# If x has a reliance on y, x needs y. {{ant|independence}
#
== Adjective ==
# Fast.
"""
    assert parse_page("ran", page) == [Sense(pos="adjective", gloss="Fast.")]


def test_only_part_of_speech_sections_and_proper_nouns_for_capitalised_titles() -> None:
    page = """== Proper noun ==
# A large country in Asia.
== Usage notes ==
# Not a sense.
== Noun ==
# Porcelain.
"""
    assert [s.gloss for s in parse_page("china", page)] == ["Porcelain."]
    assert [s.pos for s in parse_page("China", page)] == ["proper noun", "noun"]


def test_examples_before_any_sense_or_in_quotes_and_repeated() -> None:
    page = """== Noun ==
#: ''A stray example.''
# A thing.
#: "The thing is here."
#: ''The thing is here.''
#:: A nested note, not kept.
"""
    assert parse_page("thing", page) == [
        Sense(pos="noun", gloss="A thing.", examples=("The thing is here.",))
    ]


DUMP = b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page><title>go</title><ns>0</ns><revision><text>== Verb ==
# To move.</text></revision></page>
  <page><title>Template:noun</title><ns>10</ns><revision><text>x</text></revision></page>
  <page><title>empty</title><ns>0</ns><revision><text /></revision></page>
</mediawiki>"""


def test_read_pages_keeps_articles_only() -> None:
    assert list(read_pages(io.BytesIO(DUMP))) == [("go", "== Verb ==\n# To move."), ("empty", "")]
