# lingo-agent

[![CI](https://github.com/YangD1/lingo-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/YangD1/lingo-agent/actions/workflows/ci.yml)

English | [简体中文](README.zh-CN.md)

An open-source AI English tutor agent. The goal: a tutor that remembers you, adapts what it teaches to your level, assesses you against CEFR, schedules vocabulary review with FSRS, gives you news graded to your level, answers grammar questions from a knowledge graph, and talks with you by voice.

**Stack:** FastAPI · LangChain / LangGraph · PostgreSQL + pgvector · Next.js · OpenTelemetry

> **Status: P2 complete.** The tutor chats, remembers you, tracks your grammar, schedules vocabulary review and places you on the CEFR scale. It runs practice sets checked by a critic, reviews your writing, rewrites news for your level, diagnoses the root causes of your recurring grammar mistakes and drafts a daily study plan. Voice (P3) comes next. See [what works now](#what-works-now) and the [roadmap](docs/PLAN.md).

| | |
|---|---|
| ![Chat: the tutor corrects a mistake and shows what it did](docs/screenshots/chat-en.png) | ![Dashboard: CEFR level, vocabulary size, streak and today's plan](docs/screenshots/dashboard-en.png) |
| ![Grammar practice: a wrong translation, graded with the correction and the grammar point](docs/screenshots/practice-en.png) | ![Writing: each sentence corrected, mistakes explained, four scores](docs/screenshots/writing-en.png) |
| ![Reading: a news article rewritten for A2, words above the level underlined](docs/screenshots/reading-en.png) | ![Vocabulary: today's FSRS queue and word books](docs/screenshots/vocab-en.png) |

<sub>Screenshots use a demo account with scripted model replies.</sub>

## What works now

**Learning**

- **A tutor that remembers you.** After each reply, a background step decides what is worth remembering (your goals, interests, recurring problems) and summarizes the conversation. The **Memory** page shows everything it keeps, and you can edit or delete any of it.
- **Grammar tracking.** The same step tags your mistakes against 119 grammar points (A1–C2). Mastery is then updated by an algorithm (BKT and Elo), not scored by the model. The **Learner model** page shows each point with the evidence behind it, and you can delete any piece of evidence.
- **Vocabulary with FSRS.** Pick a word book (Oxford 3000, Zhongkao, Gaokao, CET-4/6, postgraduate entrance, IELTS, TOEFL or GRE), skip words you already know, and review daily on an FSRS schedule. The back of each card shows the Chinese meanings by part of speech and up to two real example sentences with human translations from Tatoeba; for words without one, AI examples are written ahead for the cards coming up in the next day (a background job you can switch off), or when you ask. Unfamiliar words from your conversations are collected automatically.
- **Replies you can follow.** Above the message box, switch the tutor between mostly Chinese and mostly English (until you choose, it follows your level: mostly Chinese at A1–A2 or before the placement test); it applies from the next reply. Hover or tap an English word in a reply to see its pronunciation, meanings, base form and the sentence it is in, ask for AI example sentences, or add it to your words. Every reply can be read aloud with the browser's own voices: the best ones on the device are picked automatically (Edge's Natural, Chrome's Google, macOS Premium voices), Chinese and English each in their own, sentence by sentence; under **Settings → Read aloud** (or the gear next to **Read aloud**) you can choose the voices, an American or British accent and the English speed, kept in that browser. If the site has a read-aloud route (Azure Speech, an OpenAI-compatible `/audio/speech` service such as SiliconFlow or OpenAI, or a local Kokoro), replies, words and review cards are read with that server voice instead, sentence by sentence; a sentence read once is cached and not billed again, and if the service fails the browser's voices take over. Learners can turn the server voice off for their browser and clear the recordings made for them; recordings unused for 30 days are deleted. Admins can also generate a whole word book's pronunciations ahead of time under **Settings → Word pronunciations** (with the words, characters, size and an estimated cost shown first; generated in the background in batches, can be paused and resumed, and carries on after a restart), so reading a word aloud plays it with no model call. Replies can also be shown in Chinese or English; translations are saved, so switching back and forth calls no model.
- **Shadowing.** Next to a tutor reply, after each reading paragraph and after each review example sentence, a microphone lets you listen to the sentence and read it back (up to 30 seconds). With pronunciation assessment set up (Azure Speech, under **Settings → Pronunciation**), you get an overall score with accuracy, fluency, completeness and (American English) prosody, each word coloured by how well you said it, and the sounds of a word you tap; words you said wrong can go to your word list and are marked on their review cards. Without it, a speech-to-text model compares what it heard with the sentence and shows the words left out or heard as others, labelled as a rough result. Recordings are not kept; your readings are listed on the learner model page, where you can delete them.
- **Speaking practice.** On the **Speaking** page, pick a scenario for your level (introducing yourself, a job interview, ordering food, asking for directions and more) or just chat. The tutor plays the other person and speaks first. Hold the microphone button to talk (or tap once to start and again to send; on a desktop, hold the space bar); what you said is transcribed and sent, and the reply is read aloud as it is written. If the transcript got you wrong, fix your last voice message and it is sent again. The tutor keeps the conversation going instead of correcting every sentence; when you finish you get a summary: what went well, your mistakes with corrections, more natural ways to say things, and expressions to try next time, each of which you can shadow or add to your words. Mistakes count as grammar evidence, except in very short voice turns that may be misheard. Without speech-to-text you can practise by typing.
- **Placement test.** About 10 minutes: up to 40 vocabulary and 20 grammar questions, adaptive, with no model involved. It sets your CEFR level. It can also mark your word book's words that you very likely know, all at once: you confirm first, and you can undo it.
- **Dashboard.** Word book progress, grammar mastery, skill estimates, common mistakes and a study calendar, plus today's conversation with the tutor. The algorithm picks what is worth doing and offers it as quick replies; the tutor talks it over with you, with cards you can confirm. One conversation a day, created with your first message, so opening the dashboard calls no model. Without a model you get the algorithm's picks as links.
- **Today's plan.** On the dashboard, a plan for today fitted to your daily minutes: due reviews, new words, a practice set, an article, and sometimes a piece of writing, with the estimated time. It is drafted by an algorithm, so opening the dashboard calls no model. Adjust the counts and switch items on or off before confirming; each item links to where you do it and ticks off as you go. Speaking practice is an optional item: switch it on and it counts as done once you have spoken for 5 minutes yourself that day. Tell the tutor in today's conversation that you only have 10 minutes, and it proposes a lighter plan on a card; confirming replaces the plan, and you can undo it.
- **Focused practice.** Start a conversation on one grammar point from the dashboard or the Learner model page. The tutor opens it and steers every turn toward that point.
- **Practice sets.** On the **Grammar practice** page, a set of short exercises (multiple choice, fill in the blank, find and fix, transform, translate, rewrite your own sentence) on the grammar points worth practising now. A model writes the items, a second model call (the critic) checks each one before you see it, and answers are graded by code where possible, by a model otherwise. Every answer is evidence for mastery; a point counts as learned only after correct answers on different days. You can flag a bad item.
- **Writing feedback.** On the **Writing** page, write 20–800 words on a task for your level, one of your own, or none. Each sentence comes back with its mistakes marked (tap one for the explanation and grammar point) and the corrected sentence below, plus four scores (task, coherence, vocabulary, grammar) and overall feedback. The mistakes go into your learner model; the scores are only shown. Paste a long piece of your writing into chat and it is handed to the writing coach, who reviews it the same way and links to the result. Deleting a piece removes its mistakes from your learner model too.
- **Graded news reading.** The **Reading** page lists new articles from the feeds you follow: NASA news, Global Voices, and RSS feeds you add yourself. Opening one rewrites it for your level (once per level, then cached; it can also be prepared in the background) with five comprehension questions, each checked by a critic. Hover or tap any word for the same word popup as in chat; words due for review today are highlighted, and words above your level are underlined. Your answers update a reading skill estimate shown on the dashboard. You can switch to the original, and **Ask the tutor about this article** opens a conversation with the reading coach, who can see the text. Feeds that only give a summary, or whose license does not allow adaptation, are shown as they are, with a link to the source.
- **Grammar diagnosis.** When the same grammar points keep going wrong, the tutor looks at them together with their prerequisites and easily confused points and writes a short diagnosis on the Learner model page: the likely root cause, with the sentences it is based on, and what to do. The points it names come up more in practice sets for two weeks. If it is wrong, delete it. It runs in the background about once a week when there are new mistakes, and after a practice set with several new ones; you can switch it off.
- **The tutor can act, with your consent.** In chat, the tutor can propose a word book, a learning goal or today's plan as a card. Nothing changes until you confirm, and you can undo it. After the placement test, a planning conversation on the result page turns the result into a plan.

**Transparency**

- **What the tutor did.** Under each reply you can expand what the tutor read, which tools it called, and what it wrote down afterwards. [docs/agent-tools.md](docs/agent-tools.md) lists every tool and background step.
- **AI usage labels.** Each feature that calls a model has an "AI" badge. It shows which model tasks run and roughly how many tokens each use costs, before you click.
- **Background work you control.** Work the tutor does while you are away (preparing your next practice set, rewriting new articles for your level, writing AI example sentences for tomorrow's words, diagnosing your mistakes) can be switched off item by item under Settings → Background work. Owners set a daily token budget for all background calls (0 turns them off); what you start yourself is never limited. Scheduled jobs run inside the single backend process, so deploy one backend instance.

**Platform**

- **Bring your own models.** Each account adds model connections in the app: a preset (DeepSeek, Anthropic, OpenAI, Qwen, Groq, SiliconFlow, …) or any OpenAI-compatible endpoint. API keys are encrypted in the database. The app lists the models a connection offers; you choose the model order per task, with automatic fallback. A connection, or a single model in a task's order, can be switched off and back on without losing its settings.
- **Attachments in chat.** Images (read by a vision model); PDF, DOCX, TXT and Markdown documents (scanned PDF pages go to the vision model); voice messages recorded in the browser and audio files (transcribed by a speech-to-text model). You can check and correct the extracted text before sending.
- **Usage table:** calls, tokens, errors, fallbacks and latency per day and model.
- **English and Chinese UI.**

Not built yet (see [docs/PLAN.md](docs/PLAN.md)): real-time voice conversation (P3); evaluation in CI, rate limiting and cost dashboards (P4).

## Quick start (Docker)

You need Docker with Compose v2, `make`, `openssl`, and [uv](https://docs.astral.sh/uv/) for the one-time word list import. The stack runs in about 1.7 GB of RAM (Postgres, backend and frontend are memory-capped); building the images the first time takes a few minutes.

```bash
git clone https://github.com/YangD1/lingo-agent.git
cd lingo-agent
make env   # creates .env with a fresh encryption key and JWT secret
make up    # builds and starts postgres + backend + frontend; migrations run automatically
make vocab-import   # once: downloads and imports the word list (about 15 seconds)
make sentences-import   # once, after vocab-import: example sentences for the flashcards (about 10 seconds)
```

The word list is [ECDICT](https://github.com/skywind3000/ECDICT) (MIT, 66 MB, pinned to one commit and checked by sha256). It is saved in `data/`, and about 38,000 words are imported: exam lists, the Oxford 3000, Collins-starred words and the 30,000 most frequent. The vocabulary pages and the placement test need it. You can run it again safely. If GitHub is unreachable, set `ECDICT_URL` to a mirror of the same file, or pass a local copy with `make vocab-import CSV=path/to/ecdict.csv`. Without uv on the host: download the file, then run `docker compose cp ecdict.csv backend:/tmp/` and `docker compose exec backend python -m app.services.vocab.import_ecdict --csv /tmp/ecdict.csv`.

Example sentences on the flashcards come from [Tatoeba](https://tatoeba.org) ([CC BY 2.0 FR](https://creativecommons.org/licenses/by/2.0/fr/)): English sentences with human Chinese translations, at most two per word, each linked to its page on Tatoeba. The three per-language exports (about 27 MB) are saved in `data/tatoeba/`; Tatoeba updates them weekly, so the import prints each file's date and sha256 instead of checking a fixed hash. Run `make sentences-import REFRESH=1` to fetch a newer export, or `make sentences-import DIR=path/to/exports` to use local copies. Words without a real sentence still have the "AI examples" button. Without uv on the host: download `eng/eng_sentences.tsv.bz2`, `cmn/cmn_sentences.tsv.bz2` and `cmn/cmn-eng_links.tsv.bz2` from <https://downloads.tatoeba.org/exports/per_language/> into one folder, run `docker compose cp that-folder backend:/tmp/tatoeba`, then `docker compose exec backend python -m app.services.vocab.import_tatoeba --dir /tmp/tatoeba`.

Then:

1. Open <http://localhost:3000> and create an account.
2. Go to **Settings → Model connections**, add a connection (for example DeepSeek), paste your API key, and save its default model.
3. Take the **Placement test** (about 10 minutes). On its result page you can talk the result over with the tutor, right there.
4. Go to **Chat** and start talking, or to **Vocabulary** to pick a word book. With a single connection you don't need to set any model order: its default model is used automatically.

`make ps` shows service status, `make logs` follows the logs, `make down` stops the stack (your data is kept in Docker volumes). `make help` lists every command.

> **Keep `.env` safe.** `CREDENTIALS_ENCRYPTION_KEYS` in it encrypts the API keys stored in the database: lose it and the stored keys can't be read (users have to enter them again). To rotate it, see `make rotate-credentials`.

## Configuring models

API keys are never put in `.env` or YAML files: each user enters their own in **Settings**. The YAML files in [`config/`](config) only define the presets and the default model order per task; `PROVIDERS_CONFIG` in `.env` picks the file.

Four tasks have their own ordered model list under **Settings**:

| Task | Used for | Needs |
|---|---|---|
| Chat model | Replies, practice openings and the planning conversation | Any chat model; tool calling for the tutor's cards (without it the tutor only gives links) |
| Background memory model | Memory, grammar tagging and word collection after each reply | Any chat model; a smaller, cheaper one is fine |
| Image model (vision) | Images and scanned PDF pages | A model that accepts images |
| Speech-to-text | Voice messages and audio files | An OpenAI-compatible `/audio/transcriptions` endpoint |

Any other task uses the default model order in `config/`. The chat and memory tasks and any other calls fall back to each connection's default model, so one connection is enough to start. Vision and speech-to-text never fall back: set them up explicitly. On each connection, the **Test** button can test the model for chat, speech-to-text or images. If you have the connection the embedding route in `config/` names (by default `openai`, for `text-embedding-3-small`), memories are searched by meaning. Otherwise the most recent ones are used.

For speech-to-text, the Groq and SiliconFlow presets are the easiest start. Groq and OpenAI refuse requests from some regions, mainland China included; SiliconFlow (`FunAudioLLM/SenseVoiceSmall`) is reachable there.

**A model server on your own machine (e.g. Ollama).** By default the backend refuses addresses on private networks, to protect a shared server from requests aimed at its internal network (SSRF). On a machine only you use:

1. Set `PROVIDER_ALLOW_PRIVATE_NETWORKS=true` in `.env` and run `make up` again.
2. Add a **Custom** connection. From the Docker stack, use `http://host.docker.internal:11434/v1`, not `localhost` (inside the container, `localhost` is the backend itself), and make Ollama listen beyond 127.0.0.1 (`OLLAMA_HOST=0.0.0.0`). A backend run directly on the host (see below) uses `http://localhost:11434/v1`, so the Ollama preset works as is.

**Local speech-to-text (optional, for development).** `make asr-up` starts [speaches](https://github.com/speaches-ai/speaches) (faster-whisper) on port 8200; the first start downloads the model. It needs about 1.4 GB of RAM while transcribing. Then, with private networks allowed, add a connection from the **Speaches** preset (base URL `http://asr:8000/v1` from the Docker stack, `http://localhost:8200/v1` from a host-run backend) and put `speaches:Systran/faster-whisper-small` on the speech-to-text route. See the comments in [`.env.example`](.env.example).

**Local read-aloud (optional, for development).** The same container also reads aloud with Kokoro: download it once with `curl -X POST http://localhost:8200/v1/models/speaches-ai/Kokoro-82M-v1.0-ONNX`, then put `speaches:speaches-ai/Kokoro-82M-v1.0-ONNX` on the read-aloud route. It reads American and British English only (no Mandarin in speaches 0.9; Chinese is left to the browser). Measured on a development machine: about 0.9 GB of RAM once loaded, 1.5 GB with two requests at once, and about 2 seconds for a 9-second sentence. Without a read-aloud route the browser reads aloud (ADR 0018); in production, use a hosted service such as Azure Speech (ADR 0028).


## Development

Besides Docker you need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you), Node.js 24 and pnpm (`corepack enable` gives you the version pinned in `frontend/package.json`).

```bash
make env            # if you haven't yet
make install        # backend and frontend dependencies, from the lockfiles
make dev-db         # only postgres, on localhost:5433
make migrate        # apply database migrations
make dev-backend    # API with auto-reload on :8000       (terminal 1)
make dev-frontend   # Next.js dev server on :3000         (terminal 2)
```

The frontend proxies `/api` to the backend, so open <http://localhost:3000> as before.

Tests and checks (they need `make dev-db`; tests use their own databases and never call real model APIs):

```bash
make test     # pytest + Vitest
make e2e      # Playwright; starts its own backend, frontend and a fake model
make lint     # ruff + mypy, eslint + TypeScript
make fmt      # format and autofix backend code
make ci       # everything CI runs, in the same order
make eval     # evaluation sets (critic, grading, diagnosis) replayed from recorded model replies
```

`make eval-live ARGS='--email <account>'` runs the evaluation sets against the models of one of your accounts instead (add `--record` to save new recordings); it calls real APIs and costs tokens.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs backend checks, frontend checks, the Docker build and the end-to-end tests on every push to `main` and every pull request.

## Architecture

```mermaid
flowchart LR
    B[Browser] -->|:3000| F["Next.js<br/>(pages + /api proxy)"]
    F -->|"HTTP / SSE"| A[FastAPI]
    A --> G["LangGraph<br/>supervisor → coaches + tools ·<br/>practice · writing · reading ·<br/>diagnosis · placement test"]
    G -->|"after each reply"| R["Background reflection<br/>memory · grammar tags ·<br/>word collection"]
    R --> L["Learner model<br/>(BKT / Elo mastery,<br/>grammar graph)"]
    A --> V["Vocabulary and grammar reviews<br/>(FSRS scheduling)"]
    S["Scheduler<br/>feeds · pre-generation ·<br/>daily budget"] --> G
    G --> P["Provider layer<br/>(per-tenant connections,<br/>fallback chains)"]
    R --> P
    P --> M[("Model APIs:<br/>LLM · vision ·<br/>speech-to-text · embeddings")]
    A --> D[("PostgreSQL + pgvector<br/>users · encrypted keys · conversations ·<br/>memories · mastery · cards · words")]
```

The browser only talks to Next.js; the login cookie is httpOnly and requests reach the API through the same-origin proxy. Every model call goes through the provider layer, which builds each tenant's models from their own connections; business code never creates a vendor SDK client or hardcodes a model name. Models understand and write; algorithms keep the books: mastery is updated from evidence by BKT and Elo, reviews are scheduled by FSRS, and the placement test is scored without a model.

```
backend/app/     FastAPI app: api/ routes, agents/ LangGraph graphs (supervisor and coaches),
                 providers/ model access, memory/ long-term memory and reflection,
                 adaptive/ grammar points, mastery, grammar graph, practice sets and diagnosis,
                 placement/, writing/, services/ vocab (word books, FSRS), news (feeds) and
                 reading (rewrites, questions), scheduler/ background jobs, cards/ tutor tools,
                 advice/, dashboard/, usage/, attachments/, prompts/,
                 credentials/ key encryption, db/ models and migrations
backend/evals/   evaluation sets with recorded model replies (make eval)
backend/tests/   pytest (unit + integration against a real Postgres)
frontend/        Next.js App Router, shadcn/ui, next-intl; e2e/ Playwright tests
config/          provider presets and default model order (dev / prod)
docs/            PLAN.md (design), PROGRESS.md (status), decisions/ (ADRs),
                 agent-tools.md (every tool and background step)
```

Design documents:

- [docs/PLAN.md](docs/PLAN.md): the full design and roadmap
- [docs/plans/P1-mvp.md](docs/plans/P1-mvp.md): the P1 implementation plan
- [docs/plans/P2-adaptive-reading-writing.md](docs/plans/P2-adaptive-reading-writing.md): the P2 implementation plan
- [docs/decisions/](docs/decisions): architecture decision records, e.g. [provider layer](docs/decisions/0002-provider-layer.md), [tenant credentials](docs/decisions/0004-tenant-credentials.md), [attachments](docs/decisions/0008-multimodal-attachments.md), [long-term memory](docs/decisions/0009-long-term-memory.md), [learner model](docs/decisions/0010-learner-model.md), [vocabulary and FSRS](docs/decisions/0011-vocabulary-and-fsrs.md), [agent tools and disclosure](docs/decisions/0013-agent-tools-and-disclosure.md), [AI usage labels](docs/decisions/0014-ai-usage-disclosure.md), [confirmation cards](docs/decisions/0015-tutor-tools-and-confirmation-cards.md), [exercise engine](docs/decisions/0021-exercise-engine.md), [grammar graph](docs/decisions/0022-grammar-graph-in-postgres.md), [supervisor and coaches](docs/decisions/0023-supervisor-and-coaches.md), [reading sources and copyright](docs/decisions/0024-reading-sources-and-copyright.md), [scheduler and background budget](docs/decisions/0025-scheduler-and-background-budget.md), [daily plan](docs/decisions/0027-daily-plan.md)

## Deploying

The Docker stack is meant to run on a small server. Before exposing it:

- Set `APP_ENV=prod` and `PROVIDERS_CONFIG=config/providers.prod.yaml`. In prod the login cookie is only sent over HTTPS, so put an HTTPS reverse proxy in front of port 3000.
- Keep `PROVIDER_ALLOW_PRIVATE_NETWORKS=false`.
- Only the frontend port is public; Postgres and the backend listen on 127.0.0.1.
- The backend fetches the reading feeds every two hours. If some sources are unreachable from your server's network, set `FEED_HTTP_PROXY` (or `COMPOSE_FEED_HTTP_PROXY` for the compose backend); it is used for feeds only, and it checks addresses less strictly than a direct fetch (see `.env.example`).

## Contributing

Issues and pull requests are welcome. Please run `make ci` before opening a pull request and use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` …).

## License

[MIT](LICENSE)

Data used at runtime, downloaded by the import commands and not included in this repository: the word list from [ECDICT](https://github.com/skywind3000/ECDICT) (MIT) and example sentences from [Tatoeba](https://tatoeba.org) ([CC BY 2.0 FR](https://creativecommons.org/licenses/by/2.0/fr/)).

Reading articles are fetched by the backend from RSS feeds and kept only in your own database: [NASA news](https://www.nasa.gov/news-release/feed/) (US government work, public domain; Astronomy Picture of the Day is skipped) and [Global Voices](https://globalvoices.org) (CC BY 3.0; stories republished from partners are skipped). Feeds that learners add themselves are shown only inside their own tenant.
