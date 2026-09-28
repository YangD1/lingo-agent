# 0002 · Provider 层：配置格式、路由与降级语义

- **状态**：已采纳；**key 的来源和启动校验两部分已被 ADR 0004 取代**（下文用删除线标出），路由格式、降级语义、embedding 不降级仍有效
- **日期**：2026-09-28

## 背景
PLAN.md 要求所有模型调用都走配置驱动的 provider 层：按任务（task）路由模型、支持降级链（fallback），并能接入任意 OpenAI 兼容厂商。落地前需要定下四件事：配置文件怎么组织、配置写什么格式、对外暴露哪些接口、降级在流式和结构化输出下具体怎么表现。

## 决定

### 1. 配置文件
- 按环境分成两份**完整的** YAML：`config/providers.dev.yaml`、`config/providers.prod.yaml`，用环境变量 `PROVIDERS_CONFIG` 选择，默认用 dev。两份文件不做深合并。
- 文件分四段：
  - `providers`：厂商**预设**，包括 `kind`（`deepseek` / `anthropic` / `openai` / `openai_compatible`）和默认 `base_url`。~~`api_key_env`~~：已删除，key 由租户在应用内配置（ADR 0004）。
  - `defaults`：共享的调用参数（`timeout`、`max_retries`）。
  - `llm`：`default` 加上 `routes.<task>`。
  - `embedding`：同上。
- 模型统一写成 `"<provider 名>:<模型名>"`。每条路由可以写三种形式：单个字符串、列表（主模型 + 降级链）、对象（`models` 加上调用参数覆盖）。
- `max_retries` 默认设成 1：失败时尽快切到下一个厂商，而不是在同一个厂商上反复重试。

### 2. 启动时校验
- 引用了未定义的 provider 名，启动失败。
- ~~某个模型的 `api_key_env` 对应的环境变量为空时，把它从链里去掉；整条链都不可用时启动失败。~~ 已被 ADR 0004 取代：租户没有配置对应连接的模型会被跳过；整条链都不可用时，请求返回 `no_llm_configured`，不影响启动。
- 启动时只校验 `llm` 段的所有路由。`embedding` 段在第一次调用 `get_embeddings` 时才解析。原因是 P0 还没有功能用到 embedding；另外 DeepSeek 不提供 embedding，只配了 DeepSeek key 的开发者如果启动时就校验 embedding，服务会起不来。等某个功能依赖 embedding 了，再把它加入启动校验。

### 2.5 embedding 不做降级链
- `embedding` 的每条路由**只能写一个模型**，写成列表会在加载配置时报错。
- 原因：不同的 embedding 模型输出的向量属于不同的向量空间，维度也可能不一样。如果调用失败后悄悄换一个模型，新写入的向量和库里已有的向量就无法比较，相似度检索的结果会错，而且不会报任何错。embedding 调用失败时应该直接报错；换模型必须作为一次显式的迁移来做（重新计算全部向量）。

### 3. 对外接口（业务代码只出现 task 名，不出现模型名）
- 注：以下接口在 ADR 0004 中都增加了第一个参数 `ctx: TenantProviderContext`。
- `get_llm(task)`：带降级链的聊天 Runnable。
- `get_structured_llm(task, schema)`：先对链上的**每个**模型调用 `with_structured_output(schema)`，再串成降级链。
- `get_chat_model(task)`：只返回主模型（`BaseChatModel`），用于需要 `bind_tools` 等专有方法的场景。
- `get_embeddings(task)`：返回 embedding 模型。
- 所有模型都用 `langchain.chat_models.init_chat_model` / `init_embeddings` 构造。`openai_compatible` 在构造时映射为 `model_provider="openai"` 并传入 `base_url`。
- 构造好的实例按 task 缓存，同时打上 `task:<task>` 和 `provider:<名>` 两个 tag，方便在 trace 和用量统计里按 task 和厂商区分。

### 4. 降级语义（依据 langchain-core 1.6.5 `runnables/fallbacks.py`）
- **流式调用**：`RunnableWithFallbacks.astream` 只在取第一个 chunk（`await anext(stream)`）时捕获异常并切到下一个模型。第一个 chunk 发出之后再出错，会直接抛出，这样可以避免把两个模型的输出拼在一起。上层（SSE 接口）遇到这种情况，要给前端发一个 `error` 事件。
- **结构化输出和工具绑定不依赖 `__getattr__` 转发**：`RunnableWithFallbacks.__getattr__` 的做法是用 `typing.get_type_hints()` 判断被调方法的返回值是不是 Runnable，是的话就把调用转发给每个 fallback。问题有两个：
  - 如果注解里引用的类型只在 `TYPE_CHECKING` 下导入，这一步会抛 `NameError`。实测 `GenericFakeChatModel(...).with_fallbacks([...]).bind_tools([...])` 就会触发。
  - mypy 也看不到这些动态转发出来的方法。

  所以统一在 provider 层显式包装：先给每个模型绑定，再串成降级链。

## 取舍
- 两份完整 YAML 会有重复内容，但读哪份就知道实际生效的是什么，不用在脑子里做合并。
- 缺 key 时自动跳过，让只配了一家厂商的开发者也能直接跑起来。代价是配置写错时不会报错，只在启动日志里留一条 warning。
- `get_chat_model` 不带降级链，所以需要工具调用的场景暂时没有降级。等到 P1 真正需要工具调用时，再补一个 `get_tool_llm(task, tools)`，按同样的“先绑定、再串链”方式实现。
