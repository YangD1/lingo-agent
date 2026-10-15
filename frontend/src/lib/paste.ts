import { strikethrough, tables } from "@joplin/turndown-plugin-gfm";
import TurndownService from "turndown";

/**
 * Pasted text as Markdown (ADR 0043 §4, task 85): HTML copied from a web page, Google Docs or
 * Word, HTML source typed as text, and tags mixed into Markdown all become Markdown, keeping
 * headings, lists, tables, emphasis and links and dropping scripts, styles, images and page
 * chrome. Raw HTML never reaches the page either way (the Markdown renderer shows tags as text),
 * so this is about keeping the structure, not about safety.
 */

/** Elements dropped together with everything inside them. */
const DROPPED = [
  "script", "style", "noscript", "template", "iframe", "frame", "frameset", "object", "embed",
  "applet", "img", "picture", "svg", "canvas", "video", "audio", "source", "track", "map",
  "nav", "form", "input", "button", "select", "textarea", "head", "title", "meta", "link", "base",
].join(",");

/** Elements whose presence means the clipboard's HTML says more than its plain text. */
const STRUCTURE = "h1,h2,h3,h4,h5,h6,ul,ol,table,blockquote,strong,b,em,i,a[href],hr,del,s";

/** A tag of a known HTML element, so `Array<string>` or `a < b > c` don't count. */
const TAG =
  /<\/?(?:html|head|body|div|span|p|br|hr|h[1-6]|ul|ol|li|dl|dt|dd|table|thead|tbody|tfoot|tr|td|th|caption|blockquote|pre|code|b|strong|i|em|u|s|del|ins|strike|sub|sup|small|mark|a|section|article|header|footer|main|aside|nav|figure|figcaption|details|summary|font|center|script|style|iframe|img|meta|link|form|input|button|svg|noscript)\b[^<>]*>/i;

/** Dangerous containers in pasted source text, removed before anything is split into blocks. */
const DANGEROUS_SOURCE = /<(script|style|iframe|noscript|template|object|textarea|select)\b[\s\S]*?(?:<\/\1\s*>|$)/gi;

const FENCE = /^\s*(`{3,}|~{3,})/;
const INLINE_CODE = /(`+)(?!`)[\s\S]*?[^`]\1(?!`)/g;

/** What to insert for a paste: Markdown when the clipboard carries structure, else the plain text. */
export function pastedText(html: string, plain: string): string {
  if (html) {
    const root = parse(html);
    const code = root.querySelector('[style*="white-space: pre"],[style*="white-space:pre"]');
    if (!code && root.querySelector(STRUCTURE)) {
      const markdown = convert(root, true);
      if (markdown) return markdown;
    }
  }
  return sourceToMarkdown(plain);
}

/** HTML source or Markdown with tags in it, as Markdown; anything else unchanged. */
export function sourceToMarkdown(text: string): string {
  if (!TAG.test(text) && !/<!doctype html|<!--/i.test(text)) return text;
  const trimmed = text.trim();
  if (/^<(?:!doctype|!--|[a-z])/i.test(trimmed) && trimmed.endsWith(">") && !FENCE.test(text)) {
    return convert(parse(trimmed), false);
  }
  return mixedToMarkdown(text);
}

/** Markdown with tags in it: tags outside code become Markdown, the rest stays as typed. */
function mixedToMarkdown(text: string): string {
  const out: string[] = [];
  let prose: string[] = [];
  let fence: string | null = null;
  const flush = () => {
    if (prose.length) out.push(proseToMarkdown(prose.join("\n")));
    prose = [];
  };
  for (const line of text.split("\n")) {
    const mark = FENCE.exec(line)?.[1];
    if (fence) {
      out.push(line);
      if (mark && mark[0] === fence[0] && mark.length >= fence.length && line.trim() === mark) fence = null;
    } else if (mark) {
      flush();
      fence = mark;
      out.push(line);
    } else {
      prose.push(line);
    }
  }
  flush();
  return out.join("\n");
}

/** Markdown prose (no fenced code): an HTML block becomes Markdown, a tag inside a line too. */
function proseToMarkdown(prose: string): string {
  return prose
    .replace(DANGEROUS_SOURCE, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .split(/(\n[ \t]*\n)/)
    .map((block) => {
      if (!TAG.test(block)) return block;
      if (/^\s*<[a-z]/i.test(block)) return inlineCodeKept(block, (part) => convert(parse(part), false));
      return block
        .split("\n")
        .map((line) => {
          if (!TAG.test(line)) return line;
          const indent = /^\s*/.exec(line)?.[0] ?? "";
          return indent + inlineCodeKept(line.slice(indent.length), (part) => convert(parse(part), false));
        })
        .join("\n");
    })
    .join("");
}

/** Runs `change` with inline code spans held aside, so `<b>` written as code stays code. */
function inlineCodeKept(text: string, change: (text: string) => string): string {
  const spans: string[] = [];
  const held = text.replace(INLINE_CODE, (span) => `${spans.push(span) - 1}`);
  return change(held).replace(/(\d+)/g, (_, i: string) => spans[Number(i)]);
}

function parse(html: string): HTMLElement {
  const root = new DOMParser().parseFromString(html, "text/html").body;
  clean(root);
  return root;
}

/** Drops page chrome and turns what Google Docs and Word say with styles into plain elements. */
function clean(root: HTMLElement) {
  root.querySelectorAll(DROPPED).forEach((el) => el.remove());

  // Google Docs wraps everything in <b style="font-weight:normal" id="docs-internal-guid-…">.
  root.querySelectorAll<HTMLElement>("b, strong").forEach((el) => {
    if (/font-weight\s*:\s*(?:normal|[1-4]00)\b/i.test(el.getAttribute("style") ?? "")) unwrap(el);
  });

  // Google Docs and Word mark emphasis with styles on spans.
  root.querySelectorAll<HTMLElement>("span[style]").forEach((span) => {
    const style = span.getAttribute("style") ?? "";
    const tags = [
      /font-weight\s*:\s*(?:bold|[6-9]00)\b/i.test(style) && !span.closest("h1,h2,h3,h4,h5,h6,th") && "strong",
      /font-style\s*:\s*italic/i.test(style) && "em",
      /text-decoration[^;]*line-through/i.test(style) && "del",
    ].filter((tag): tag is string => Boolean(tag));
    for (const tag of tags) {
      const wrapper = span.ownerDocument.createElement(tag);
      wrapper.append(...Array.from(span.childNodes));
      span.append(wrapper);
    }
  });

  wordLists(root);
  tablesForMarkdown(root);
}

/** Word writes list items as paragraphs led by a bullet or number span; make them real lists. */
function wordLists(root: HTMLElement) {
  root.querySelectorAll<HTMLElement>('[style*="mso-list:Ignore"], [style*="mso-list: Ignore"]').forEach((marker) => {
    const paragraph = marker.closest("p");
    if (!paragraph) return;
    const tag = /^\s*\w{1,3}[.)]/.test(marker.textContent ?? "") ? "OL" : "UL";
    marker.remove();
    const before = paragraph.previousElementSibling;
    const list =
      before?.nodeName === tag && before.hasAttribute("data-word-list")
        ? before
        : paragraph.ownerDocument.createElement(tag);
    if (list !== before) {
      list.setAttribute("data-word-list", "");
      paragraph.before(list);
    }
    const item = paragraph.ownerDocument.createElement("li");
    item.append(...Array.from(paragraph.childNodes));
    list.append(item);
    paragraph.remove();
  });
}

/**
 * Table cells as one line of inline text, and the first row as the header when there is none
 * (Google Docs, Word): otherwise the table plugin keeps the table as HTML or adds an empty header.
 */
function tablesForMarkdown(root: HTMLElement) {
  root.querySelectorAll<HTMLElement>("td, th").forEach((cell) => {
    cell.querySelectorAll("code").forEach((code) => {
      const span = code.ownerDocument.createElement("lingo-code");
      span.textContent = code.textContent;
      code.replaceWith(span);
    });
    cell.querySelectorAll("br, hr").forEach((el) => el.replaceWith(" "));
    cell
      .querySelectorAll("p, div, li, ul, ol, h1, h2, h3, h4, h5, h6, blockquote, pre")
      .forEach((el) => unwrap(el, " "));
  });
  root.querySelectorAll("table").forEach((table) => {
    if (table.querySelector("th")) return;
    table.rows[0]?.querySelectorAll("td").forEach((td) => {
      const th = td.ownerDocument.createElement("th");
      th.append(...Array.from(td.childNodes));
      td.replaceWith(th);
    });
  });
}

function unwrap(el: Element, around = "") {
  el.replaceWith(around, ...Array.from(el.childNodes), around);
}

const converters = new Map<boolean, TurndownService>();

/** `escape` off for source text, where Markdown the learner typed must stay Markdown. */
function convert(root: HTMLElement, escape: boolean): string {
  let service = converters.get(escape);
  if (!service) {
    service = converter(escape);
    converters.set(escape, service);
  }
  return service
    .turndown(root)
    .replace(/ /g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function converter(escape: boolean): TurndownService {
  const service = new TurndownService({
    headingStyle: "atx",
    bulletListMarker: "-",
    codeBlockStyle: "fenced",
    emDelimiter: "*",
    strongDelimiter: "**",
    hr: "---",
  });
  if (!escape) service.escape = (text) => text;
  service.use([strikethrough, tables]);
  service.addRule("listItem", {
    filter: "li",
    replacement(content, node) {
      const parent = node.parentNode as HTMLElement;
      let prefix = "- ";
      if (parent.nodeName === "OL") {
        const start = Number(parent.getAttribute("start") ?? 1);
        prefix = `${start + Array.prototype.indexOf.call(parent.children, node)}. `;
      }
      const body = content.replace(/^\n+/, "").replace(/\n+$/, "\n").replace(/\n/gm, `\n${" ".repeat(prefix.length)}`);
      return prefix + body.trimEnd() + (node.nextSibling ? "\n" : "");
    },
  });
  service.addRule("link", {
    filter: (node) => node.nodeName === "A" && node.hasAttribute("href"),
    replacement(content, node) {
      const href = (node as HTMLElement).getAttribute("href")?.trim() ?? "";
      if (!content.trim() || !/^(?:https?:|mailto:)/i.test(href)) return content;
      return `[${content}](${href.replace(/[\s()]/g, encodeURIComponent)})`;
    },
  });
  service.addRule("cellCode", {
    filter: (node) => node.nodeName === "LINGO-CODE",
    replacement: (_, node) => `\`${node.textContent ?? ""}\``,
  });
  return service;
}
