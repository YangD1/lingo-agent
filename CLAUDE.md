# lingo-agent

开源 AI 英语私教 Agent：用户长期记忆、自适应学习引擎、CEFR 评估、FSRS 背单词、分级新闻阅读、语法 GraphRAG、语音对话。

本机如果有 `CLAUDE.local.md`（不进 git），会话协议、计划和进度以它为准。

## 决策记录

架构或选型决定写成 ADR，放在 `docs/decisions/NNNN-短标题.md`（模板见 0001）。

## 目录结构（规划，P0 落地后以实际为准）

```
backend/app/
  api/         FastAPI 路由（只做参数校验和调用，不写业务逻辑）
  agents/      LangGraph 图：supervisor、各 coach 子图、assessor
  memory/      长期记忆抽取与读取、学习者模型
  adaptive/    BKT/Elo 掌握度、诊断、选题规划、练习生成 + critic
  providers/   llm / embedding / asr / tts / pronunciation / realtime
  services/    fsrs、cefr、vocab、news
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
- **Agent 工具调用**（LangGraph tool、MCP、模型决定是否调用的函数）按 ADR 0013：身份从运行时 context 注入、不进工具参数；可能并行调用；失败作为工具结果返回、不中断整轮；循环有上限；工具结果是不可信数据；有副作用的工具要幂等、可撤销。**新增或修改任何工具、MCP、后台步骤，都要同步更新 `docs/agent-tools.md`**（公开清单），学习者也要能在界面上看到私教做了什么。
- **AI 用量公示**（ADR 0014）：新增任何会调用模型的功能，都要在 `backend/app/usage/features.yaml` 登记它触发的调用（task、时机、默认估计），并在前端入口挂 `AiBadge`，让学习者点之前就知道这里用 AI、每次大约多少 token。

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

以 `Makefile` 为准（`make help` 列出全部）。

- **首次**：`make env`（生成 `.env`，含加密主密钥和 JWT 密钥，不覆盖已有文件）→ `make install`
- **全栈（Docker）**：`make up`（构建 + 启动，后端启动时自动迁移）/ `make down` / `make ps` / `make logs`；可选本地语音转写 `make asr-up`
- **热重载开发**：`make dev-db`（只起 postgres，5433）→ `make migrate` → `make dev-backend`（:8000）+ `make dev-frontend`（:3000，`/api` 代理到后端）
- **测试**（都要先 `make dev-db`）：`make test`（pytest 默认 4 个 worker 并行，每个用自己的 `lingo_test_gwN` 库，约 1–2 分钟；`PYTEST_WORKERS=0` 串行；+ Vitest）、`make e2e`（Playwright，自带后端、前端和假模型）；单个后端测试：`cd backend && uv run pytest tests/path::name`
- **测试节奏**：拆任务时，每个子任务写明建议加哪层测试和理由，和任务一起给用户确认：
  - pytest：后端逻辑、接口、权限、迁移、算法、提示词装配；
  - Vitest：前端纯逻辑和组件状态（解析、格式化、条件渲染、状态切换）；
  - E2E：跨前后端的用户主流程、跳转、流式输出等只有真浏览器能暴露的问题；纯样式和文案不加 E2E。
  开发中只跑和改动相关的测试；收尾时把**受影响的层**各全量跑一次（没改后端就不跑全量 pytest，没改前端就不跑 Vitest / E2E），**不加 `-x`**，一轮看到全部失败。偶发失败先单独重跑确认，再修竞态，不要靠重跑碰运气。
- **检查**：`make lint`（ruff + mypy、eslint + tsc）、`make fmt`；推送前 `make ci`（和 GitHub Actions 同样的步骤）
- **新迁移**：`cd backend && uv run alembic revision --autogenerate -m "..."`，然后 `make migrate`
- **CI 结果**：`gh run list`、`gh run view <id> --log-failed`
