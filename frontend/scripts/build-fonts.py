"""Slice the selectable text fonts into woff2 pieces with unicode-range (ADR 0059, 0060).

The browser only downloads the pieces whose characters appear on the page, and only for
the font the learner picked. Download the sources into one empty directory, then run from
the frontend directory:

    D=/tmp/fonts; G=https://raw.githubusercontent.com/google/fonts/main/ofl
    curl -sSfL -o $D/Inter.ttf "$G/inter/Inter%5Bopsz%2Cwght%5D.ttf"
    curl -sSfL -o $D/NotoSansSC.ttf "$G/notosanssc/NotoSansSC%5Bwght%5D.ttf"
    curl -sSfL -o $D/SourceSerif4.ttf "$G/sourceserif4/SourceSerif4%5Bopsz%2Cwght%5D.ttf"
    curl -sSfL -o $D/NotoSerif.ttf "$G/notoserif/NotoSerif%5Bwdth%2Cwght%5D.ttf"
    curl -sSfL -o $D/NotoSerifSC.ttf "$G/notoserifsc/NotoSerifSC%5Bwght%5D.ttf"
    gh release download v1.530 -R lxgw/LxgwWenKai -D $D \\
        -p LXGWWenKai-Regular.ttf -p LXGWWenKai-Medium.ttf
    uv run --no-project --with fonttools --with brotli \\
        python -I scripts/build-fonts.py $D

Each choice gets public/fonts/<choice>/ with its pieces and a font.css. Pieces:
  latin    English and Western European letters, IPA, punctuation, currency, arrows
  symbols  other non-CJK glyphs below U+2E80 (more Latin, Greek, Cyrillic, math)
  ipa      IPA only, to fill what the Latin face lacks (the next family in the stack)
  ui       Han characters and CJK punctuation used by the zh-CN interface strings
  hot-N    remaining characters ranked by frequency in docs/ (Chinese prose), 150 each
  gb-N     the rest of GB2312, in code order, 200 each
Characters outside these fall back to the system fonts in globals.css. Variable fonts
keep their weight axis; other axes (optical size, width) are pinned to the default.
"""

import io
import json
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

FRONTEND = Path(__file__).resolve().parent.parent
REPO = FRONTEND.parent
OUT_ROOT = FRONTEND / "public" / "fonts"
HOT_SIZE = 150
GB_SIZE = 200
# Basic Latin to Latin Extended-A, IPA, combining marks, general punctuation, currency,
# letterlike, arrows. Latin Extended-B / Additional (Vietnamese and so on) go to symbols.
LATIN_BLOCKS = [(0x0000, 0x017F), (0x0250, 0x036F), (0x1D00, 0x1DBF), (0x2000, 0x21FF)]
IPA_BLOCKS = [(0x0250, 0x02FF), (0x1D00, 0x1DBF)]


@dataclass(frozen=True)
class Face:
    slug: str
    family: str
    source: str
    pieces: tuple[str, ...]
    # None: a variable font, declared over its whole weight axis.
    weight: str | None = None


ALL = ("latin", "symbols", "cjk")
CHOICES: dict[str, list[Face]] = {
    "sans": [
        Face("inter", "Inter", "Inter.ttf", ("latin", "symbols")),
        Face("notosanssc", "Noto Sans SC", "NotoSansSC.ttf", ("cjk",)),
    ],
    "serif": [
        Face("sourceserif", "Source Serif 4", "SourceSerif4.ttf", ("latin", "symbols")),
        Face("notoserif", "Noto Serif", "NotoSerif.ttf", ("ipa",)),
        Face("notoserifsc", "Noto Serif SC", "NotoSerifSC.ttf", ("cjk",)),
    ],
    # WenKai has no Bold: Regular stands in for light weights, Medium for semibold / bold.
    "wenkai": [
        Face("regular", "LXGW WenKai", "LXGWWenKai-Regular.ttf", ALL, "100 449"),
        Face("medium", "LXGW WenKai", "LXGWWenKai-Medium.ttf", ALL, "450 900"),
    ],
}
LICENSES = {
    "sans": "Inter, Noto Sans SC",
    "serif": "Source Serif 4, Noto Serif, Noto Serif SC",
    "wenkai": "LXGW WenKai v1.530",
}


def in_blocks(cp: int, blocks: list[tuple[int, int]]) -> bool:
    return any(lo <= cp <= hi for lo, hi in blocks)


def is_cjk(cp: int) -> bool:
    return cp >= 0x2E80


def gb2312_chars() -> list[str]:
    chars = []
    for hi in range(0xA1, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.append(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return chars


def zh_ui_text() -> str:
    def strings(node: object) -> list[str]:
        if isinstance(node, dict):
            return [s for v in node.values() for s in strings(v)]
        return [node] if isinstance(node, str) else []

    data = json.loads((FRONTEND / "messages" / "zh-CN.json").read_text("utf-8"))
    return "".join(strings(data))


def docs_frequency() -> Counter[str]:
    counter: Counter[str] = Counter()
    for path in sorted((REPO / "docs").rglob("*.md")):
        counter.update(re.findall(r"[一-鿿]", path.read_text("utf-8")))
    return counter


def cjk_pieces(cmap: set[int]) -> list[tuple[str, list[int]]]:
    cjk_punct = {cp for cp in cmap if 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF}
    ui_chars = {ord(c) for c in zh_ui_text() if is_cjk(ord(c)) and ord(c) in cmap}
    ui = sorted(ui_chars | cjk_punct)
    pieces = [("ui", ui)]
    taken = set(ui)

    ranked = docs_frequency().most_common()
    hot = [ord(c) for c, _ in ranked if ord(c) in cmap and ord(c) not in taken]
    for i in range(0, len(hot), HOT_SIZE):
        pieces.append((f"hot-{i // HOT_SIZE:02d}", sorted(hot[i : i + HOT_SIZE])))
    taken |= set(hot)

    rest = [
        ord(c) for c in gb2312_chars() if is_cjk(ord(c)) and ord(c) in cmap and ord(c) not in taken
    ]
    for i in range(0, len(rest), GB_SIZE):
        pieces.append((f"gb-{i // GB_SIZE:02d}", sorted(rest[i : i + GB_SIZE])))
    return pieces


def plan_pieces(face: Face, cmap: set[int]) -> list[tuple[str, list[int]]]:
    pieces: list[tuple[str, list[int]]] = []
    if "latin" in face.pieces:
        pieces.append(("latin", sorted(cp for cp in cmap if in_blocks(cp, LATIN_BLOCKS))))
    if "symbols" in face.pieces:
        symbols = [cp for cp in cmap if not in_blocks(cp, LATIN_BLOCKS) and not is_cjk(cp)]
        pieces.append(("symbols", sorted(symbols)))
    if "ipa" in face.pieces:
        pieces.append(("ipa", sorted(cp for cp in cmap if in_blocks(cp, IPA_BLOCKS))))
    if "cjk" in face.pieces:
        pieces.extend(cjk_pieces(cmap))
    return [(name, cps) for name, cps in pieces if cps]


def unicode_range(cps: list[int]) -> str:
    parts, start = [], cps[0]
    for prev, cp in zip(cps, [*cps[1:], None], strict=True):
        if cp is None or cp != prev + 1:
            parts.append(f"U+{start:X}" if start == prev else f"U+{start:X}-{prev:X}")
            start = cp if cp is not None else start
    return ", ".join(parts)


def load_source(path: Path) -> tuple[bytes, str]:
    """The font with non-weight axes pinned to their defaults, and its CSS weight range."""
    font = TTFont(path)
    if "fvar" not in font:
        return path.read_bytes(), ""
    axes = {a.axisTag: a for a in font["fvar"].axes}
    pinned = {tag: a.defaultValue for tag, a in axes.items() if tag != "wght"}
    if pinned:
        font = instancer.instantiateVariableFont(font, pinned)
    buf = io.BytesIO()
    font.save(buf)
    wght = axes["wght"]
    return buf.getvalue(), f"{wght.minValue:g} {wght.maxValue:g}"


def build_piece(source: bytes, cps: list[int]) -> bytes:
    font = TTFont(io.BytesIO(source))
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=cps)
    subsetter.subset(font)
    font.flavor = "woff2"
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def build_choice(choice: str, faces: list[Face], src_dir: Path) -> None:
    out_dir = OUT_ROOT / choice
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    css = [
        "/* Generated by scripts/build-fonts.py (ADR 0060). Do not edit by hand. */",
        f"/* {LICENSES[choice]}: SIL OFL 1.1, see src/fonts/LICENSE-*.txt */",
    ]
    total = 0
    for face in faces:
        source, axis_weight = load_source(src_dir / face.source)
        cmap = set(TTFont(io.BytesIO(source)).getBestCmap())
        for name, cps in plan_pieces(face, cmap):
            data = build_piece(source, cps)
            total += len(data)
            filename = f"{face.slug}-{name}.woff2"
            (out_dir / filename).write_bytes(data)
            css.append(
                "@font-face {\n"
                f'  font-family: "{face.family}";\n'
                "  font-style: normal;\n"
                f"  font-weight: {face.weight or axis_weight};\n"
                "  font-display: swap;\n"
                f'  src: url("/fonts/{choice}/{filename}") format("woff2");\n'
                f"  unicode-range: {unicode_range(cps)};\n"
                "}"
            )
    (out_dir / "font.css").write_text("\n".join(css) + "\n", "utf-8")
    print(f"{choice}: {len(css) - 2} faces, {total // 1024} KB")


def main(src_dir: Path, only: list[str]) -> None:
    for choice, faces in CHOICES.items():
        if not only or choice in only:
            build_choice(choice, faces, src_dir)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
