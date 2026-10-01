/**
 * Shapes ECDICT's plain-text glosses for display (task 27.2). Chinese `translation` has one part
 * of speech per line ("n. 银行, 堤, 岸"); lines like "[医] 库" are domain senses, folded away
 * unless they are all the word has. English `definition` is WordNet or Webster text where a
 * line without a part of speech continues the previous sense.
 */

export type Sense = {
  /** "n.", "vt.", …; null for lines without one ("slay的过去分词"). */
  pos: string | null;
  /** "[经]" in "n. [经] 广告": a domain tag on a sense that still has a part of speech. */
  domain: string | null;
  text: string;
};

export type Meanings = {
  /** What the card shows. */
  main: Sense[];
  /** Domain-only lines ("[计] 运行"), shown under "more". */
  domain: Sense[];
};

// The parts of speech ECDICT and WordNet use; a whitelist, so a wrapped "place." is not one.
const POS =
  /^((?:n|v|vt|vi|a|s|adj|adv|prep|conj|pron|num|art|aux|int|interj|abbr|pl|pref|suf|na|vbl|un|phr|comb|pers|quant)\.)(?:\s+|(?=\[)|$)/;
const DOMAIN = /^\[([^\]]+)\]\s*/;

// ECDICT writes adjectives as "a." and WordNet satellite adjectives as "s.".
const POS_LABEL: Record<string, string> = { "a.": "adj.", "s.": "adj." };
const posLabel = (pos: string) => POS_LABEL[pos] ?? pos;

// "为, 因为" → "为，因为": a full-width comma between Chinese, English text left alone.
const chineseCommas = (text: string) => text.replace(/(?<=[^\x00-\x7f]), ?(?=[^\x00-\x7f])/g, "，");

function senseOf(line: string): Sense {
  let rest = line.trim();
  const pos = POS.exec(rest);
  if (pos) rest = rest.slice(pos[0].length);
  const domain = DOMAIN.exec(rest);
  if (domain) rest = rest.slice(domain[0].length);
  return {
    pos: pos ? posLabel(pos[1]) : null,
    domain: domain ? domain[1] : null,
    text: chineseCommas(rest),
  };
}

export function parseTranslation(translation: string): Meanings {
  const senses = translation
    .split("\n")
    .filter((line) => line.trim())
    .map(senseOf);
  const main = senses.filter((s) => s.pos !== null || s.domain === null);
  const domain = senses.filter((s) => s.pos === null && s.domain !== null);
  return main.length > 0 ? { main, domain } : { main: domain, domain: [] };
}

/** English senses, with hard-wrapped continuation lines joined back on. */
export function parseDefinition(definition: string | null): Sense[] {
  const senses: Sense[] = [];
  for (const raw of (definition ?? "").split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const pos = POS.exec(line);
    const last = senses.at(-1);
    if (!pos && last) last.text = `${last.text} ${line}`;
    else senses.push({ pos: pos ? posLabel(pos[1]) : null, domain: null, text: pos ? line.slice(pos[0].length) : line });
  }
  return senses;
}

/** A run of a sentence; `hit` when it is the word being learned. */
export type Segment = { text: string; hit: boolean };

const TOKEN = /[A-Za-z]+(?:['’-][A-Za-z]+)*/g;
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * The sentence cut into runs, with the word's forms (lowercase, from the API) marked:
 * single words as whole words ("go" not in "good"), phrases ("look up") as text.
 */
export function markWord(sentence: string, forms: string[]): Segment[] {
  const words = new Set(forms.filter((f) => !f.includes(" ")));
  const ranges: [number, number][] = [];
  for (const m of sentence.matchAll(TOKEN)) {
    if (words.has(m[0].toLowerCase().replace("’", "'"))) ranges.push([m.index, m.index + m[0].length]);
  }
  for (const phrase of forms.filter((f) => f.includes(" "))) {
    for (const m of sentence.matchAll(new RegExp(`\\b${escape(phrase)}\\b`, "gi"))) {
      ranges.push([m.index, m.index + m[0].length]);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const segments: Segment[] = [];
  let at = 0;
  for (const [start, end] of ranges) {
    if (start < at) continue; // overlaps one already marked
    if (start > at) segments.push({ text: sentence.slice(at, start), hit: false });
    segments.push({ text: sentence.slice(start, end), hit: true });
    at = end;
  }
  if (at < sentence.length) segments.push({ text: sentence.slice(at), hit: false });
  return segments;
}
