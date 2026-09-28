# 进度看板

> 状态：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成 · `[!]` 阻塞（写明原因）
> 阶段定义见 `docs/PLAN.md` 第四节。只在 P0 细化任务，后续阶段开始时再拆分。

**当前阶段**：P0 骨架（任务 1–9 完成；任务 10 进行中：10.3 api.ts / sse.ts）
**阻塞项**：无（真实 key 冒烟测试改为任务 10 后在设置页里做）

## P0 骨架
- [x] 方案设计确认（docs/PLAN.md）
- [x] 仓库初始化、会话记忆协议（CLAUDE.md / PROGRESS / SESSION_LOG / ADR）
- [x] P0 详细实施计划（`docs/plans/P0-skeleton.md`，Q1–Q6 均按推荐确认）
- [x] 1. ADR 0002（provider 层）、0003（鉴权与流式传输）
- [x] 2. backend 脚手架：uv 项目、ruff/mypy/pytest 配置、settings.py、main.py、/healthz
- [x] 3. provider 层 v1（从环境变量读 key）。被 ADR 0004 部分取代，由任务 8 改造
- [x] 4. ADR 0004（多租户凭据）、0005（可观测性）已采纳；改写 ADR 0002 被取代的部分；同步 PLAN / CLAUDE.md / README / .env.example（YAML 结构调整并入任务 8，和代码一起改）
- [x] 5. 可观测性 B：可选 OTel tracing（OpenInference + OTLP，默认关闭）+ compose 的 observability profile（Phoenix）；验证 LangGraph 节点的覆盖情况
- [x] 6. 数据库：compose postgres、SQLAlchemy async（psycopg3）、Alembic（users、tenants、tenant_members、conversations、provider_connections、tenant_model_routes、llm_usage）、/readyz
- [x] 7. 鉴权：argon2 + JWT（httpOnly cookie / Bearer）；注册时自动建个人租户；get_current_user / get_current_tenant
- [x] 8. 凭据与 provider 层 v2：YAML 改为“预设 + 默认路由”、AES-GCM 加密、SSRF 防护、TenantProviderContext、按租户缓存、连接和路由 CRUD 及 /test；可观测性 A：`llm_usage` 表 + 回调 + 用量查询接口
- [x] 9. 对话图（通过运行时 context 传 ctx）+ AsyncPostgresSaver + 会话 CRUD + SSE 接口 + 集成测试
  - [x] 9.1 图与 checkpointer：lifespan 里建 `AsyncConnectionPool`（小连接池）和 `AsyncPostgresSaver`；`app/agents/chat_graph.py`（START → tutor → END，`context_schema=ChatContext`，ctx 走运行时 context）；`app/prompts/tutor_system.md`；测试确认 checkpoint 里没有 key
  - [x] 9.2 会话 CRUD：`app/chat/service.py` + `app/api/chat.py`（列表、新建、历史消息、删除时同时 `adelete_thread`）；访问别人的会话一律 404
  - [x] 9.3 发消息 SSE：`POST /conversations/{id}/messages`，事件为 token / done / error；开流前先检查模型配置；首条消息生成标题并刷新 updated_at；metadata 带 user_id，让 llm_usage 记到人
  - [x] 9.4 集成测试（假模型跑图、SSE 事件顺序、历史读回、越权、断开连接）和真实 uvicorn + curl 冒烟；同步 ADR 0003 / P0 计划
- [~] 10. frontend：Next 16 + shadcn、登录/注册页、聊天页、模型设置页（含用量表）、SSE 客户端、proxy.ts
  - [x] 10.1 脚手架与代理验证：Next 16.3.6 + React 19.2 + Tailwind 4.3 + shadcn（base-nova，底层 Base UI）+ Vitest 5 + Playwright 1.63（chromium）；`/api/*` rewrite 到 `BACKEND_URL`（**构建时**确定）。**SSE 实测结论**：dev 和 `next start` 都会 gzip `text/event-stream`，并把整段回复缓冲到最后一次发出 → 后端 `start_turn` 追加 `Cache-Control: no-transform` 修复（单独提交 fix(chat)），不需要备选方案；abort 能经过代理传到后端。typecheck、lint、build、Vitest、Playwright 冒烟全部通过
  - [x] 10.2 i18n（ADR 0006）：next-intl 4.14，不做 URL 语言前缀；`getRequestConfig` 按 `NEXT_LOCALE` cookie → Accept-Language → en 的顺序确定语言（**与原计划不同**：不在 proxy 里写 cookie，cookie 只在用户主动切换时由 Server Action 写入）；`messages/en.json` 和 `zh-CN.json`，`global.ts` 让 key 带类型检查；`useErrorMessage()` 按 code 查文案，找不到就显示后端的 message。**前置**：后端所有错误统一为 `{detail:{code,message}}`，422 转成 `validation_error`（单独提交）。验证：Vitest 17 个测试（语言协商、两份文案的 key 和占位符一致、错误映射）+ Playwright i18n E2E 2 个；typecheck、lint、build 都通过
  - [~] 10.3 `lib/api.ts`（fetch 封装，统一解析 `{detail:{code,message}}` 错误）+ `lib/sse.ts`（`streamChat`：fetch POST + eventsource-parser + AbortController）及其 Vitest 单测
  - [ ] 10.4 登录和注册页、`proxy.ts` 鉴权（没有 cookie 就跳 /login；proxy 只负责鉴权，语言在 request.ts 里确定）、登出
  - [ ] 10.5 聊天页：会话列表、消息区、输入框、流式渲染、停止生成；409 的两个错误码给出引导（跳到设置页）
  - [ ] 10.6 模型设置页：连接管理（选预设、填 key、测试连接）、chat 路由覆盖、用量表
  - [ ] 10.7 Playwright E2E：`frontend/e2e/fake_llm.py` 是一个假 OpenAI 兼容服务（逐字流式输出，带 usage），用 uv 运行；后端以 `PROVIDER_ALLOW_PRIVATE_NETWORKS=true` 启动并使用独立测试库。用例：注册 → 未配置模型时的引导 → 在设置页建连接（base_url 指向假服务）→ 流式对话 → 停止生成 → 刷新后历史还在 → 用量表有数据 → 切换语言 → 登出后访问受保护页会跳 /login
  - [ ] 10.8 收尾：typecheck、lint、build、Vitest、Playwright 全部通过；经 Next 代理用 curl 端到端冒烟；同步 ADR 0003、P0 计划和看板
- [ ] 11. docker-compose 全栈 + .env.example + Makefile（gen-key / rotate-credentials）
- [ ] 12. GitHub Actions CI（backend / frontend / docker build）
- [ ] 13. README（英文 + zh-CN）+ CLAUDE.md 常用命令

## P1 MVP：私教对话 + 长期记忆 + 背单词 + 入学测 + 自适应引擎 v1
- [ ] （进入 P1 时拆分）

## P2 自适应引擎完整版 + 阅读 + 语法 GraphRAG + 写作
- [ ] （进入 P2 时拆分）

## P3 语音（级联 + 实时双模式）
- [ ] （进入 P3 时拆分）

## P4 企业级打磨
- [ ] （进入 P4 时拆分）
