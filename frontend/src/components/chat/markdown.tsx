import type { ComponentProps, ElementType } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkCjkFriendly from "remark-cjk-friendly/parseOnly";
import remarkGfm from "remark-gfm";

// remark-cjk-friendly: plain CommonMark refuses `这是**“重点”**的意思` as bold
// because the `**` sits between a CJK letter and punctuation; LLM replies to
// Chinese learners hit this constantly. Raw HTML is never rendered (react-markdown
// default), so model output cannot inject markup.
const remarkPlugins = [remarkGfm, remarkCjkFriendly];

/** One English word, maybe hyphenated or with an apostrophe (same rule as the backend's
 * collected words). */
export const WORD = /[A-Za-z]+(?:['\u2019-][A-Za-z]+)*/g;
// Words here are code or a link's text, not prose to look up.
const SKIP_TAGS = new Set(["code", "pre", "a"]);

// Just the hast shapes this touches (hast types aren't a direct dependency).
type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

function wrapWords(text: string): HastNode[] {
  const out: HastNode[] = [];
  let last = 0;
  for (const match of text.matchAll(WORD)) {
    const start = match.index;
    if (start > last) out.push({ type: "text", value: text.slice(last, start) });
    out.push({
      type: "element",
      tagName: "span",
      properties: { dataWord: match[0], className: ["cursor-pointer rounded-sm hover:bg-primary/10"] },
      children: [{ type: "text", value: match[0] }],
    });
    last = start + match[0].length;
  }
  if (last < text.length) out.push({ type: "text", value: text.slice(last) });
  return out;
}

/** Wraps each English word of the prose in `span[data-word]`, for the word popup (ADR 0017 §2). */
function rehypeWords() {
  const visit = (node: HastNode) => {
    if (!node.children || (node.tagName && SKIP_TAGS.has(node.tagName))) return;
    node.children = node.children.flatMap((child) => {
      if (child.type === "text" && child.value) return wrapWords(child.value);
      visit(child);
      return [child];
    });
  };
  return visit;
}
const rehypePlugins = [rehypeWords];

// react-markdown passes its AST `node` to every custom component; drop it so it
// doesn't end up as a DOM attribute.
function styled<T extends ElementType>(Tag: T, className: string, extra?: ComponentProps<T>) {
  function Styled({ node, ...props }: ComponentProps<T> & ExtraProps) {
    void node;
    const Element = Tag as ElementType;
    return <Element className={className} {...extra} {...props} />;
  }
  Styled.displayName = `Markdown.${String(Tag)}`;
  return Styled;
}

const components: Components = {
  p: styled("p", "my-2 first:mt-0 last:mb-0"),
  ul: styled("ul", "my-2 list-disc pl-5"),
  ol: styled("ol", "my-2 list-decimal pl-5"),
  li: styled("li", "my-0.5"),
  h1: styled("h1", "mt-3 mb-2 text-lg font-semibold"),
  h2: styled("h2", "mt-3 mb-2 text-base font-semibold"),
  h3: styled("h3", "mt-3 mb-1 font-semibold"),
  blockquote: styled("blockquote", "my-2 border-l-2 border-border pl-3 text-muted-foreground"),
  a: styled("a", "underline underline-offset-2", { target: "_blank", rel: "noopener noreferrer" }),
  pre: styled("pre", "my-2 overflow-x-auto rounded-md bg-background p-3 text-sm [&_code]:bg-transparent [&_code]:p-0"),
  code: styled("code", "rounded bg-background px-1 py-0.5 font-mono text-[0.9em]"),
  table: ({ node, ...props }) => {
    void node;
    return (
      <div className="my-2 overflow-x-auto">
        <table className="border-collapse text-sm" {...props} />
      </div>
    );
  },
  th: styled("th", "border border-border px-2 py-1 text-left font-semibold"),
  td: styled("td", "border border-border px-2 py-1"),
  hr: styled("hr", "my-3 border-border"),
};

/** `words`: make English words look-up-able (tutor messages only). */
export function Markdown({ children, words = false }: { children: string; words?: boolean }) {
  return (
    <div className="break-words" data-slot="markdown">
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={words ? rehypePlugins : undefined}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
