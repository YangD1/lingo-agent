# 0005 · 可观测性：自建用量记录 + 可插拔 OpenTelemetry，不再绑定 LangSmith

- **状态**：已采纳
- **日期**：2026-09-28
- **影响**：取代 PLAN.md 中“LangSmith 负责 tracing / 成本统计 / 评估”的设计，以及 ADR 0001 里关于 LangSmith 的部分。

## 背景
- LangSmith 平台是闭源 SaaS。要自己部署必须购买企业版授权并联系销售，没有开源或免费的自托管版本。用它就意味着把对话内容上传到第三方。这与项目“开源、低配服务器、能本地跑”的方向冲突。
- 调用模型的 key 由租户自己提供（ADR 0004），调用成本由租户承担，所以用量和成本数据应该**在应用内展示给租户**，而不是放在部署方的第三方后台里。
- 考察过的开源替代品：
  - **Langfuse**（MIT）：v3 起依赖 ClickHouse（至少 8G 内存）、Redis、S3/MinIO 和 Postgres，低配服务器跑不动。
  - **Arize Phoenix**（ELv2，源码可见，可以免费自部署）：单个容器，基于 OpenTelemetry。

## 决定

### A. 自建用量记录（必做，P0）
- 新建 `llm_usage` 表，每次模型调用记一行：tenant_id、user_id、conversation_id、task、connection、model、输入/输出 token、耗时、状态（`status`：ok / error）、是否为 fallback（`is_fallback`：主模型失败后由备用模型完成的调用）、错误码、时间。
- 通过 LangChain 回调（`on_chat_model_start` / `on_llm_end` / `on_llm_error`）采集，数据来源是 `usage_metadata`。在后台批量写入，不阻塞回复。
- **只记录元数据，不记录 prompt 和回复内容。**
- 租户能在设置页看到自己的用量（P0 只做按天和按模型的汇总表格，图表放到 P4）。
- 不在代码里内置价格表去换算金额：各厂商价格经常变，而且租户可能走中转代理，价格未必相同。只记 token 数；是否展示金额，以后作为租户可配置项再决定。
- **实现细节**（P0 任务 8 第 5 步）：
  - 构建模型时，`get_chat_models` 给 fallback 链里的每个模型挂一个 `UsageRecorder`（`app/usage/recorder.py`）。tenant、task、connection、model 和链中位置（`is_fallback`）在构建时就确定了。
  - 模型按租户缓存、同一租户所有用户共用，所以 `user_id` 和 `conversation_id` 在调用时通过 `RunnableConfig.metadata` 传入。metadata 会传给所有子调用；LangGraph 还会把 `configurable.thread_id` 自动复制进 metadata，所以会话 id 取 `conversation_id`，没有时取 `thread_id`。缺失或格式不对就记为 NULL，不报错，因为后台任务本来就没有这两个 id。
  - 错误只记异常类名，不记异常消息（消息里可能回显请求内容）。
  - **被取消的调用也要记**（客户端断开时，厂商已经为生成的 token 计费）。要做到这一点需要满足两个条件，都是冒烟时踩出来的：
    1. recorder 是同步的 `BaseCallbackHandler`，并设 `run_inline = True`。langchain-core 先同步调用 inline handler，再 `asyncio.gather` 其余 handler；在 anyio 电平触发的取消下，gather 会先被取消，异步 handler 就跑不到。
    2. 调模型用 `astream`，不用 `ainvoke`。`astream` 用 `except BaseException` 通知 `on_llm_error`；`ainvoke` 内部的 `await asyncio.gather(...)` 被取消时直接抛出，回调永远收不到。tutor 节点因此改为 astream 再合并 chunk。以后新增的节点只要可能被用户取消，都要这样写。
  - `stream_usage` 显式设为开启：我们总是自己传入 `base_url` 和 http client，ChatOpenAI 就不会自动开启它，流式调用会拿不到 token 数。个别服务不支持 `stream_options`，租户可以在连接参数里关掉。
  - `UsageWriter`（`app/usage/writer.py`）：用 asyncio 队列，攒满 50 行或每 2 秒批量写一次库。队列满了就丢弃并计数，写库失败只打日志，都不影响回复。lifespan 关闭时会把队列写完（最多等 5 秒）。
  - 连接的 `/test` 调用的也是租户的真实账户，所以同样会记录，task 为 `connection_test`。
  - 查询接口：`GET /tenant/usage?days=N`（1–90，默认 30，只有 owner 和 admin 能调），按 UTC 日期、连接和模型汇总调用次数、token 数、错误次数、fallback 次数和平均耗时。

### B. 可插拔的 OpenTelemetry tracing（可选，默认关闭）
- 埋点只做一次：`openinference-instrumentation-langchain`（Apache-2.0）通过 LangChain 的回调系统产生 OTel span，LangGraph 节点作为 Runnable 执行，也会被记录。实际覆盖情况在实现任务里验证。
- 用 `opentelemetry-sdk` 和 OTLP HTTP 导出器（都是 Apache-2.0）发送数据。**导出地址由环境变量决定**，不写死任何厂商。
  - `OTEL_TRACING_ENABLED=false`（默认值）：不初始化 tracer，没有任何开销。
  - 打开后，发送到 `OTEL_EXPORTER_OTLP_ENDPOINT`。开发时指向本机的 Phoenix 容器，它在 compose 的 `observability` profile 里，默认不启动，数据不会离开本机。部署方也可以把它指向 Langfuse、LangSmith，或任何接受 OTLP 的后端。
- trace 里包含**完整的对话内容**。所以 tracing 是部署方的决定，必须显式开启。`.env.example` 和 README 里要写明：如果把 trace 发往第三方，对话内容就会离开你的服务器。
- 测试中强制关闭 tracing。
- 如果想保留调用结构和耗时、但隐藏对话内容，可以用 OpenInference 的 `TraceConfig` 环境变量（如 `OPENINFERENCE_HIDE_INPUTS` / `OPENINFERENCE_HIDE_OUTPUTS`）遮蔽输入输出。
- 已验证（2026-09-28，任务 5）：LangGraph 根图、节点和模型调用分别生成 `LangGraph`、`tutor`、模型类名三个 span，属于同一条 trace；run metadata（tenant_id 等）会带到 span 上；通过真实的 OTLP/HTTP 导出到 Phoenix `version-20.16.0` 后，可以用 `/v1/projects/default/spans` 查回来。

### 评估（P4）
改为用 pytest 加仓库里的评估数据集（合成数据，不含真实用户数据）来跑，不依赖任何平台。如果想可视化，可以把评估结果以 OTel 或 Phoenix experiments 的形式导出，作为可选项。

P2 先落地了最小集（任务 36，`backend/evals/`）：critic 和批改两套，默认回放录制的真实模型输出、跟着 pytest / CI 跑，`make eval-live` 可换真实模型重跑或重录。P4 再接回归趋势和看板。

## 取舍
- 项目不再以“展示 LangSmith”为卖点，换成“厂商中立的 OpenTelemetry 观测，默认本地”。LangSmith 用户仍然可以通过 OTLP 接入。
- Phoenix 的许可证是 ELv2，不是 OSI 认证的开源许可。但它只以独立容器的形式、按需启动，不进入我们的依赖树，也不在我们的代码里分发，所以不影响本项目的开源许可。
- 自建用量统计需要多写一些代码（一张表、一个回调、一个查询接口），但换来了租户能直接看到自己的用量。
