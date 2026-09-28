# 进度看板

> 状态：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成 · `[!]` 阻塞（写明原因）
> 阶段定义见 `docs/PLAN.md` 第四节。只在 P0 细化任务，后续阶段开始时再拆分。

**当前阶段**：P0 骨架（任务 1–10 完成；下一步：任务 11 docker-compose 全栈）
**阻塞项**：无（待用户手动：在设置页填自己的真实 key 做一次冒烟，代码和 E2E 已就绪）

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
- [x] 10. frontend：Next 16 + shadcn、登录/注册页、聊天页、模型设置页（含用量表）、SSE 客户端、proxy.ts
  - [x] 10.1 脚手架与代理验证：Next 16.3.6 + React 19.2 + Tailwind 4.3 + shadcn（base-nova，底层 Base UI）+ Vitest 5 + Playwright 1.63（chromium）；`/api/*` rewrite 到 `BACKEND_URL`（**构建时**确定）。**SSE 实测结论**：dev 和 `next start` 都会 gzip `text/event-stream`，并把整段回复缓冲到最后一次发出 → 后端 `start_turn` 追加 `Cache-Control: no-transform` 修复（单独提交 fix(chat)），不需要备选方案；abort 能经过代理传到后端。typecheck、lint、build、Vitest、Playwright 冒烟全部通过
  - [x] 10.2 i18n（ADR 0006）：next-intl 4.14，不做 URL 语言前缀；`getRequestConfig` 按 `NEXT_LOCALE` cookie → Accept-Language → en 的顺序确定语言（**与原计划不同**：不在 proxy 里写 cookie，cookie 只在用户主动切换时由 Server Action 写入）；`messages/en.json` 和 `zh-CN.json`，`global.ts` 让 key 带类型检查；`useErrorMessage()` 按 code 查文案，找不到就显示后端的 message。**前置**：后端所有错误统一为 `{detail:{code,message}}`，422 转成 `validation_error`（单独提交）。验证：Vitest 17 个测试（语言协商、两份文案的 key 和占位符一致、错误映射）+ Playwright i18n E2E 2 个；typecheck、lint、build 都通过
  - [x] 10.3 `lib/api.ts`（`api<T>()` / `apiFetch()` / `ApiError{status,code,message,issues}`；非 JSON 错误归为 `http_<status>`，断网归为 `network_error`，abort 原样抛出）+ `lib/sse.ts`（`streamChat()` 是 async generator：fetch POST → TextDecoderStream → EventSourceParserStream；开流前的错误抛 ApiError；保证以 done 或 error 结束，流意外断开时补一个 `stream_interrupted`；忽略未知事件）。13 个单测，其中一个用真实 Node HTTP 服务验证：中途 abort 会抛 AbortError，并且服务端看到连接关闭
  - [x] 10.4 登录和注册页（共用 `AuthForm`，错误按 code 显示对应文案）；`src/proxy.ts` 只做乐观检查（cookie 是否存在、JWT 的 exp 是否过期，不验签）：没登录访问 /chat、/settings 会跳到 `/login?next=…`（`safeNextPath` 防止开放重定向），已登录访问 /、/login、/register 会跳到 /chat；`(app)` 布局在服务端带 cookie 调后端 `/auth/me` 做权威校验，401 时跳到 `/session-expired` 清掉 cookie（否则签名无效但没过期的 token 会导致重定向死循环）；登出按钮。**提前完成了 10.7 的基础设施**：`e2e/run_backend.py`（每次重建 `lingo_e2e` 库，迁移后启动 uvicorn :8100）+ Playwright 的 webServer 同时拉起后端和前端。验证：Vitest 55 个、Playwright 5 个（含冷启动）、typecheck、lint 全部通过
  - [x] 10.5 聊天页：会话 id 放在 `/chat?c=<id>`，用 History API 同步（新建会话时页面不会重新挂载，流不会被打断；浏览器后退可用）；会话延迟创建，第一次发送时才建，开流前被拒绝（比如 409）就删掉空会话、撤回乐观显示的消息、把文字还回输入框；`no_llm_configured` 显示“去设置”按钮；停止生成后标注“未保存”（和后端只保存用户消息的行为一致）；Enter 发送，Shift+Enter 换行，输入法组字时按 Enter 不发送。核心逻辑在 `useChatSession`（5 个单测）。E2E 3 个（未配置模型时的引导、流式输出 + 刷新后历史还在 + 停止生成、切换和删除会话），用 `e2e/fake_llm.py`（10.7 的一部分，提前完成）
  - [x] 10.6 模型设置页：连接管理（选预设只需填 key；也可自定义 base_url；测试连接显示延迟；替换 key；删除）；chat 路由覆盖（按顺序填 `连接名:模型`，前端先校验格式，给出可选连接的建议，可恢复默认）；用量表（7/30/90 天，带合计行，手动刷新，因为用量是异步写入的）。`invalid_provider_config` 和 `validation_error` 会附上后端给的具体原因。新增 `ui/native-select.tsx`（原生 select，语言切换器也改用它）。E2E 2 个（全程在 UI 里配置假模型 → 聊天 → 用量表有数据；预设只需填 key，错误输入有提示）；typecheck、lint、Vitest 60 个、Playwright 共 10 个全部通过
  - [x] 10.7 Playwright E2E：基础设施在 10.4/10.5 已提前完成——`e2e/fake_llm.py`（假 OpenAI 兼容服务，流式 + 非流式，带 usage；消息含 “long” 时慢速逐字输出，用来测停止生成）、`e2e/run_backend.py`（独立 `lingo_e2e` 库、`PROVIDER_ALLOW_PRIVATE_NETWORKS=true`）、三个 webServer（假模型 :8101、后端 :8100、Next 生产构建 :3100）。用例共 11 个：auth 3（含登出后访问受保护页跳 /login、坏 token 不死循环）、chat 3、settings 2（UI 建连接 → 聊天 → 用量表）、i18n 3（本次补上：登录后在应用内切换语言，服务端布局和客户端组件都切换，会话和 URL 保持不变）。全部通过
  - [x] 10.8 收尾：typecheck、lint、build、Vitest 60 个、Playwright 11 个全部通过；Next 生产构建 + 后端 + 假模型全栈 curl 冒烟（注册 → 建连接 → 设路由 → 建会话 → 流式）：token 每 0.1s 逐块到达，响应无 content-encoding、带 `no-transform`，历史已保存，404 为统一错误格式；同步 P0 计划 §8（`/chat?c=`、async generator、两层鉴权、i18n、`BACKEND_URL` 构建时确定）、§10 CI 前端 job、任务 10 验收标准；ADR 0003 此前已同步
- [ ] 11. docker-compose 全栈 + .env.example + Makefile（gen-key / rotate-credentials）
  - [x] 11.1 后端镜像：`backend/Dockerfile` 两个阶段都基于 `python:3.12-slim-bookworm`（uv 二进制从 `ghcr.io/astral-sh/uv:0.11.8` 拷入，`uv sync --locked --no-dev`；两阶段 Python 路径相同，venv 拷过去不断链），以非 root 运行（uid 10001）；代码在 `/app/backend`，`config/` 在运行时挂到 `/app/config`；启动时先 `python -m app.db.migrate` 再 `exec uvicorn`（单 worker）；HEALTHCHECK 调 `/healthz`。**没有用 `# syntax=docker/dockerfile:1`**：BuildKit 解析它时直连 Docker Hub，本机代理环境下超时，而默认前端已支持 `RUN --mount`。验证：镜像 494MB；空库迁移 → healthy → `/readyz` ok → 注册 201；重启后没有重复迁移；缺加密 key 时拒绝启动并提示 `make gen-key`；空闲内存约 140MiB
  - [x] 11.2 前端镜像：`frontend/Dockerfile`（node:24-slim + corepack pnpm；deps / build / runtime 三阶段；`BACKEND_URL` 既作构建参数写进 rewrites，也作运行时 env 给 `server-api.ts`；运行 standalone 的 `server.js`，用户 node，HEALTHCHECK 请求 `/login`）+ `.dockerignore`；`next.config.ts` 加 `output: "standalone"` 和 `experimental.cpus`（`NEXT_BUILD_CPUS`，默认 4）；构建阶段 `NODE_OPTIONS=--max-old-space-size=2048`。**`pnpm start` 改为 `scripts/start-standalone.mjs`**（`next start` 不支持 standalone；脚本拷贝 static/public 后启动 `server.js`），E2E 也改跑它（`PORT`/`HOSTNAME=127.0.0.1`），测试和镜像用的是同一个产物。验证：镜像 386MB，构建约 60s；容器冒烟：匿名访问 /chat → 307 到 /login?next、经 /api 注册 201、带 cookie 访问 /chat 200（运行时 BACKEND_URL 生效）；前端 65MiB、后端 186MiB；typecheck、lint、Vitest 60、Playwright 11 通过
    - 踩坑：两次 docker 构建把 **Windows 提交内存**耗尽（vmmemWSL ~10GB + MuMu ~7.7GB，上限 39.7GB），WSL 和模拟器一起崩；WSL 内部的 cgroup 上限和看门狗没用。用户已设 `.wslconfig`：`memory=8GB`、`swap=4GB`、`[experimental] autoMemoryReclaim=dropCache`，页面文件改为系统管理（提交上限变为 56.7GB）。之后构建时 Windows 可用提交内存最低 32.6GB。本机另有一个限 3G、4 核的 buildx 构建器 `lingo-capped`（只在本机，不写进仓库）
  - [x] 11.3 `docker-compose.yml`：新增 backend（`build: ./backend`，`config/` 只读挂载，容器内 `DATABASE_URL` 由 `POSTGRES_*` 拼出、指向 `postgres:5432`，OTel 默认发往 `phoenix:6006`，可用 `COMPOSE_OTEL_EXPORTER_OTLP_ENDPOINT` 覆盖；`extra_hosts: host.docker.internal:host-gateway` 方便连宿主机的 Ollama；mem_limit 768m）、frontend（`BACKEND_URL=http://backend:8000` 同时作为 build arg 和 env；mem_limit 384m）；依赖链 postgres → backend → frontend，都等 `service_healthy`。**宿主机端口：只有前端对外（3000），postgres、backend、phoenix 都只绑 127.0.0.1**；neo4j（`neo4j:5-community`）、redis（`redis:8-alpine`）分别放在同名 profile 里，默认不启动。**与计划不同**：不用 `${CREDENTIALS_ENCRYPTION_KEYS:?}`，因为 compose 会对整个文件插值，连 `docker compose up -d postgres` 也会被拦；改为由后端拒绝启动并提示 `make gen-key`。验证：`compose config` 在没有 `.env` 和打开全部 profile 时都通过；用临时 env 文件执行 `up -d --build`，三个服务都 healthy，内存 postgres 29MiB、backend 167MiB、frontend 46MiB；经前端代理访问 `/api/readyz` 返回 ok。踩坑：第一次崩溃留下的 pnpm 缓存里有半截写入的文件（`vite/package.json` 为空）→ `ERR_PNPM_CMD_SHIM_PARSE_MANIFEST`；用 `docker buildx prune --filter id=<pnpm 缓存 id>` 只清掉那一个缓存后恢复正常
  - [x] 11.4 `.env.example`：补 `POSTGRES_USER/PASSWORD/DB`、`FRONTEND_HOST_PORT`、`BACKEND_HOST_PORT`、`BACKEND_URL`、`COMPOSE_OTEL_EXPORTER_OTLP_ENDPOINT`，并说明同一份 `.env` 在 compose 和在宿主机运行两种方式下的用法（compose 忽略其中的 `DATABASE_URL`、`BACKEND_URL`）、APP_ENV=prod 需要 HTTPS、容器里怎么连宿主机的 Ollama。`Makefile`：`help`（自动列出带 `##` 注释的目标）、`env`（从 example 生成，openssl 生成加密 key 和 64 位 hex 的 JWT_SECRET，文件权限 600，已存在就不覆盖；`ENV_FILE` 可改路径）、`gen-key`（和 Python CLI 格式一致，不依赖 uv）、`up/down/build/logs/ps`、`rotate-credentials`（在 backend 容器里执行，注释写了四步流程）、`dev-db/migrate/dev-backend/dev-frontend/install`、`test/test-backend/test-frontend/e2e/lint/fmt`；`PNPM`、`COMPOSE` 可覆盖。`dev-frontend` 从根 `.env` 读取 `BACKEND_URL`（Next 只读 `frontend/` 下的 env 文件），优先级：环境变量 > .env > 默认 :8000。验证：`make env` 生成的 key 能被后端解析器接受、加解密往返成功，JWT_SECRET 通过 prod 校验，第二次执行不覆盖；`make lint` 全过；`make test` 212 + 60 个通过；dev-frontend 的三种取值都正确
  - [~] 11.5 从零验证：用临时 env 文件（不碰真实 `.env`）执行 `docker compose up -d --build`，经 :3000 走完 注册 → 建连接（宿主机上的假模型）→ 流式对话 → 重启容器后历史还在；执行 `rotate-credentials`；用 `docker stats` 记录内存；同步 P0 计划 §0 Demo、§9 和看板
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
