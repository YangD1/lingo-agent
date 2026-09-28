# P0 骨架 · 详细实施计划

> 状态：**已确认**（2026-09-28，Q1–Q6 均按推荐）。确认后按任务顺序实现，任务清单同步在 `docs/PROGRESS.md`。
> 上位设计见 `docs/PLAN.md` 第四节 P0。本文件只写 P0 范围内“怎么做”；超出 P0 的只留接口、不实现。

## 0. P0 的完成定义（Demo 脚本）

`docker compose up -d` →（首次）`make migrate` → 浏览器打开 `http://localhost:3000`：

1. 注册账号 → 自动登录 → 进入聊天页
2. 发一句英文，回复逐 token 流式出现
3. 刷新页面 / 重新登录，历史消息还在（Postgres checkpointer）；新建第二个会话，两个会话互不串
4. LangSmith 里能看到这次对话的 trace，带 `user_id`、`conversation_id`、`task=chat` 元数据
5. 把 `providers.yaml` 里 chat 路由的主模型 key 置空/写错 → 自动降级到备用模型，对话不中断
6. `make test`、`make lint` 全绿；GitHub Actions 全绿

**P0 不做**：记忆抽取、Supervisor 多 Agent、Neo4j 业务代码、语音、限流、refresh token、邮箱验证。

---

## 1. 依赖版本（2026-09-28 查询 PyPI / npm 得到的最新版）

锁定策略：`pyproject.toml` 写 `>=当前小版本,<下一个大版本`，真正的精确版本由 `uv.lock` / `pnpm-lock.yaml` 锁定并提交。

### 后端（Python 3.12，uv 0.11）
| 包 | 版本 | 用途 |
|---|---|---|
| fastapi | 0.141 | Web 框架 |
| uvicorn[standard] | 0.54 | ASGI 服务器 |
| pydantic / pydantic-settings | 2.13 / 2.15 | 模型、配置 |
| langchain | 1.4 | `init_chat_model`、`init_embeddings` |
| langchain-core | 1.6 | Runnable、fallback |
| langchain-openai / -anthropic / -deepseek | 1.6 / 1.7 / 1.1 | 各厂商集成 |
| langgraph | 1.2 | 对话图 |
| langgraph-checkpoint-postgres | 3.1 | `AsyncPostgresSaver` |
| langsmith | 0.14 | tracing |
| sqlalchemy[asyncio] | 2.1 | ORM |
| alembic | 1.20 | 迁移 |
| psycopg[binary,pool] | 3.3 | **唯一的 PG 驱动**（SQLAlchemy 和 checkpointer 共用，见 §4） |
| pgvector | 0.5 | SQLAlchemy 的 Vector 类型（P0 只建扩展，不建向量列） |
| pyjwt | 2.15 | JWT |
| pwdlib[argon2] | 0.3 | 密码哈希（FastAPI 官方教程现推荐，替代 passlib） |
| ~~sse-starlette~~ | — | 不再使用：FastAPI 0.141 内置 `fastapi.sse`（任务 9 决定，见 ADR 0003） |
| pyyaml | 6.x | 读 providers.yaml |
| dev：pytest 9.1、pytest-asyncio 1.4、httpx 0.28、ruff 0.16、mypy 2.3 | | |

### 前端（Node 24 LTS，pnpm 12）
| 包 | 版本 | 说明 |
|---|---|---|
| next | 16.3 | App Router |
| react / react-dom | 19.2 | create-next-app 实际装的版本 |
| tailwindcss | 4.3 | v4，CSS-first 配置 |
| shadcn（CLI） | 4.21 | 预设 base-nova（底层 Base UI）；button / input / label / card / scroll-area / sonner / textarea |
| next-intl | 4.14 | 中英 i18n，不做 URL 语言前缀，语言存在 cookie 里（ADR 0006） |
| vitest / @testing-library/react | 5.0 / 16.3 | 单测，jsdom 环境 |
| @playwright/test | 1.63 | E2E，只装 chromium |
| eventsource-parser | 4.1 | 解析 POST 返回的 SSE 流（浏览器原生 `EventSource` 只支持 GET、不能带自定义头） |
| typescript | **5.9** | npm 最新已是 7.0（Go 原生编译器），Next 16 工具链兼容性未验证 |
| eslint | 以 `create-next-app` 生成的为准 | |

### 基础设施镜像
| 服务 | 镜像 | 默认启动 | 内存上限 |
|---|---|---|---|
| postgres | `pgvector/pgvector:pg16` | ✅ | 512M |
| backend | 自建（`ghcr.io/astral-sh/uv` 构建，`python:3.12-slim` 运行） | ✅ | 512M |
| frontend | 自建（Next `output: "standalone"`，`node:24-alpine`） | ✅ | 256M |
| neo4j | `neo4j:5-community`，heap 512M | ❌ profile `graph` | 1G |
| redis | `redis:8-alpine` | ❌ profile `cache` | 128M |

Neo4j / Redis 在 P0 没有业务代码使用，放进 compose **profiles** 默认不启动（见 Q3），`docker compose --profile graph up` 才起。

---

## 2. 目录结构（P0 实际落地的部分）

```
lingo-agent/
├── Makefile                      # dev / up / down / migrate / test / lint / fmt
├── docker-compose.yml
├── .env.example                  # 补充新变量（留空值）
├── config/
│   ├── providers.dev.yaml
│   └── providers.prod.yaml
├── backend/
│   ├── pyproject.toml            # uv 项目；ruff、mypy、pytest 配置都在这里
│   ├── uv.lock
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py               # create_app()、lifespan（DB 引擎、checkpointer、编译图）
│   │   ├── settings.py           # pydantic-settings：Settings
│   │   ├── deps.py               # FastAPI 依赖：get_session、get_current_user、get_graph
│   │   ├── api/
│   │   │   ├── health.py         # GET /healthz（存活）、/readyz（查 DB）
│   │   │   ├── auth.py           # POST /auth/register、/auth/login、/auth/logout；GET /auth/me
│   │   │   └── chat.py           # 会话 CRUD + POST /conversations/{id}/messages（SSE）
│   │   ├── auth/
│   │   │   ├── security.py       # hash_password / verify_password / create_token / decode_token
│   │   │   └── service.py        # register_user / authenticate
│   │   ├── providers/
│   │   │   ├── config.py         # YAML → Pydantic 配置模型、加载与校验
│   │   │   ├── llm.py            # get_llm / get_structured_llm
│   │   │   ├── embedding.py      # get_embeddings
│   │   │   └── errors.py         # ProviderConfigError 等
│   │   ├── agents/
│   │   │   └── chat_graph.py     # build_chat_graph(checkpointer)：START → tutor → END
│   │   ├── prompts/
│   │   │   └── tutor_system.md
│   │   ├── observability.py      # LangSmith 配置检查、run metadata 构造
│   │   └── db/
│   │       ├── base.py           # DeclarativeBase、命名约定
│   │       ├── session.py        # async engine / sessionmaker
│   │       ├── models.py         # User、Conversation
│   │       └── migrations/       # Alembic（async env.py）
│   └── tests/
│       ├── conftest.py           # 测试 DB、app 客户端、假 LLM 注入
│       ├── unit/                 # providers、security、settings
│       └── integration/          # auth API、chat 图 + SSE
├── frontend/
│   ├── Dockerfile
│   ├── next.config.ts            # rewrites /api/* → backend（见 Q1）
│   └── src/
│       ├── app/
│       │   ├── (auth)/login/page.tsx
│       │   ├── (auth)/register/page.tsx
│       │   └── chat/[[...id]]/page.tsx
│       ├── components/           # shadcn/ui + ChatMessages、ChatInput、ConversationList
│       ├── lib/api.ts            # fetch 封装（credentials: include）
│       ├── lib/sse.ts            # streamChat()：POST + eventsource-parser
│       └── proxy.ts              # 未登录跳 /login（Next 16 把 middleware.ts 更名为 proxy.ts，实现时按官方文档核对）
├── .github/workflows/ci.yml
└── docs/…
```

`memory/ adaptive/ services/ scheduler/ evals/` 在 P0 **不建空目录**，到对应阶段再建（避免空壳）。

---

## 3. Provider 层（核心设计，拟写 ADR 0002）

### 3.1 配置文件格式

按环境分两个文件，由 `PROVIDERS_CONFIG` 环境变量选择（默认 `config/providers.dev.yaml`）。不做 YAML 深合并——两份文件各自完整，读起来一目了然（见 Q5）。

```yaml
# config/providers.dev.yaml
providers:                       # 厂商连接信息：只写“怎么连”，不写密钥
  deepseek:  { kind: deepseek,  api_key_env: DEEPSEEK_API_KEY }
  anthropic: { kind: anthropic, api_key_env: ANTHROPIC_API_KEY }
  openai:    { kind: openai,    api_key_env: OPENAI_API_KEY }
  qwen:                          # 任意 OpenAI 兼容厂商都这么接
    kind: openai_compatible
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key_env: DASHSCOPE_API_KEY
  ollama:
    kind: openai_compatible
    base_url: http://localhost:11434/v1
    api_key_env: null            # 本地无需密钥

defaults:                        # 所有模型共享的调用参数，可被路由覆盖
  timeout: 30
  max_retries: 1                 # 刻意设小：重试放在 fallback 链上，而不是在单个厂商上死磕

llm:
  default: [deepseek:deepseek-chat, openai:gpt-4o-mini]    # 列表 = 主模型 + 降级链
  routes:                        # task 名 → 模型链；没配的 task 走 default
    chat:
      models: [deepseek:deepseek-chat, anthropic:claude-sonnet-5]
      temperature: 0.7
    # P1 起：router / tutor / memory_extract / critic ...

embedding:
  default: [openai:text-embedding-3-small]
```

规则：
- 模型写法 `"<provider 名>:<模型名>"`，provider 名必须在 `providers` 里定义，**启动时校验**，写错直接启动失败，不等到调用时才报错。
- 路由值可以是字符串（单模型）、列表（降级链），或对象（`models` + 调用参数）。
- 链里某个 provider 的 `api_key_env` 对应的环境变量为空 → 启动时 **跳过它并打 warning**（这样只填了 DeepSeek key 也能跑）；整条链都没有可用模型 → 启动失败。
- 业务代码中**不出现任何模型名**，只出现 task 名。

### 3.2 对外接口

```python
# app/providers/llm.py
def get_llm(task: str = "default", **overrides: Any) -> Runnable[LanguageModelInput, BaseMessage]:
    """返回按 task 路由、带 fallback 链的聊天模型。"""

def get_structured_llm(task: str, schema: type[T]) -> Runnable[LanguageModelInput, T]:
    """结构化输出版本：先对链上每个模型 with_structured_output，再串成 fallback。"""

def get_chat_model(task: str) -> BaseChatModel:
    """只返回主模型（不带 fallback），给需要 bind_tools 等 BaseChatModel 专有方法的场景。"""

# app/providers/embedding.py
def get_embeddings(task: str = "default") -> Embeddings
```

实现要点：
- 每个模型用 `langchain.chat_models.init_chat_model(model, model_provider=kind, base_url=..., api_key=..., timeout=..., max_retries=...)` 构造；`openai_compatible` 映射到 `model_provider="openai"` + `base_url`。
- 链用 `primary.with_fallbacks(rest)`；用 `functools.lru_cache` 按 (task, overrides) 缓存实例；测试里可 `cache_clear()`。
- 每个模型实例带 `tags=[f"task:{task}", f"provider:{name}"]`，LangSmith 里可以按 task / 厂商筛选和统计成本。

**为什么要有 `get_structured_llm`，而不是让调用方 `get_llm(...).with_structured_output(...)`**（已对照 langchain-core 1.6.5 源码 `runnables/fallbacks.py` 核实）：
- `with_fallbacks()` 返回 `RunnableWithFallbacks`，它本身没有定义 `with_structured_output` / `bind_tools`。它有一个 `__getattr__`：用 `typing.get_type_hints()` 看被调方法的返回类型，如果是 Runnable，就把这个方法同样应用到每个 fallback 上。
- 这个转发**依赖运行时能解析类型注解**。实测 `GenericFakeChatModel(...).with_fallbacks([...]).bind_tools([...])` 直接抛 `NameError: name 'BaseTool' is not defined`——因为该注解引用的类型只在 `TYPE_CHECKING` 下导入。能不能用，取决于每个集成包怎么写注解。
- mypy 看到的类型是 `RunnableWithFallbacks`，上面没有这些方法，strict 模式下会报错。
- 所以 provider 层显式做“先对每个模型绑定 schema/tools，再串 fallback”，不依赖这个隐式转发。

**Fallback 与流式的语义**（已对照同一文件的 `astream` 核实，实现时加单测）：流式调用时，`RunnableWithFallbacks` 只在 `await anext(stream)` 取**第一个 chunk** 时捕获异常并切换模型；第一个 chunk 已经发出后再出错，直接抛给调用方（不然用户会看到两个模型的回复拼在一起）。对话接口遇到这种情况给前端发 `error` 事件。

### 3.3 P0 只实现 LLM + Embedding
ASR / TTS / 发音评测 / realtime 在 P3 做，P0 不预留空接口。

---

## 4. 数据库

- **驱动统一用 psycopg3**：`langgraph-checkpoint-postgres` 只支持 psycopg3（不支持 asyncpg），SQLAlchemy 也用 `postgresql+psycopg` async，一个驱动、一套连接参数。`.env.example` 里的 `DATABASE_URL` 已经是这个格式。
- 两个连接池：SQLAlchemy 的 async engine（业务表）；`psycopg_pool.AsyncConnectionPool`（checkpointer，需 `autocommit=True, row_factory=dict_row`）。都在 lifespan 里创建和关闭。
- **Alembic 管业务表**；checkpointer 自己的表由 `AsyncPostgresSaver.setup()` 创建（它有内置迁移），**不进 Alembic**，在 `make migrate` 里一起执行。
- 第一个迁移：`CREATE EXTENSION IF NOT EXISTS vector` + 两张表：

| 表 | 字段 |
|---|---|
| `users` | id UUID PK、email（唯一，存小写）、password_hash、display_name、is_active、created_at、updated_at |
| `conversations` | id UUID PK、user_id FK → users（级联删除）、title、created_at、updated_at；索引 (user_id, updated_at desc) |

- LangGraph `thread_id` = `conversation.id`。每次读写会话前先校验 `conversation.user_id == 当前用户`，防止越权读别人的对话。
- 历史消息不单独存表，从 checkpointer 读 `graph.aget_state(config).values["messages"]`。

---

## 5. 鉴权

- 注册：email + 密码（≥8 位），argon2 哈希。登录成功签发 JWT（HS256，`sub=user_id`，`exp` 默认 7 天，`JWT_EXPIRE_MINUTES` 可配）。
- **令牌放在 httpOnly + SameSite=Lax 的 cookie 里**（生产加 Secure），不放 localStorage：前端 JS 读不到令牌，XSS 偷不走（见 Q1）。
- `get_current_user` 依赖同时接受 cookie 和 `Authorization: Bearer`（后者方便 curl / 测试 / 以后的移动端）。
- 前端通过 Next.js `rewrites` 把 `/api/*` 转发到后端，浏览器看来是同源，cookie 自然携带，不需要 CORS。
- `JWT_SECRET` 为默认值 `change-me` 且 `APP_ENV=prod` 时，**拒绝启动**。
- P0 不做 refresh token / 登出黑名单（登出 = 清 cookie），放到 P4。

---

## 6. 对话图与 SSE 接口

### 6.1 图
```
START → tutor → END          （state = MessagesState）
```
- `tutor` 节点：读 `prompts/tutor_system.md` 作为 system prompt，调 `get_llm("chat")`。
- 编译时传入 `AsyncPostgresSaver`；测试里换 `InMemorySaver` + 假模型。
- 结构刻意最小；P1 在这个图上加 `load_memory` / supervisor 路由 / `reflect_memory`。

### 6.2 接口
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/conversations` | 当前用户的会话列表 |
| POST | `/conversations` | 新建会话 |
| GET | `/conversations/{id}/messages` | 历史消息（从 checkpointer 读） |
| DELETE | `/conversations/{id}` | 删会话，同时删 checkpointer 里对应 thread（`adelete_thread`） |
| POST | `/conversations/{id}/messages` | 发消息，返回 SSE 流 |

### 6.3 SSE 事件协议（自定义，见 Q2）
```
event: token   data: {"text": "Hel"}
event: token   data: {"text": "lo!"}
event: done    data: {"message_id": "...", "usage": {...}}
event: error   data: {"code": "llm_unavailable", "message": "..."}
```
- 开流前的错误走 HTTP：404（会话不存在或越权）、409 `no_llm_configured`、409 `conversation_busy`（同一会话同时只允许一个回复在生成，进程内锁；多 worker 时换成 advisory lock，放到 P4）。
- 用 `graph.astream(..., stream_mode="messages")` 取 token，只转发 `tutor` 节点的 AI 消息 chunk。
- 调用时的 `config`：`configurable.thread_id`、`metadata={user_id, conversation_id}`、`tags=["chat"]`，LangSmith 自动带上。
- 客户端断开：图在独立 task 里运行，断开时显式取消，确保上游生成真正停止（仅靠 anyio 的取消传播不够，见 ADR 0003 的实现细节）；checkpointer 只记录已完成的节点，不会存半截回复。
- 响应头追加 `Cache-Control: no-transform`，否则 Next rewrites 代理会把 SSE gzip 压缩并缓冲整段回复（任务 10.1 实测，见 ADR 0003）。
- 首条消息后用消息前 40 个字符做会话标题（不额外调 LLM）。

---

## 7. LangSmith

- 只靠环境变量开启：`LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT`。LangChain / LangGraph 检测到这些变量会自动上报，不需要改业务代码。
- `observability.py`：启动时打印 tracing 是否开启、project 名；开了 tracing 却没填 key 时打 warning。
- **测试里强制 `LANGSMITH_TRACING=false`**（conftest 设置），保证测试不外发数据。

---

## 8. 前端

- `create-next-app`（TS strict、Tailwind、ESLint、App Router、`src/`）→ `shadcn init` → 加 button / input / card / scroll-area / sonner。
- 页面：`/login`、`/register`、`/chat`（左侧会话列表 + 右侧消息区，`/chat/[id]` 打开指定会话）。
- 流式：`lib/sse.ts` 里 `fetch` POST → `response.body` → `eventsource-parser` → 回调 `onToken/onDone/onError`；支持 `AbortController` 停止生成。
- 消息渲染 P0 用纯文本 + 换行，Markdown 渲染放 P1。
- `proxy.ts`：没有 cookie 的请求访问 `/chat` 跳 `/login`（只看 cookie 在不在，真正校验在后端）。

---

## 9. Docker Compose 与本地开发

两种运行方式：
- **日常开发**：`make dev-db`（只起 postgres）+ `make dev-backend`（uvicorn --reload）+ `make dev-frontend`（next dev），热重载。
- **一键演示 / 部署**：`docker compose up -d` 起全栈。

compose 要点：所有服务设 `mem_limit`；postgres 有 healthcheck，backend `depends_on: condition: service_healthy`；数据卷 `pgdata`；backend 以只读方式挂载 `config/`；backend 镜像入口先跑迁移再起 uvicorn（`make migrate` 也可单独跑）。

`.env.example` 新增（留空或安全默认值）：`APP_ENV=dev`、`PROVIDERS_CONFIG=config/providers.dev.yaml`、`JWT_EXPIRE_MINUTES=10080`、`DASHSCOPE_API_KEY=`、`POSTGRES_USER/PASSWORD/DB`、`BACKEND_URL=http://localhost:8000`（前端 rewrites 用）。

---

## 10. 测试 / Lint / CI

- **ruff**：`select = ["E","F","I","B","UP","ASYNC","RUF"]`，行宽 100；**mypy**：`strict = true`（第三方库缺类型的逐个 ignore）。
- **测试 DB**：本地用 compose 里的 postgres，建独立库 `lingo_test`；CI 用 GitHub Actions 的 service container（同一个 pgvector 镜像）。不引入 testcontainers（少一个依赖）。
- 测试清单：
  - `unit/test_provider_config.py`：YAML 解析、未知 provider 报错、缺 key 的模型被跳过、整链不可用报错
  - `unit/test_llm_router.py`：task 路由、默认回退、fallback 生效（主模型抛错 → 用备用）、流式首 chunk 前失败才切换、`get_structured_llm` 每个模型都带 schema
  - `unit/test_security.py`：哈希/校验、JWT 签发/过期/篡改
  - `unit/test_settings.py`：prod 下默认 JWT_SECRET 拒绝启动
  - `integration/test_auth_api.py`：注册 → 登录 → /me → 重复注册 409 → 错误密码 401
  - `integration/test_chat.py`：假模型（`GenericFakeChatModel`）跑图；SSE 事件顺序 token…done；历史可读回；越权访问别人会话 404
- **测试里不调用真实 LLM API**：provider 层提供测试注入点（conftest 里覆盖 `get_llm`），并且设置假的 API key，防止误调。
- **CI**（`.github/workflows/ci.yml`）：
  - backend job：`uv sync --locked` → `ruff check` → `ruff format --check` → `mypy app` → `alembic upgrade head` → `pytest`
  - frontend job：`pnpm install --frozen-lockfile` → `lint` → `tsc --noEmit` → `build`
  - docker job：`docker compose build`（只验证能构建）

---

## 11. 任务顺序（2026-09-28 修订：加入多租户凭据，见 §13 和 ADR 0004）

每项的完成标准：对应测试通过、lint 干净、看板已更新。

| # | 任务 | 验证 |
|---|---|---|
| 1 ✅ | ADR 0002、0003 | — |
| 2 ✅ | backend 脚手架 | 已完成 |
| 3 ✅ | provider 层 v1（从环境变量读 key）。**被 ADR 0004 部分取代**，由任务 8 改造 | 已完成 |
| 4 | ADR 0004 确认；改写 ADR 0002 中被取代的部分；YAML 删掉 `api_key_env`，改成“预设 + 默认路由” | 人工 review |
| 5 | LangSmith 接入（部署方的 key 仍放环境变量） | 手动看到 trace |
| 6 | DB：compose 里的 postgres、SQLAlchemy async、Alembic。表：users、tenants、tenant_members、conversations、provider_connections、tenant_model_routes；加 `/readyz` | `make migrate` 成功；`/readyz` 返回 200 |
| 7 | 鉴权：注册时自动建个人租户和 owner 成员关系；实现 `get_current_user` 和 `get_current_tenant` | auth 测试通过 |
| 8 | 凭据与 provider 层 v2：`crypto.py`（AES-GCM、AAD、主密钥轮换）；`net_guard.py`（保存时检查 URL，连接时检查 IP，ChatAnthropic 子类）；`TenantProviderContext` 和按租户的 LRU 缓存；连接和路由的 CRUD 以及 `/test` 接口 | 加密测试、SSRF 测试（私网、IPv6、rebinding 模拟）、路由解析测试、repr 和序列化结果不含 key |
| 9 | 对话图（通过运行时 context 传 ctx）、AsyncPostgresSaver、会话 CRUD、SSE 接口 | 集成测试；确认 checkpoint 里没有 key；没配模型时返回 `no_llm_configured` |
| 10 | 前端：登录和注册页、聊天页、**模型设置页**（连接列表、新增/编辑、测试连接、各任务路由编辑）、未配置模型时的引导 | lint、tsc、build 通过；浏览器里走通 Demo |
| 11 | docker-compose 全栈、`.env.example`、Makefile（含 `gen-key`、`rotate-credentials`） | `docker compose up` 后走通 Demo |
| 12 | GitHub Actions CI | CI 全绿 |
| 13 | README（英文 + zh-CN）；补充 CLAUDE.md 的常用命令 | 照着 README 能从零跑起来 |

## 12. 待确认的决定

- **Q1 令牌存哪**：推荐 **httpOnly cookie + Next rewrites 同源代理**；备选：Bearer token 存 localStorage + 后端开 CORS（实现更简单，但 XSS 能偷走令牌）。
  - 风险：Next rewrites 转发 SSE 时可能缓冲（开压缩时尤其）。任务 7/8 时先验证；若确实缓冲，SSE 这一个接口改为浏览器直连后端（带 cookie 的 CORS）。
- **Q2 流式协议**：推荐 **自定义 SSE 事件**（协议透明、前后端各 ~50 行、便于讲清原理）；备选：Vercel AI SDK 的 UI Message Stream 协议 + `useChat`（前端省事，但后端要按它的协议格式输出，且与其版本绑定）。
- **Q3 Neo4j / Redis**：推荐 P0 放进 compose **profiles 默认不启动**（P2 用到 Neo4j 时再默认开）；备选：P0 就全部默认启动。
- **Q4 TypeScript 版本**：推荐跟随 `create-next-app` 生成的版本（预计 5.x）；TS 7 等 Next 官方声明支持后再升级。
- **Q5 dev/prod 配置**：推荐 **两份完整 YAML，用 `PROVIDERS_CONFIG` 选择**；备选：一份 base + prod 覆盖深合并（更省字，但读配置时要在脑子里合并）。
- **Q6 类型检查**：推荐 mypy strict；备选：pyright（更快，但要装 Node 依赖到 Python CI）。

---

## 13. 修订：多租户凭据（2026-09-28，详见 ADR 0004）

- 模型厂商的 key 不再放环境变量或 YAML，由租户在“模型设置”页录入，加密存库。**只使用租户自己的 key**，没有平台兜底 key。
- 租户可以配置：连接（kind、名字、base_url、key、额外参数），以及各任务的路由（模型链、temperature、timeout、max_retries）。YAML 只提供预设和默认路由。
- 环境变量保留部署方自己的配置：`CREDENTIALS_ENCRYPTION_KEYS`、`JWT_SECRET`、`LANGSMITH_*`、`PROVIDER_ALLOW_PRIVATE_NETWORKS`。
- 其他章节里与此冲突的内容以本节为准：§3.1 的 `api_key_env`、§3 中“缺 key 时启动失败”、§9 的 `.env.example` 里的厂商 key。
- Demo 的第 5 步改为：在设置页把主模型的 key 改成错误的值，确认对话自动降级到备用模型。新增第 0 步：注册后进入设置页，填入 key 并测试连接。
- 新增依赖 `cryptography`（AES-GCM）。

---

## 14. 修订：可观测性（2026-09-28，详见 ADR 0005）

- **去掉 LangSmith**。它的平台是闭源 SaaS，自托管需要企业版授权。§1 中的 `langsmith` 依赖、§2 中“LangSmith 配置检查”、§7 整节、Demo 第 4 步都以本节为准。
- **A · `llm_usage` 用量表**（P0 必做）：LangChain 回调在后台批量写入，只记元数据不记内容；设置页展示租户自己的用量汇总。
- **B · OpenTelemetry tracing**（可选，默认关闭）：用 `openinference-instrumentation-langchain`、`opentelemetry-sdk` 和 OTLP HTTP 导出器，三者都是 Apache-2.0。环境变量为 `OTEL_TRACING_ENABLED`（默认 false）和 `OTEL_EXPORTER_OTLP_ENDPOINT`。compose 的 `observability` profile 里放 Phoenix 容器。
- Demo 第 4 步改为：设置页的用量表里能看到这次对话的 token 数；开启 OTel 后，在本地 Phoenix（http://localhost:6006）能看到带 tenant_id、conversation_id、task 的 trace。
- 测试中强制关闭 OTel。`LANGSMITH_TRACING=false` 仍然保留，因为 langsmith 是 langchain-core 的传递依赖，要防止开发者环境里的变量意外触发上报。

---

## 15. 任务 6 落地记录（2026-09-28）

- compose 里 postgres 映射到宿主机的端口改为可配置，默认 **5433**（`POSTGRES_HOST_PORT`），避免和本机已装的 Postgres 冲突。`DATABASE_URL` 的默认值相应改成 5433。
- 首次初始化数据卷时，`docker/postgres/init/01-create-test-db.sql` 会建 `lingo_test` 库。
- 统一迁移入口 `python -m app.db.migrate`：先执行 Alembic `upgrade head`，再执行 `AsyncPostgresSaver.setup()`。
- 迁移文件名格式为 `YYYYMMDD_<rev>_<slug>.py`，生成后自动跑 ruff format 和 ruff check --fix（alembic.ini 里的 post_write_hooks）。
- 测试的安全阀：库名不以 `_test` 结尾就拒绝运行。`test_models_match_migrations` 用 `compare_metadata` 检查模型改了却没写迁移的情况。
