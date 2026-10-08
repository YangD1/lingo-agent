from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Word
from app.services.reading.glossary import build, load_entries


async def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            Word(word="go", translation="去", frq=50, exchange="p:went/d:gone/i:going/3:goes"),
            Word(word="went", translation="go 的过去式", exchange="0:go/1:p"),
            Word(word="comet", translation="彗星", frq=12000, exchange="s:comets"),
            Word(word="Comet", translation="彗星 专名", frq=None),
            Word(word="orbit", translation="轨道", bnc=7000, frq=9000, exchange="i:orbiting"),
            Word(word="rare", translation="稀有", exchange="r:rarer"),
        ]
    )
    await session.commit()


async def test_load_entries_resolves_case_and_inflections(db_session: AsyncSession) -> None:
    await _seed(db_session)
    entries = await load_entries(db_session, ["went", "Comets", "comet", "orbiting", "nope"])
    # "went" has its own entry, so the exact match wins over the lemma.
    assert entries["went"].word == "went"
    assert entries["comets"].word == "comet"
    # Two entries spell "comet" in some case: the ranked one wins.
    assert (entries["comet"].word, entries["comet"].rank) == ("comet", 12000)
    assert (entries["orbiting"].word, entries["orbiting"].rank) == ("orbit", 7000)
    assert "nope" not in entries


async def test_build_uses_the_lexicon(db_session: AsyncSession) -> None:
    await _seed(db_session)
    glossary = await build(db_session, ["Comets go rarer ways, orbiting far."], cut=8000, limit=10)
    assert [w["word"] for w in glossary.words] == ["comet", "rare"]
    # Lexicon words: comets go rarer orbiting = 4; past the cut: comets rarer = 2.
    assert glossary.above_level_share == 0.5
