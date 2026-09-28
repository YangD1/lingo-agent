import type { ComponentProps, ElementType } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkCjkFriendly from "remark-cjk-friendly/parseOnly";
import remarkGfm from "remark-gfm";

// remark-cjk-friendly: plain CommonMark refuses `这是**“重点”**的意思` as bold
// because the `**` sits between a CJK letter and punctuation; LLM replies to
// Chinese learners hit this constantly. Raw HTML is never rendered (react-markdown
// default), so model output cannot inject markup.
const remarkPlugins = [remarkGfm, remarkCjkFriendly];

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

export function Markdown({ children }: { children: string }) {
  return (
    <div className="break-words">
      <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
