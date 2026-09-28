# lingo-agent

开源 AI 英语私教 Agent：用户长期记忆、自适应学习引擎、CEFR 评估、FSRS 背单词、分级新闻阅读、语法 GraphRAG、语音对话。

- 设计：`docs/PLAN.md`（唯一权威，改设计必须同步改它）
- 当前进度（每次会话自动加载）：@docs/PROGRESS.md

## 会话协议（长任务，每次会话必须遵守）

跨会话的上下文靠仓库里的文件延续，不依赖对话记忆。

1. **开始**：看上面自动加载的进度看板，再读 `docs/SESSION_LOG.md` 最上面的 1–2 条交接记录。如果看板和代码实际状态不一致，以代码为准，并修正看板。
2. **先计划再动手**：每个阶段开工前，先把该阶段拆成具体任务写进 `docs/PROGRESS.md`，和用户确认后再写代码。
3. **进行中**：任务状态一变就更新看板（`[ ]` 未开始 / `[~]` 进行中 / `[x]` 完成 / `[!]` 阻塞，并写明原因）。**同一时间只能有一个 `[~]`。**
4. **做决定时**：架构或选型决定写成 ADR，放在 `docs/decisions/NNNN-短标题.md`（模板见 0001）；如果改了方案，同步更新 `docs/PLAN.md`。
5. **结束前 / 上下文快满时**：在 `docs/SESSION_LOG.md` **顶部**追加交接记录：做了什么 / 未完成（精确到文件和函数）/ 下一步 / 踩坑。然后更新看板的“当前阶段”。
6. **完成标准**：一个任务只有在测试通过、lint 干净、看板已更新时才能标 `[x]`。没验证过的，不写“完成”。

### 钩子（`.claude/hooks/lingo_hooks.py`，由本地 `.claude/settings.local.json` 启用）
- **SessionStart**：自动注入当前阶段、git status 和最新一条交接记录；如果是上下文压缩后重新开始，还会注入压缩前快照，并要求先补写交接记录。
- **PreCompact**：把压缩前的 git 状态保存到 `.claude/state/`（已 gitignore）。
- **Stop**：只要有代码文件比 PROGRESS/SESSION_LOG 更新，就拦下这一轮，要求先更新文档；同一轮只拦一次。
- **PreToolUse**：禁止写入 `.env*`（`.env.example` 除外）；禁止写入疑似密钥；`git commit` 前扫描暂存区，发现密钥或 env 文件就拒绝。
- **PostToolUse**：`.py` 文件改完自动执行 `ruff format`。
- 被钩子拦下时，按提示的原因处理，**不要绕过**（比如改用 Bash 去写 `.env`）。

## 目录结构（规划，P0 落地后以实际为准）

```
backend/app/
  api/         FastAPI 路由（只做参数校验和调用，不写业务逻辑）
  agents/      LangGraph 图：supervisor、各 coach 子图、assessor
  memory/      长期记忆抽取与读取、学习者模型
  adaptive/    BKT/Elo 掌握度、诊断、选题规划、练习生成 + critic
  providers/   llm / embedding / asr / tts / pronunciation / realtime
  services/    fsrs、cefr、vocab、news、graph(neo4j)
  scheduler/   APScheduler 任务
  prompts/     提示词模板（不在代码里内联长提示词）
  db/          SQLAlchemy 模型 + Alembic 迁移
backend/evals/ 评估数据集与评估器（pytest 驱动，见 ADR 0005）
backend/tests/
frontend/      Next.js App Router
config/        providers.dev.yaml / providers.prod.yaml（由 PROVIDERS_CONFIG 选择）
```

## 架构约束（改动前先确认没有违反）

- **LLM 负责理解和生成，算法负责记账和调度**：掌握度由 BKT/Elo 根据证据更新，复习由 FSRS 调度。**不让 LLM 直接给掌握度打分。**
- **所有模型调用都走 provider 层**（`get_llm("<task>")`、`get_asr()`……），由 `config/providers.*.yaml`（预设与默认路由）加租户在应用内配置的连接和路由驱动（见 ADR 0002、0004），并支持 fallback 链。业务代码里禁止直接实例化厂商 SDK 或写死模型名。
- LLM 生成的练习和题目**必须经过 critic 节点校验**才能交给用户。
- LLM 输出一律用 Pydantic 结构化输出，不靠正则解析自由文本。
- 线上服务器配置很低：重模型（whisper、TTS）只在 dev 本地跑，prod 走 API。新增依赖要考虑内存占用。
- 长期记忆写入要异步执行，不阻塞对话回复；用户必须能查看、编辑、删除自己的记忆。

## 代码规范

- **Python**：3.12，用 uv 管理依赖（`uv add`，不用 pip），全量类型注解，用 ruff 做格式化和 lint，I/O 一律 async。配置走 pydantic-settings。
- **TypeScript**：strict 模式，用 pnpm，组件用 shadcn/ui + Tailwind。
- **测试**：算法模块（FSRS、BKT/Elo、选题优先级、CEFR）必须有单测；LangGraph 图用 mock LLM 跑集成测试，测试里不调用真实 API。
- **提交**：Conventional Commits（`feat:`、`fix:`、`docs:`、`refactor:`、`test:`、`chore:`）。只在用户要求时才提交。

## 开源与安全

- 模型厂商的 key 由租户在应用内配置，加密存库，不放 `.env` 或 YAML。部署方自己的密钥（加密主密钥、JWT）和可观测性配置（OTel）只放 `.env`（已 gitignore）。新增环境变量时，同步更新 `.env.example`（留空值）。
- 不要提交个人学习数据、抓取的新闻全文、模型权重和 `data/` 目录。
- 仓库文档保持中性，不写个人背景信息。

## 常用命令

（P0 完成后补充：启动、测试、lint、数据库迁移、compose）
