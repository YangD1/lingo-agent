"""Feed parsing, HTML cleaning and the source rules (task 41.2; Q41a-d)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.news.clean import html_to_text
from app.services.news.fetch import FeedFetchError
from app.services.news.parse import ParsedFeed, parse_feed
from app.services.news.rules import Kept, Skipped, judge

FEEDS = Path(__file__).parent.parent / "fixtures" / "feeds"
NOW = datetime(2026, 10, 7, 15, tzinfo=UTC)


def load(name: str) -> ParsedFeed:
    return parse_feed((FEEDS / name).read_bytes(), now=NOW)


def kept(result: Kept | Skipped) -> Kept:
    assert isinstance(result, Kept), result
    return result


# --- cleaning ------------------------------------------------------------------------


def test_cleaning_keeps_prose_and_drops_furniture() -> None:
    html = (
        "<nav><a href='/'>Home</a></nav><h2>Title</h2><p>One <b>bold</b> line.<br>Two</p>"
        "<figure><img src='x'/><figcaption>Photo CC BY-NC</figcaption></figure>"
        "<ul><li>first</li><li>second</li></ul><script>alert(1)</script>"
        "<p><a href='/a'>Only a link</a></p><p>Text with <a href='/b'>a link</a> inside.</p>"
    )
    assert html_to_text(html).split("\n\n") == [
        "Title",
        "One bold line.",
        "Two",
        "first",
        "second",
        "Text with a link inside.",
    ]


def test_cleaning_survives_broken_markup() -> None:
    html = "<p>Open <em>never closed<p>Next</div></span><li>item"
    assert html_to_text(html).split("\n\n") == ["Open never closed", "Next", "item"]


def test_cleaning_drops_by_class_and_repeats() -> None:
    html = (
        "<div class='wp-caption'><p class='wp-caption-text'>caption</p></div>"
        "<p>Same.</p><p>Same.</p><div class='x-intro'><p>intro</p></div>"
    )
    assert html_to_text(html) == "Same.\n\nintro"
    assert html_to_text(html, skip_class_words=("intro",)) == "Same."


# --- parsing -------------------------------------------------------------------------


def test_parse_rss_entries() -> None:
    feed = load("global_voices.xml")
    assert (feed.title, feed.site_url) == ("Global Voices", "https://globalvoices.org")
    entry = feed.entries[0]
    assert entry.guid == "https://globalvoices.org/?p=101"
    assert entry.author == "Global Voices Central & Eastern Europe"
    assert entry.published_at == datetime(2026, 10, 6, 8, 5, 24, tzinfo=UTC)
    assert entry.tags == ("Arts & Culture", "Language")


def test_parse_atom_with_html_title_and_content() -> None:
    feed = load("atom.xml")
    (entry,) = feed.entries
    assert entry.title == "Learning English with songs"
    assert entry.author == "Pat Blogger"
    assert entry.tags == ("learning",)
    # Full content wins over the summary; scripts never survive.
    assert html_to_text(entry.html) == (
        "Songs repeat words, and repetition helps memory.\n\nSing along every day."
    )


def test_parse_skips_entries_without_a_link_and_clamps_future_dates() -> None:
    feed = load("summary_only.xml")
    assert [e.url for e in feed.entries] == [
        "https://daily.example/library",
        "https://daily.example/future",
    ]
    assert feed.entries[0].title == "Pretend city opens a new library & park"
    assert feed.entries[1].published_at == NOW
    # No guid: the link stands in.
    assert feed.entries[1].guid == "https://daily.example/future"


def test_parse_rejects_what_is_not_a_feed() -> None:
    with pytest.raises(FeedFetchError) as caught:
        load("not_a_feed.html")
    assert caught.value.code == "not_a_feed"


# --- rules ---------------------------------------------------------------------------


def test_nasa_keeps_articles_and_skips_apod_and_notices() -> None:
    apod, notice, article = load("nasa.xml").entries
    assert judge(apod, source="nasa", feed_license="public_domain") == Skipped("apod")
    assert judge(notice, source="nasa", feed_license="public_domain") == Skipped("too_short")

    result = kept(judge(article, source="nasa", feed_license="public_domain"))
    paragraphs = result.body.split("\n\n")
    # The leaked headline, reading time and repeated title are gone; so is the tail.
    assert paragraphs[0].startswith("A thin layer of frozen seawater")
    assert "Thinner Ice" in paragraphs
    assert "Satellites have watched the ice since the late seventies." in paragraphs
    assert paragraphs[-1].startswith("The maps in this story")
    for gone in ("Another Story", "min read", "Image credit", "2026-067", "Jane Doe", "Related"):
        assert gone not in result.body
    assert result.license == "public_domain"
    assert not result.summary_only
    assert result.word_count >= 250


def test_global_voices_skips_partner_stories_only() -> None:
    own, partner, partner_by_story = load("global_voices.xml").entries
    result = kept(judge(own, source="global_voices", feed_license="cc_by"))
    # Image captions name other licenses; they are dropped, not read as the article's.
    assert "CC BY-NC-ND" not in result.body
    assert "Originally published on" not in result.body
    assert result.body.startswith("A small station finds new listeners")
    assert result.license == "cc_by"

    assert judge(partner, source="global_voices", feed_license="cc_by") == Skipped("republished")
    assert judge(partner_by_story, source="global_voices", feed_license="cc_by") == Skipped(
        "republished"
    )


def test_own_feeds_keep_teasers_as_summary_only() -> None:
    library, future = load("summary_only.xml").entries
    result = kept(judge(library, source=None, feed_license="unknown"))
    assert result.summary_only
    assert result.body == "The new library has a garden on the roof."  # "Read more" link dropped
    assert result.license == "unknown"
    assert kept(judge(future, source=None, feed_license="unknown")).body == "Dated far ahead."


def test_a_builtin_teaser_is_skipped() -> None:
    (entry,) = load("atom.xml").entries
    assert judge(entry, source="global_voices", feed_license="cc_by") == Skipped("too_short")
