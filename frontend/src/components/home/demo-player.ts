import { DemoClock, STOP } from "./demo-clock";
import { type DemoCopy, SCENES } from "./demo-copy";
import c from "./landing-demo.module.css";

/**
 * The home page demo's scenes (ADR 0065 §2), played into the chat window as the app runs a
 * turn: memories read, the reply streamed, tools called, work done after the reply, and the
 * workspace sliding open for long texts. Loaded with a dynamic import only when the section
 * nears the viewport. It writes the DOM directly, like the scripted picture it is; all copy
 * comes from the message catalogs (trusted, and allowed to carry <b> / <s>).
 */

export type Player = {
  play(scene: number): void;
  setPlaying(on: boolean): void;
  destroy(): void;
};

// The reading and writing material is English in both languages; the translation is the
// Chinese a learner reading it would get.
const ARTICLE = {
  title: "Water around a young star",
  p: [
    [
      `Astronomers have found signs of water <span class="${c.wd}">vapour</span> around a young star about 450 light-years from Earth.`,
      "天文学家在距地球约 450 光年的一颗年轻恒星周围，发现了水蒸气的迹象。",
    ],
    [
      `<span class="${c.sn}">The water sits in a disc of gas and dust that is still forming planets, which suggests that worlds like ours <span data-pick>may begin with water already on board</span>.</span>`,
      "这些水位于一个仍在形成行星的气体尘埃盘中，这表明像地球这样的星球可能一开始就自带着水。",
    ],
    [
      "“We were not expecting such a clear signal,” said the lead researcher, adding that further observations would be needed to confirm it.",
      "“我们没想到信号会这么清晰，”首席研究员说，并补充说还需要进一步观测来证实。",
    ],
  ],
  pasted:
    "Water around a young star · Astronomers have found signs of water vapour around a young star about 450 light-years from Earth. The water sits in a disc of gas and dust that is still forming planets…",
};
const ESSAY = {
  title: "My new city",
  text: `My family moved to Hangzhou three years ago. We have lived here <span class="${c.err}" data-e="0">since three years</span>, and I really like it. The streets are quiet and <span class="${c.err}" data-e="1">the people here is friendly</span>. On weekends we walk around the West Lake and try new food. <span class="${c.err}" data-e="2">It is a very good place.</span>`,
  pasted:
    "My new city · My family moved to Hangzhou three years ago. We have lived here since three years, and I really like it. The streets are quiet and the people here is friendly…",
  edits: [
    ["since three years", "for three years", "tense"],
    ["the people here is friendly", "the people here are friendly", "agreement"],
    ["It is a very good place.", "It's a lovely place to live.", "style"],
  ] as const,
};

const LOGO = `<svg viewBox="0 0 64 64" aria-hidden="true"><g fill="var(--brand)" stroke="var(--brand)" stroke-linejoin="round"><path stroke-width="3.4" d="M14.4 14.4L12.8 5.4L18 10.8Z"/><path stroke-width="3.4" d="M29.6 14.4L31.2 5.4L26 10.8Z"/><ellipse stroke="none" cx="22" cy="19.2" rx="10.8" ry="10.4"/><path stroke="none" d="M15 23C8.8 30 8.2 43.6 9.6 50.2Q10.4 54 14.6 54H29.4Q33.6 54 34.4 50.2C35.8 43.6 35.2 30 29 23Z"/></g><path d="M31 51.2H42C49 51.2 52.5 46.4 51.5 41.2C50.6 36.8 45.6 35.8 43 38.8" fill="none" stroke="var(--brand)" stroke-width="5.6" stroke-linecap="round" stroke-linejoin="round"/><path fill="var(--spark)" d="M43 12.5Q43 19 49.5 19Q43 19 43 25.5Q43 19 36.5 19Q43 19 43 12.5Z"/></svg>`;
const BOOK = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px"><path d="M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7z"/></svg>`;
const POINTER = `<svg viewBox="0 0 20 20"><path d="M3 2l13 7.2-5.6 1.3L8 16z" fill="#1C1B22" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>`;

/* A CJK character streams on its own; anything else streams a word with its trailing space. */
const TOKEN = /[　-〿㐀-鿿＀-￯]|[^\s　-〿㐀-鿿＀-￯]+\s*|\s+/g;

/** The pieces a text streams in, as the chat streams tokens. */
export function splitTokens(text: string): string[] {
  return text.match(TOKEN) ?? [];
}

function el(tag: string, cls?: string, html?: string): HTMLElement {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}

export function createPlayer(
  win: HTMLElement,
  t: DemoCopy,
  { reduced, onScene }: { reduced: boolean; onScene: (scene: number) => void },
): Player {
  const clock = new DemoClock(reduced);
  let run = 0;
  const wait = (ms: number) => clock.wait(ms, run);
  const narrow = () => window.matchMedia?.("(max-width: 820px)").matches ?? false;

  let msgs: HTMLElement;
  let input: HTMLElement;
  let composer: HTMLElement;
  let wsTop: HTMLElement;
  let wsBody: HTMLElement;
  let cursor: HTMLElement;
  const q = (sel: string) => win.querySelector<HTMLElement>(sel)!;
  const follow = () => {
    msgs.scrollTop = msgs.scrollHeight;
  };

  // ---------- building blocks ----------
  /** Wraps every text piece of `html` in a hidden span, appended to `target`; returns them in order. */
  function tokens(target: HTMLElement, html: string): HTMLElement[] {
    const tpl = document.createElement("template");
    tpl.innerHTML = html;
    const out: HTMLElement[] = [];
    (function walk(node: Node) {
      for (const child of [...node.childNodes]) {
        if (child.nodeType !== Node.TEXT_NODE) {
          walk(child);
          continue;
        }
        const frag = document.createDocumentFragment();
        for (const piece of splitTokens(child.textContent ?? "")) {
          const span = el("span", c.hidden);
          span.textContent = piece;
          frag.append(span);
          out.push(span);
        }
        child.replaceWith(frag);
      }
    })(tpl.content);
    target.append(tpl.content);
    return out;
  }
  async function stream(target: HTMLElement, html: string, ms = 32) {
    const caret = el("i", c.caret);
    const list = tokens(target, html);
    for (const [i, piece] of list.entries()) {
      piece.className = "";
      piece.after(caret);
      if (i % 3 === 0) follow();
      await wait(ms);
    }
    caret.remove();
    follow();
  }
  async function type(text: string, ms = 30) {
    for (const ch of text) {
      input.append(ch);
      await wait(ch === " " ? ms / 2 : ms);
    }
  }
  function me(text: string, quote?: string) {
    const m = el("div", c.me);
    if (quote) m.append(el("span", c.q, quote));
    m.append(text);
    msgs.append(m);
    follow();
  }
  async function send(text: string, quote?: string) {
    await clickOn(composer.querySelector(`.${c.send}`));
    input.textContent = "";
    me(text, quote);
    await wait(400);
  }
  function ai() {
    const m = el("div", c.ai, `<span class="${c.av}">${LOGO}</span>`);
    msgs.append(m);
    follow();
    return m;
  }
  function step(parent: HTMLElement, name: string, running: string) {
    const s = el("div", c.step, `<span><i class="${c.spinner}"></i><code>${name}</code><em>${running}</em></span>`);
    parent.append(s);
    follow();
    return {
      done(text: string, detail?: string) {
        s.classList.add(c.done);
        s.querySelector("em")!.textContent = text;
        if (detail) s.append(el("div", c.det, detail));
        follow();
      },
    };
  }
  async function stepRun(
    parent: HTMLElement,
    name: string,
    { running, done }: { running: string; done: string },
    detail?: string,
    ms = 900,
  ) {
    const s = step(parent, name, running);
    await wait(ms);
    s.done(done, detail);
    await wait(250);
  }
  function reply(m: HTMLElement) {
    const r = el("div", c.reply);
    m.append(r);
    const p = el("p");
    r.append(p);
    return { r, p };
  }
  function summary(parent: HTMLElement, text: string, rows: [string, string][]) {
    const b = el("button", c.sum, `<span class="${c.chev}">›</span><span>${t.activity} ${text}</span>`);
    b.setAttribute("type", "button");
    b.tabIndex = -1;
    const panel = el("div", c.sumPanel, rows.map(([k, v]) => `<div><span>${k}</span><span>${v}</span></div>`).join(""));
    panel.hidden = true;
    b.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      b.classList.toggle(c.open, !panel.hidden);
      follow();
    });
    parent.append(b, panel);
    follow();
    return b;
  }

  // the pointer: moves to an element's spot inside the window, then taps
  async function pointTo(target: Element | null, fx = 0.5, fy = 0.55) {
    if (!target) return;
    const w = win.getBoundingClientRect();
    const r = target.getBoundingClientRect();
    cursor.classList.add(c.on);
    cursor.style.transform = `translate(${r.left - w.left + r.width * fx}px, ${r.top - w.top + r.height * fy}px)`;
    await wait(700);
  }
  async function tap() {
    cursor.classList.remove(c.tap);
    void cursor.offsetWidth;
    cursor.classList.add(c.tap);
    await wait(260);
  }
  async function clickOn(target: Element | null, fx?: number, fy?: number) {
    await pointTo(target, fx, fy);
    await tap();
  }
  /** Scrolls `box` just enough to show `target`. */
  function into(box: HTMLElement, target: HTMLElement, pad = 40) {
    const b = box.getBoundingClientRect();
    const r = target.getBoundingClientRect();
    if (r.bottom > b.bottom - pad) box.scrollTop += r.bottom - b.bottom + pad;
    else if (r.top < b.top + pad) box.scrollTop -= b.top + pad - r.top;
  }
  // let a smooth scroll land before pointing
  const settle = () => wait(reduced ? 0 : 420);

  function hintBar() {
    const s = t.reading;
    const bar = el(
      "div",
      c.hintbar,
      `<span>${s.offer}</span><b class="${c.btn} ${c.solid}" data-k="read">${s.read}</b><b class="${c.btn}" data-k="write">${s.write}</b><b class="${c.btn} ${c.ghost}">${s.send}</b>`,
    );
    composer.prepend(bar);
    follow();
    return bar;
  }
  async function paste(text: string) {
    await clickOn(input, 0.3, 0.5);
    input.textContent = text;
    await wait(500);
  }
  function openWorkspace(kind: "reading" | "writing", title: string, version: string, tools: string) {
    wsTop.innerHTML = `<b class="${c.btn} ${c.ghost} ${c.back}">←</b><span>${kind === "reading" ? BOOK : "✎"}</span><b>${title}</b><span class="${c.ver}">${version}</span><span class="${c.wsTools}">${tools}</span>`;
    wsBody.innerHTML = "";
    wsBody.scrollTop = 0;
    win.classList.add(c.split);
  }
  function docCard(parent: HTMLElement, icon: string, title: string, sub: string) {
    parent.append(el("div", c.docCard, `<i>${icon}</i><span><b>${title}</b><small>${sub}</small></span>`));
    follow();
  }

  // ---------- scenes ----------
  const scenes: Record<(typeof SCENES)[number], () => Promise<void>> = {
    // memory and a fix
    async memory() {
      const s = t.memory;
      await clickOn(input, 0.3, 0.5);
      await type(s.user, 24);
      await send(s.user);
      const m = ai();
      await stepRun(m, "load_context", { running: t.loadContext, done: s.context }, s.contextDetail);
      await stream(reply(m).p, s.reply);
      await wait(300);
      await stepRun(m, "grammar_tagging", s.grammar, s.grammarDetail);
      await stepRun(m, "reflect_memory", s.reflect, s.reflectDetail);
      const b = summary(m, s.summary, [
        [t.read, s.contextDetail],
        [t.called, "grammar_tagging · reflect_memory"],
        [t.saved, `${s.reflectDetail} · <a>${t.editable}</a>`],
      ]);
      await wait(600);
      await settle();
      await clickOn(b, 0.25);
      b.click();
    },
    // practice, checked before it is shown
    async practice() {
      const s = t.practice;
      await clickOn(input, 0.3, 0.5);
      await type(s.user, 22);
      await send(s.user);
      const m = ai();
      await stepRun(m, "load_context", { running: t.loadContext, done: s.context }, s.contextDetail);
      const { r, p } = reply(m);
      await stream(p, s.reply);
      const quiz = step(r, "give_quiz", s.quiz.running);
      await wait(1100);
      quiz.done(s.quiz.done);
      await stepRun(r, "critic", s.critic, undefined, 1200);
      const card = el(
        "div",
        c.quiz,
        `<header>${s.card}<span class="${c.okChip}">✓ ${s.checked}</span><small>${s.progress}</small></header>
        <p>I ____ in Hangzhou since 2019.</p>
        <div class="${c.opts}"><span>live</span><span data-ok>have lived</span><span>lived</span><span>am living</span></div>`,
      );
      r.append(card);
      follow();
      await wait(700);
      await settle();
      const right = card.querySelector<HTMLElement>("[data-ok]")!;
      await clickOn(right);
      right.classList.add(c.right);
      right.textContent += "  ✓";
      card.append(el("div", c.why, s.why));
      follow();
      await wait(500);
      await stepRun(m, "practice_grade", s.grade, s.gradeDetail);
      summary(m, s.summary, [
        [t.read, s.contextDetail],
        [t.called, "give_quiz · critic · practice_grade"],
      ]);
    },
    // a long text opens in the workspace for close reading
    async reading() {
      const s = t.reading;
      await paste(ARTICLE.pasted);
      const bar = hintBar();
      await wait(900);
      await clickOn(bar.querySelector("[data-k=read]"));
      bar.remove();
      input.textContent = "";
      openWorkspace(
        "reading",
        ARTICLE.title,
        s.version,
        `<span class="${c.seg}"><span>${s.modes.original}</span><span class="${c.on}">${s.modes.parallel}</span><span>${s.modes.translation}</span></span><b class="${c.btn}" data-k="ana">${s.analyse}</b>`,
      );
      wsBody.append(el("h3", undefined, ARTICLE.title));
      const rows = ARTICLE.p.map(([text]) => {
        const row = el(
          "div",
          c.para,
          `<div>${text}</div><div data-zh><div class="${c.shim}"><i></i><i></i><i></i></div></div>`,
        );
        wsBody.append(row);
        return row;
      });
      docCard(ai(), BOOK, ARTICLE.title, `${s.opened} · ${s.version}`);
      await wait(800);
      // translated paragraph by paragraph
      for (const [i, row] of rows.entries()) {
        await wait(650);
        row.querySelector("[data-zh]")!.innerHTML = `<div class="${c.zh}">${ARTICLE.p[i][1]}</div>`;
      }
      await wait(500);
      // a word opens its card
      const word = wsBody.querySelector<HTMLElement>(`.${c.wd}`)!;
      await clickOn(word);
      word.classList.add(c.hot);
      const box = wsBody.getBoundingClientRect();
      const wr = word.getBoundingClientRect();
      const pop = el(
        "div",
        c.pop,
        `<strong>vapour</strong><em>/ˈveɪpə/</em><span>${s.word}</span><span class="${c.lvl}">B2</span><b class="${c.btn}">${s.add}</b>`,
      );
      pop.style.top = `${wr.bottom - box.top + wsBody.scrollTop + 6}px`;
      pop.style.left = `${Math.max(8, Math.min(wr.left - box.left, box.width - 250))}px`;
      wsBody.append(pop);
      await wait(900);
      const add = pop.querySelector<HTMLElement>(`.${c.btn}`)!;
      await clickOn(add);
      add.textContent = s.added;
      await wait(900);
      pop.remove();
      word.classList.remove(c.hot);
      // a sentence opens its structure
      const anaButton = wsTop.querySelector<HTMLElement>("[data-k=ana]")!;
      await clickOn(anaButton);
      anaButton.classList.add(c.on);
      const sentence = wsBody.querySelector<HTMLElement>(`.${c.sn}`)!;
      await clickOn(sentence, 0.3, 0.3);
      sentence.classList.add(c.hot);
      const ana = el(
        "div",
        c.ana,
        `<div class="${c.step}"><span><i class="${c.spinner}"></i><em>${s.analysing}</em></span></div>`,
      );
      rows[1].append(ana);
      into(wsBody, ana);
      await wait(1200);
      ana.innerHTML = `<dl>${Object.values(s.analysis)
        .map(({ label, text }) => `<dt>${label}</dt><dd>${text}</dd>`)
        .join("")}</dl>`;
      await settle();
      into(wsBody, ana);
      await wait(2200);
      ana.remove();
      sentence.classList.remove(c.hot);
      anaButton.classList.remove(c.on);
      await settle();
      // select a phrase, ask about it in the chat
      const pick = wsBody.querySelector<HTMLElement>("[data-pick]")!;
      await pointTo(pick, 0, 0.6);
      pick.classList.add(c.sel);
      await pointTo(pick, 1, 0.6);
      const pr = pick.getBoundingClientRect();
      const bb = wsBody.getBoundingClientRect();
      const ask = el("b", `${c.btn} ${c.solid} ${c.ask}`, s.ask);
      ask.style.top = `${pr.top - bb.top + wsBody.scrollTop - 36}px`;
      ask.style.left = `${Math.max(8, pr.left - bb.left + pr.width / 2 - 40)}px`;
      wsBody.append(ask);
      await wait(500);
      await clickOn(ask);
      ask.remove();
      const quote = `“${pick.textContent}”`;
      if (narrow()) win.classList.remove(c.split);
      input.textContent = "";
      input.append(el("span", c.q, quote));
      await wait(300);
      await type(s.question, 60);
      await send(s.question, quote);
      pick.classList.remove(c.sel);
      const m = ai();
      await stream(reply(m).p, s.reply);
      summary(m, s.summary, [
        [t.read, quote],
        [t.called, "—"],
      ]);
    },
    // an essay opens in the workspace with changes to accept or skip
    async writing() {
      const s = t.writing;
      await paste(ESSAY.pasted);
      const bar = hintBar();
      await wait(900);
      await clickOn(bar.querySelector("[data-k=write]"));
      bar.remove();
      input.textContent = "";
      let version = 1;
      openWorkspace(
        "writing",
        ESSAY.title,
        `${s.words} · ${s.saved}`,
        `<b class="${c.btn}" data-k="vers">${s.versions}（${version}）</b><b class="${c.btn} ${c.solid}">${s.review}</b>`,
      );
      const essay = el("div", c.essay, `<div class="${c.doc}"><p>${ESSAY.text}</p></div>`);
      wsBody.append(essay);
      const m = ai();
      await stepRun(m, "writing_review", { running: s.reviewing, done: s.reviewed }, undefined, 1600);
      await stream(reply(m).p, s.reply);
      await stepRun(m, "propose_edit", s.edits, undefined, 700);
      const list = el("div", c.edits, `<h4>${s.heading}<b class="${c.btn}">${s.acceptAll}</b></h4>`);
      for (const [from, to, why] of ESSAY.edits) {
        list.append(
          el(
            "div",
            c.edit,
            `<span><s>${from}</s> → <b>${to}</b></span><span class="${c.why}">${s.why[why]}</span><span class="${c.acts}"><b class="${c.btn} ${c.solid}">${s.accept}</b><b class="${c.btn}">${s.decline}</b></span>`,
          ),
        );
      }
      essay.append(list);
      const decide = async (i: number, take: boolean) => {
        const card = list.children[i + 1] as HTMLElement;
        const span = essay.querySelector<HTMLElement>(`[data-e="${i}"]`)!;
        span.classList.add(c.hot);
        await settle();
        into(wsBody, card, 20);
        await settle();
        await clickOn(card.querySelectorAll(`.${c.acts} .${c.btn}`)[take ? 0 : 1]);
        span.className = "";
        card.classList.add(c.gone);
        card.querySelector(`.${c.acts}`)!.replaceWith(el("span", c.result, take ? s.accepted : s.declined));
        if (take) {
          span.innerHTML = `<del>${ESSAY.edits[i][0]}</del> <ins>${ESSAY.edits[i][1]}</ins>`;
          version++;
          wsTop.querySelector("[data-k=vers]")!.textContent = `${s.versions}（${version}）`;
        }
        await wait(700);
      };
      await wait(600);
      await decide(0, true);
      await decide(1, true);
      await decide(2, false);
      await stepRun(m, "grammar_tagging", s.grammar, s.grammarDetail);
      summary(m, s.summary, [[t.called, "writing_review · propose_edit · grammar_tagging"]]);
      await wait(500);
      await clickOn(wsTop.querySelector("[data-k=vers]"));
      wsBody.scrollTop = 0;
      const { current, first } = s.history;
      wsBody.append(
        el(
          "div",
          c.versions,
          `<div><b>${current.name}</b><small>${current.meta}</small><small>${current.action}</small></div>` +
            `<div><b>${first.name}</b><small>${first.meta}</small><b class="${c.btn}">${first.action}</b></div>`,
        ),
      );
    },
    // a quick answer, then a deeper follow-up the tutor chose to write
    async deepen() {
      const s = t.deepen;
      await clickOn(input, 0.3, 0.5);
      await type(s.user, 40);
      await send(s.user);
      const m = ai();
      await stepRun(m, "load_context", { running: t.loadContext, done: s.context }, s.contextDetail, 700);
      const { r, p } = reply(m);
      await stream(p, s.reply, 26);
      const deep = el("div", c.deep, `<span>${s.label}</span>`);
      r.append(deep);
      const d = step(deep, "deepen", s.deepen.running);
      await wait(1500);
      const more = el("p");
      deep.append(more);
      await stream(more, s.more, 30);
      d.done(s.deepen.done);
      summary(m, s.summary, [
        [t.read, s.contextDetail],
        [t.called, "load_context · deepen"],
      ]);
    },
  };

  // ---------- the window ----------
  function shell() {
    win.classList.remove(c.split);
    win.innerHTML = `
      <div class="${c.chat}">
        <div class="${c.wTop}"><span class="${c.av}">${LOGO}</span>JOJO<small>${t.level}</small></div>
        <div class="${c.msgs}"></div>
        <div class="${c.composer}"><div class="${c.box}"><div class="${c.field}"></div><span class="${c.send}">↑</span></div></div>
      </div>
      <div class="${c.ws}"><div class="${c.wsTop}"></div><div class="${c.wsBody}"></div></div>
      <div class="${c.cursor}">${POINTER}</div>`;
    msgs = q(`.${c.msgs}`);
    input = q(`.${c.field}`);
    input.dataset.placeholder = t.placeholder;
    composer = q(`.${c.composer}`);
    wsTop = q(`.${c.wsTop}`);
    wsBody = q(`.${c.wsBody}`);
    cursor = q(`.${c.cursor}`);
  }

  async function play(i: number) {
    run = clock.start();
    onScene(i);
    shell();
    try {
      await wait(500);
      await scenes[SCENES[i]]();
      cursor.classList.remove(c.on);
      if (reduced) return;
      await wait(3600);
      void play((i + 1) % SCENES.length);
    } catch (e) {
      if (e !== STOP) throw e;
    }
  }

  let last = 0;
  let raf = 0;
  const loop = (now: number) => {
    clock.tick(now - (last || now));
    last = now;
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);

  return {
    play: (i) => void play(i),
    setPlaying(on) {
      clock.playing = on;
    },
    destroy() {
      clock.cancel();
      cancelAnimationFrame(raf);
      win.innerHTML = "";
      win.classList.remove(c.split);
    },
  };
}
